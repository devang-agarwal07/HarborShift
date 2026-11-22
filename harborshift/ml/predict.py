"""Validate inputs and use a saved synthetic model or the offline rule."""

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from pathlib import Path
import pickle

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "artifacts" / "delay_model.joblib"
CATEGORICAL = ("port_id", "event_type")
NUMERIC = (
    "expected_duration_days", "severity_1_to_5", "congestion_0_to_5",
    "planned_transit_days", "schedule_buffer_days",
)
FEATURES = (*CATEGORICAL, *NUMERIC)
MODEL_VERSION = "synthetic-delay-v1"


@dataclass(frozen=True)
class DelayPrediction:
    days: float
    version: str
    source: str


@lru_cache(maxsize=4)
def _load(path: Path, modified_ns: int):
    import joblib
    return joblib.load(path)


def predict_delay(features: dict, model_path: Path = MODEL_PATH) -> DelayPrediction:
    missing = set(FEATURES) - features.keys()
    if missing:
        raise ValueError("Missing prediction fields: " + ", ".join(sorted(missing)))
    for field in CATEGORICAL:
        if not isinstance(features[field], str) or not features[field].strip():
            raise ValueError(f"{field} must be a nonempty string")
    for field in NUMERIC:
        value = features[field]
        cap = 5 if field in {"severity_1_to_5", "congestion_0_to_5"} else None
        if type(value) is not int or value < 0 or (cap is not None and value > cap):
            raise ValueError(f"{field} must be a nonnegative integer within its supported range")

    try:
        stat = model_path.stat()
        saved = _load(model_path, stat.st_mtime_ns)
    except (OSError, ImportError, ValueError, EOFError, pickle.UnpicklingError):
        saved = None
    if saved and tuple(saved["features"]) == FEATURES:
        import pandas as pd
        prediction = float(saved["pipeline"].predict(pd.DataFrame([features], columns=list(FEATURES)))[0])
        if isfinite(prediction):
            return DelayPrediction(max(0.0, prediction), saved["version"], "synthetic_model")
    severity = features["severity_1_to_5"]
    days = min(features["expected_duration_days"], (severity + 1) // 2)
    return DelayPrediction(float(days), "rule-v1", "rule_fallback")
