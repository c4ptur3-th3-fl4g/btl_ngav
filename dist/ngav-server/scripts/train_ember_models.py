import argparse
import csv
import importlib.util
import json
import os
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MaxAbsScaler


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "models"


def iter_ember_samples(input_path: Path, max_files: Optional[int] = None) -> Iterable[Tuple[Dict[str, float], int]]:
    paths = _resolve_input_files(input_path, max_files=max_files)
    for path in paths:
        print(f"[info] reading {path}")
        if path.suffix.lower() == ".csv":
            yield from _iter_csv_samples(path)
        else:
            yield from _iter_jsonl_samples(path)


def load_subset(
    input_path: Path,
    limit: int,
    seed: int,
    strategy: str = "balanced",
    max_files: Optional[int] = 1,
) -> Tuple[List[Dict[str, float]], np.ndarray]:
    rng = random.Random(seed)
    if strategy == "balanced":
        return _load_balanced_subset(input_path, limit=limit, seed=seed, max_files=max_files)
    if strategy == "head":
        return _load_head_subset(input_path, limit=limit, seed=seed, max_files=max_files)

    reservoir: List[Tuple[Dict[str, float], int]] = []
    seen = 0

    for features, label in iter_ember_samples(input_path, max_files=max_files):
        if label not in {0, 1}:
            continue
        seen += 1
        item = (features, label)
        if len(reservoir) < limit:
            reservoir.append(item)
            continue
        replace_at = rng.randint(0, seen - 1)
        if replace_at < limit:
            reservoir[replace_at] = item

    if not reservoir:
        raise ValueError(f"no labeled EMBER samples found in {input_path}")

    rng.shuffle(reservoir)
    X = [features for features, _ in reservoir]
    y = np.array([label for _, label in reservoir], dtype=np.int64)
    return X, y


def _load_head_subset(input_path: Path, limit: int, seed: int, max_files: Optional[int]) -> Tuple[List[Dict[str, float]], np.ndarray]:
    rows: List[Tuple[Dict[str, float], int]] = []
    for features, label in iter_ember_samples(input_path, max_files=max_files):
        if label in {0, 1}:
            rows.append((features, label))
        if len(rows) >= limit:
            break

    if not rows:
        raise ValueError(f"no labeled EMBER samples found in {input_path}")

    rng = random.Random(seed)
    rng.shuffle(rows)
    X = [features for features, _ in rows]
    y = np.array([label for _, label in rows], dtype=np.int64)
    return X, y


