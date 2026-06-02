import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib
import pandas as pd


DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "ngav.pkl"
DEFAULT_BEHAVIOR_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "behavior_model.pkl"


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


class NgavDetector:
    def __init__(
        self,
        model_path: Optional[Path] = None,
        threshold: Optional[float] = None,
        include_behavior_model: bool = True,
    ) -> None:
        model_paths = [Path(model_path).resolve()] if model_path else [DEFAULT_MODEL_PATH]
        if include_behavior_model and DEFAULT_BEHAVIOR_MODEL_PATH.exists():
            behavior_path = DEFAULT_BEHAVIOR_MODEL_PATH.resolve()
            if behavior_path not in [path.resolve() for path in model_paths]:
                model_paths.append(behavior_path)

        self.models = [_load_model_runner(path, threshold=threshold) for path in model_paths]
        if not self.models:
            raise ValueError("no NGAV models were loaded")

    def detect_event(self, event: Dict[str, Any]) -> List[Detection]:
        records = list(_extract_records(event))
        if not records:
            return []

        detections: List[Detection] = []
        for model in self.models:
            frame = _build_feature_frame(records, model.feature_columns)
            scores = -model.pipeline.decision_function(frame)
            for record, score in zip(records, scores):
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
        feature_columns=list(bundle["feature_columns"]),
        threshold=float(threshold) if threshold is not None else float(bundle["threshold"]),
    )


def _extract_records(event: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    data = event.get("data")
    if not isinstance(data, dict):
        return []

    records = data.get("records")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]

    record = data.get("record")
    if isinstance(record, dict):
        return [record]

    if _looks_like_process_record(data):
        return [data]

    return []


def _looks_like_process_record(data: Dict[str, Any]) -> bool:
    process_fields = {"pid", "ppid", "name", "exe", "username", "status", "cmdline_len"}
    return bool(process_fields.intersection(data.keys()))


def _build_feature_frame(records: List[Dict[str, Any]], feature_columns: List[str]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = None
    return frame[feature_columns]


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
    parser.add_argument("--anomalies-only", action="store_true", help="Print only anomalous detections")
    args = parser.parse_args()

    detector = NgavDetector(
        Path(args.model) if args.model else None,
        threshold=args.threshold,
        include_behavior_model=not args.ngav_only,
    )
    detections = detector.detect_events(load_events(Path(args.events_file)))
    for detection in detections:
        if args.anomalies_only and not detection.is_anomaly:
            continue
        print(json.dumps(detection.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
