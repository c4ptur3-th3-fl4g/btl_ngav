import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib
import pandas as pd


DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "ngav.pkl"
DEFAULT_BEHAVIOR_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "behavior_model.pkl"
DEFAULT_EMBER_NGAV_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "ember_ngav.pkl"
DEFAULT_EMBER_ANOMALY_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "ember_anomaly.pkl"


@dataclass
class Detection:
    model_name: str
    endpoint: Optional[str]
    event_id: Optional[str]
    event_type: Optional[str]
    score: float
    threshold: float
    is_anomaly: bool
    record: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "endpoint": self.endpoint,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "score": self.score,
            "threshold": self.threshold,
            "is_anomaly": self.is_anomaly,
            "record": self.record,
        }


@dataclass
class ModelRunner:
    name: str
    path: Path
    pipeline: Any
    feature_columns: List[str]
    threshold: float
    feature_kind: str
    score_mode: str


class NgavDetector:
    def __init__(
        self,
        model_path: Optional[Path] = None,
        threshold: Optional[float] = None,
        include_behavior_model: bool = True,
        include_ember_models: bool = True,
    ) -> None:
        model_paths = [Path(model_path).resolve()] if model_path else [DEFAULT_MODEL_PATH]
        if include_behavior_model and DEFAULT_BEHAVIOR_MODEL_PATH.exists():
            behavior_path = DEFAULT_BEHAVIOR_MODEL_PATH.resolve()
            if behavior_path not in [path.resolve() for path in model_paths]:
                model_paths.append(behavior_path)
        if include_ember_models:
            for ember_path in [DEFAULT_EMBER_NGAV_MODEL_PATH, DEFAULT_EMBER_ANOMALY_MODEL_PATH]:
                resolved_ember_path = ember_path.resolve()
                if ember_path.exists() and resolved_ember_path not in [path.resolve() for path in model_paths]:
                    model_paths.append(resolved_ember_path)

        self.models = [_load_model_runner(path, threshold=threshold) for path in model_paths]
        if not self.models:
            raise ValueError("no NGAV models were loaded")

    def detect_event(self, event: Dict[str, Any]) -> List[Detection]:
        records = list(_extract_records(event))
        if not records:
            return []

        detections: List[Detection] = []
        for model in self.models:
            model_records = [record for record in records if _record_matches_model(record, model.feature_kind)]
            if not model_records:
                continue

            model_input = _build_model_input(model_records, model)
            scores = _score_model(model, model_input)
            for record, score in zip(model_records, scores):
                score_value = float(score)
                detections.append(
                    Detection(
                        model_name=model.name,
                        endpoint=event.get("endpoint") or record.get("endpoint"),
                        event_id=event.get("id"),
                        event_type=event.get("event_type"),
                        score=score_value,
                        threshold=model.threshold,
                        is_anomaly=score_value > model.threshold,
                        record=record,
                    )
                )
        return detections

    def detect_events(self, events: Iterable[Dict[str, Any]]) -> List[Detection]:
        detections: List[Detection] = []
        for event in events:
            detections.extend(self.detect_event(event))
        return detections


def _load_model_runner(path: Path, threshold: Optional[float] = None) -> ModelRunner:
    resolved_path = Path(path).resolve()
    bundle = joblib.load(resolved_path)
    model_name = resolved_path.stem
    return ModelRunner(
        name=model_name,
        path=resolved_path,
        pipeline=bundle["pipeline"],
        feature_columns=list(bundle.get("feature_columns", [])),
        threshold=float(threshold) if threshold is not None else float(bundle["threshold"]),
        feature_kind=bundle.get("feature_kind", "process"),
        score_mode=bundle.get("score_mode", "negative_decision_function"),
    )