def _load_balanced_subset(input_path: Path, limit: int, seed: int, max_files: Optional[int]) -> Tuple[List[Dict[str, float]], np.ndarray]:
    per_class_target = {0: limit // 2, 1: limit - (limit // 2)}
    buckets: Dict[int, List[Dict[str, float]]] = {0: [], 1: []}

    for features, label in iter_ember_samples(input_path, max_files=max_files):
        if label not in {0, 1}:
            continue
        if len(buckets[label]) < per_class_target[label]:
            buckets[label].append(features)
        if len(buckets[0]) >= per_class_target[0] and len(buckets[1]) >= per_class_target[1]:
            break

    rows: List[Tuple[Dict[str, float], int]] = []
    for label, items in buckets.items():
        rows.extend((features, label) for features in items)
    if not rows:
        raise ValueError(f"no labeled EMBER samples found in {input_path}")
    if len({label for _, label in rows}) < 2:
        raise ValueError(
            "subset contains only one class; increase --max-files or use --sample-strategy head/reservoir"
        )

    rng = random.Random(seed)
    rng.shuffle(rows)
    X = [features for features, _ in rows]
    y = np.array([label for _, label in rows], dtype=np.int64)
    return X, y


def train_ember_ngav(X: List[Dict[str, float]], y: np.ndarray, device: str, gpu_id: int = 0) -> Tuple[Pipeline, str]:
    if len(set(y.tolist())) < 2:
        raise ValueError("supervised NGAV training requires both benign label 0 and malware label 1")
    resolved_device = resolve_device(device)
    if resolved_device == "cuda" and importlib.util.find_spec("xgboost"):
        from xgboost import XGBClassifier

        cuda_device = f"cuda:{gpu_id}"
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(gpu_id))
        pipeline = Pipeline(
            [
                ("vectorizer", DictVectorizer(sparse=True)),
                (
                    "classifier",
                    XGBClassifier(
                        objective="binary:logistic",
                        eval_metric="logloss",
                        n_estimators=250,
                        max_depth=6,
                        learning_rate=0.08,
                        subsample=0.9,
                        colsample_bytree=0.9,
                        tree_method="hist",
                        device=cuda_device,
                        random_state=42,
                    ),
                ),
            ]
        )
        try:
            pipeline.fit(X, y)
            return pipeline, cuda_device
        except Exception as ex:
            if device == "cuda":
                raise
            print(f"[warn] XGBoost CUDA training failed, falling back to CPU: {ex}")

    pipeline = Pipeline(
        [
            ("vectorizer", DictVectorizer(sparse=True)),
            ("scaler", MaxAbsScaler()),
            (
                "classifier",
                SGDClassifier(
                    loss="log_loss",
                    class_weight="balanced",
                    max_iter=1000,
                    tol=1e-3,
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(X, y)
    return pipeline, "cpu"


def train_ember_anomaly(X: List[Dict[str, float]], y: np.ndarray, contamination: float) -> Tuple[Pipeline, float]:
    benign = [features for features, label in zip(X, y) if label == 0]
    if not benign:
        raise ValueError("anomaly training requires at least one benign EMBER sample")

    pipeline = Pipeline(
        [
            ("vectorizer", DictVectorizer(sparse=True)),
            ("scaler", MaxAbsScaler()),
            (
                "detector",
                IsolationForest(
                    n_estimators=200,
                    contamination=contamination,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipeline.fit(benign)
    train_scores = -pipeline.decision_function(benign)
    threshold = float(np.quantile(train_scores, 1.0 - contamination))
    return pipeline, threshold


def save_bundle(path: Path, pipeline: Pipeline, threshold: float, model_type: str, device: str) -> None:
    bundle = {
        "pipeline": pipeline,
        "threshold": float(threshold),
        "feature_columns": [],
        "feature_kind": "ember",
        "model_type": model_type,
        "score_mode": "predict_proba" if model_type == "supervised" and device.startswith("cuda") else (
            "decision_function" if model_type == "supervised" else "negative_decision_function"
        ),
        "device": device,
        "label_mapping": {"benign": 0, "malware": 1},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)


def resolve_device(requested: str) -> str:
    if requested == "cpu":
        return "cpu"
    has_xgboost = importlib.util.find_spec("xgboost") is not None
    has_driver = nvidia_driver_available()
    if requested == "cuda":
        if not has_driver:
            raise RuntimeError("CUDA requested but NVIDIA driver is not available; `nvidia-smi` failed")
        if not has_xgboost:
            raise RuntimeError("CUDA requested but xgboost is not installed in this virtualenv")
        return "cuda"
    if has_driver and has_xgboost:
        return "cuda"
    if not has_driver:
        print("[warn] NVIDIA driver is not available; using CPU training")
    if not has_xgboost:
        print("[warn] xgboost is not installed; using CPU training")
    return "cpu"


def nvidia_driver_available() -> bool:
    try:
        subprocess.run(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def _resolve_input_files(input_path: Path, max_files: Optional[int] = None) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(input_path)

    names = [
        "train_features_1.jsonl",
        "train_features_2.jsonl",
        "train_features_3.jsonl",
        "train_features_4.jsonl",
        "train_features_5.jsonl",
        "train_features_0.jsonl",
        "test_features.jsonl",
    ]
    preferred = [input_path / name for name in names if (input_path / name).exists()]
    if preferred:
        return preferred[:max_files] if max_files else preferred

    files = sorted(input_path.glob("*.jsonl")) + sorted(input_path.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no .jsonl or .csv files found in {input_path}")
    return files[:max_files] if max_files else files


def _iter_jsonl_samples(path: Path) -> Iterable[Tuple[Dict[str, float], int]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            label = _parse_label(row.get("label"))
            if label is None:
                continue
            features = flatten_ember_features(row)
            if features:
                yield features, label


def _iter_csv_samples(path: Path) -> Iterable[Tuple[Dict[str, float], int]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = _parse_label(row.get("label"))
            if label is None:
                continue
            features: Dict[str, float] = {}
            for key, value in row.items():
                if key in {"label", "sha256", "appeared"}:
                    continue
                number = _to_float(value)
                if number is not None:
                    features[key] = number
            if features:
                yield features, label


def flatten_ember_features(row: Dict[str, Any]) -> Dict[str, float]:
    features: Dict[str, float] = {}
    for key, value in row.items():
        if key in {"label", "sha256", "appeared", "avclass"}:
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


def _parse_label(value: Any) -> Optional[int]:
    try:
        label = int(value)
    except (TypeError, ValueError):
        return None
    if label in {0, 1}:
        return label
    return None


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if np.isfinite(value):
            return float(value)
        return None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        if np.isfinite(number):
            return number
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Train NGAV and anomaly models from a subset of EMBER data")
    parser.add_argument("--ember-path", required=True, help="EMBER .jsonl/.csv file or directory")
    parser.add_argument("--limit", type=int, default=50000, help="Maximum labeled samples to keep")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--contamination", type=float, default=0.02)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--gpu-id", type=int, default=0, help="CUDA GPU id for XGBoost, e.g. 0 for GTX1650")
    parser.add_argument(
        "--sample-strategy",
        choices=["balanced", "head", "reservoir"],
        default="balanced",
        help="balanced/head read a partial dataset quickly; reservoir scans selected files",
    )
    parser.add_argument("--max-files", type=int, default=1, help="Maximum EMBER JSONL/CSV files to read")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    X, y = load_subset(
        Path(args.ember_path),
        limit=args.limit,
        seed=args.seed,
        strategy=args.sample_strategy,
        max_files=args.max_files,
    )
    print(f"[info] loaded labeled EMBER subset: samples={len(X)} benign={(y == 0).sum()} malware={(y == 1).sum()}")

    ngav_pipeline, ngav_device = train_ember_ngav(X, y, device=args.device, gpu_id=args.gpu_id)
    save_bundle(output_dir / "ember_ngav.pkl", ngav_pipeline, threshold=0.5 if ngav_device.startswith("cuda") else 0.0, model_type="supervised", device=ngav_device)
    print(f"[info] saved {output_dir / 'ember_ngav.pkl'} device={ngav_device}")

    anomaly_pipeline, threshold = train_ember_anomaly(X, y, contamination=args.contamination)
    save_bundle(output_dir / "ember_anomaly.pkl", anomaly_pipeline, threshold=threshold, model_type="anomaly", device="cpu")
    print(f"[info] saved {output_dir / 'ember_anomaly.pkl'} threshold={threshold:.6f} device=cpu")


if __name__ == "__main__":
    main()
