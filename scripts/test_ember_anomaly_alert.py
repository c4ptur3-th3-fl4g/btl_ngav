#!/usr/bin/env python3
import argparse
import json
import random
import secrets
import socket
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import request

import joblib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATHS = [
    PROJECT_ROOT / "models" / "ember_anomaly.pkl",
    PROJECT_ROOT / "models" / "ember_ngav.pkl",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an EMBER anomaly event and send it to NGAV collector to test alert delivery."
    )
    parser.add_argument("--collector-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--endpoint", default=f"ember-alert-test-{socket.gethostname()}")
    parser.add_argument("--model-path", default="")
    parser.add_argument("--tries", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Only print the generated event; do not send it")
    args = parser.parse_args()

    model_path = _resolve_model_path(args.model_path)
    bundle = joblib.load(model_path)
    candidate, score, threshold = _find_anomalous_ember_features(bundle, tries=args.tries, seed=args.seed)

    event = {
        "endpoint": args.endpoint,
        "event_type": "ember_test_anomaly",
        "timestamp": time.time(),
        "data": {
            "ember_features": candidate,
            "test_marker": "ngav_forced_ember_anomaly_alert_test",
            "model_path": str(model_path),
            "expected_score": score,
            "expected_threshold": threshold,
        },
    }

    if args.dry_run:
        print(json.dumps(event, indent=2))
        return

    collector_url = args.collector_url.rstrip("/")
    api_key = args.api_key.strip() or _register_test_agent(collector_url, args.endpoint)
    response = _post_json(f"{collector_url}/ingest", event, api_key=api_key)

    print("[ok] sent EMBER anomaly test event")
    print(f"[ok] model: {model_path}")
    print(f"[ok] expected_score={score:.6f} threshold={threshold:.6f}")
    print(json.dumps(response, indent=2))
    print()
    print("Check:")
    print(f"  {collector_url}/detections?limit=5&anomalies_only=true")
    print(f"  {collector_url}/api/elastic/alerts?limit=5")
    print(f"  {collector_url}/ui")


def _resolve_model_path(model_path: str) -> Path:
    if model_path:
        path = Path(model_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    for path in DEFAULT_MODEL_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError("No EMBER model found. Expected models/ember_anomaly.pkl or models/ember_ngav.pkl")


def _find_anomalous_ember_features(bundle: Dict[str, Any], tries: int, seed: int) -> Tuple[Dict[str, float], float, float]:
    threshold = float(bundle["threshold"])
    candidates = list(_candidate_features(bundle, tries=tries, seed=seed))
    best_record: Optional[Dict[str, float]] = None
    best_score = float("-inf")

    for record in candidates:
        score = _score(bundle, record)
        if score > best_score:
            best_record = record
            best_score = score
        if score > threshold:
            return record, score, threshold

    raise RuntimeError(
        f"Could not generate an anomalous EMBER sample after {tries} tries. "
        f"Best score={best_score:.6f}, threshold={threshold:.6f}."
    )


def _candidate_features(bundle: Dict[str, Any], tries: int, seed: int) -> Iterable[Dict[str, float]]:
    feature_names = _feature_names(bundle)
    rng = random.Random(seed)

    yield {name: 0.0 for name in feature_names}
    yield {name: 1.0 for name in feature_names}
    yield {name: 999999.0 for name in feature_names}
    yield {name: -999999.0 for name in feature_names}

    choices = [0.0, 1.0, 10.0, 100.0, 1000.0, 10000.0, 999999.0]
    for _ in range(max(0, tries - 4)):
        yield {name: rng.choice(choices) for name in feature_names}


def _feature_names(bundle: Dict[str, Any]) -> List[str]:
    pipeline = bundle["pipeline"]
    vectorizer = getattr(pipeline, "named_steps", {}).get("vectorizer")
    names = list(getattr(vectorizer, "feature_names_", []) or [])
    if names:
        return names
    names = list(bundle.get("feature_columns", []) or [])
    if names:
        return names
    raise ValueError("EMBER model has no feature names")


def _score(bundle: Dict[str, Any], record: Dict[str, float]) -> float:
    pipeline = bundle["pipeline"]
    mode = bundle.get("score_mode", "negative_decision_function")
    if mode == "predict_proba":
        estimator = getattr(pipeline, "named_steps", {}).get("classifier")
        if estimator is not None and hasattr(estimator, "set_params"):
            try:
                estimator.set_params(device="cpu")
            except Exception:
                pass
        return float(pipeline.predict_proba([record])[0][1])

    raw = float(pipeline.decision_function([record])[0])
    if mode == "decision_function":
        return raw
    return -raw


def _register_test_agent(collector_url: str, endpoint: str) -> str:
    api_key = secrets.token_urlsafe(32)
    payload = {
        "endpoint": endpoint,
        "api_key": api_key,
        "os": "NGAV EMBER alert test",
        "os_name": "test",
        "hostname": socket.gethostname(),
        "machine": "test",
    }
    response = _post_json(f"{collector_url}/register_agent", payload)
    return str(response.get("api_key") or api_key)


def _post_json(url: str, payload: Dict[str, Any], api_key: str = "") -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