def _extract_records(event: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    data = event.get("data")
    if not isinstance(data, dict):
        return []

    ember_features = data.get("ember_features") or data.get("pe_features")
    if isinstance(ember_features, dict):
        return [_tag_ember_record(ember_features)]

    records = data.get("records")
    if isinstance(records, list):
        return [_tag_record(record) for record in records if isinstance(record, dict)]

    record = data.get("record")
    if isinstance(record, dict):
        return [_tag_record(record)]

    if _looks_like_process_record(data):
        return [_tag_record(data)]

    if _looks_like_ember_record(data):
        return [_tag_ember_record(data)]

    return []


def _looks_like_process_record(data: Dict[str, Any]) -> bool:
    process_fields = {"pid", "ppid", "name", "exe", "username", "status", "cmdline_len"}
    return bool(process_fields.intersection(data.keys()))


def _looks_like_ember_record(data: Dict[str, Any]) -> bool:
    ember_fields = {"histogram", "byteentropy", "strings", "general", "header", "section", "imports", "exports", "datadirectories"}
    return bool(ember_fields.intersection(data.keys()))


def _tag_record(record: Dict[str, Any]) -> Dict[str, Any]:
    if "_feature_kind" in record:
        return record
    if _looks_like_ember_record(record):
        return _tag_ember_record(record)
    return {**record, "_feature_kind": "process"}


def _tag_ember_record(record: Dict[str, Any]) -> Dict[str, Any]:
    flattened: Dict[str, Any]
    if _looks_like_ember_record(record):
        flattened = dict(_flatten_ember_features(record))
    else:
        flattened = dict(record)
    flattened["_feature_kind"] = "ember"
    return flattened


def _flatten_ember_features(record: Dict[str, Any]) -> Dict[str, float]:
    features: Dict[str, float] = {}
    for key, value in record.items():
        if key in {"label", "sha256", "appeared", "avclass", "_feature_kind"}:
            continue
        _flatten_value(key, value, features)
    return features


def _flatten_value(prefix: str, value: Any, out: Dict[str, float]) -> None:
    number = _to_float(value)
    if number is not None:
        out[prefix] = number
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            _flatten_value(f"{prefix}.{key}", nested, out)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _flatten_value(f"{prefix}.{index}", item, out)


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def _record_matches_model(record: Dict[str, Any], feature_kind: str) -> bool:
    return record.get("_feature_kind", "process") == feature_kind


def _build_model_input(records: List[Dict[str, Any]], model: ModelRunner) -> Any:
    cleaned_records = [{key: value for key, value in record.items() if key != "_feature_kind"} for record in records]
    if model.feature_kind == "ember":
        return cleaned_records
    return _build_feature_frame(cleaned_records, model.feature_columns)


def _build_feature_frame(records: List[Dict[str, Any]], feature_columns: List[str]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = None
    return frame[feature_columns]


def _score_model(model: ModelRunner, model_input: Any) -> Any:
    if model.score_mode == "predict_proba":
        _prefer_cpu_inference_for_cpu_input(model.pipeline)
        probabilities = model.pipeline.predict_proba(model_input)
        return [float(row[1]) for row in probabilities]
    return _normalize_scores(model.pipeline.decision_function(model_input), model.score_mode)


def _prefer_cpu_inference_for_cpu_input(pipeline: Any) -> None:
    # XGBoost models may be trained on cuda:0, while collector inference passes CPU dict/sparse input.
    # Setting the estimator to CPU avoids XGBoost's mismatched-device fallback warning at runtime.
    estimator = getattr(pipeline, "named_steps", {}).get("classifier")
    if estimator is None or not hasattr(estimator, "set_params"):
        return
    try:
        estimator.set_params(device="cpu")
    except Exception:
        return


def _normalize_scores(raw_scores: Any, score_mode: str) -> Any:
    if score_mode == "decision_function":
        return raw_scores
    return -raw_scores


def load_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Score collector JSONL events with the trained NGAV model")
    parser.add_argument("events_file", help="Path to collector events.jsonl")
    parser.add_argument("--model", help="Path to a single trained NGAV model bundle")
    parser.add_argument("--threshold", type=float, help="Override threshold from the model bundle")
    parser.add_argument(
        "--ngav-only",
        action="store_true",
        help="Use only the main NGAV model and skip behavior_model.pkl",
    )
    parser.add_argument(
        "--no-ember",
        action="store_true",
        help="Skip EMBER static PE models",
    )
    parser.add_argument("--anomalies-only", action="store_true", help="Print only anomalous detections")
    args = parser.parse_args()

    detector = NgavDetector(
        Path(args.model) if args.model else None,
        threshold=args.threshold,
        include_behavior_model=not args.ngav_only,
        include_ember_models=not args.no_ember,
    )
    detections = detector.detect_events(load_events(Path(args.events_file)))
    for detection in detections:
        if args.anomalies_only and not detection.is_anomaly:
            continue
        print(json.dumps(detection.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
