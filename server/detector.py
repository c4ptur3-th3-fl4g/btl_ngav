import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib
import pandas as pd


DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "ngav.pkl"


@dataclass
class Detection:
    endpoint: Optional[str]
    event_id: Optional[str]
    event_type: Optional[str]
    score: float
    threshold: float
    is_anomaly: bool
    record: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "score": self.score,
            "threshold": self.threshold,
            "is_anomaly": self.is_anomaly,
            "record": self.record,
        }


class NgavDetector:
    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH, threshold: Optional[float] = None) -> None:
        self.model_path = Path(model_path).resolve()
        bundle = joblib.load(self.model_path)
        self.pipeline = bundle["pipeline"]
        self.feature_columns = list(bundle["feature_columns"])
        self.threshold = float(threshold) if threshold is not None else float(bundle["threshold"])

    def detect_event(self, event: Dict[str, Any]) -> List[Detection]:
        records = list(_extract_records(event))
        if not records:
            return []

        frame = _build_feature_frame(records, self.feature_columns)
        scores = -self.pipeline.decision_function(frame)

        detections: List[Detection] = []
        for record, score in zip(records, scores):
            score_value = float(score)
            detections.append(
                Detection(
                    endpoint=event.get("endpoint") or record.get("endpoint"),
                    event_id=event.get("id"),
                    event_type=event.get("event_type"),
                    score=score_value,
                    threshold=self.threshold,
                    is_anomaly=score_value > self.threshold,
                    record=record,
                )
            )
        return detections

    def detect_events(self, events: Iterable[Dict[str, Any]]) -> List[Detection]:
        detections: List[Detection] = []
        for event in events:
            detections.extend(self.detect_event(event))
        return detections


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
    parser.add_argument("--model", default=str(DEFAULT_MODEL_PATH), help="Path to trained NGAV model bundle")
    parser.add_argument("--threshold", type=float, help="Override threshold from the model bundle")
    parser.add_argument("--anomalies-only", action="store_true", help="Print only anomalous detections")
    args = parser.parse_args()

    detector = NgavDetector(Path(args.model), threshold=args.threshold)
    detections = detector.detect_events(load_events(Path(args.events_file)))
    for detection in detections:
        if args.anomalies_only and not detection.is_anomaly:
            continue
        print(json.dumps(detection.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    main()
