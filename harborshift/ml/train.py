"""Train and evaluate a reproducible model on the supplied synthetic data."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from harborshift.data_loader import default_source, load_dataset
from .predict import CATEGORICAL, FEATURES, MODEL_PATH, MODEL_VERSION, NUMERIC, ROOT

SEED = 42


def metrics(expected, predicted):
    return {
        "mae_days": float(mean_absolute_error(expected, predicted)),
        "rmse_days": float(mean_squared_error(expected, predicted) ** 0.5),
    }


def train(source: Path, model_path: Path = MODEL_PATH) -> dict:
    dataset = load_dataset(source)
    dataset.require_valid()
    rows = [asdict(record) for record in dataset.records["historical_delays_synthetic"].values()]
    if len(rows) < 20:
        raise ValueError("Delay training requires at least 20 valid historical records")
    frame = pd.DataFrame(rows)
    target = frame.pop("actual_delay_days").astype(float)
    features = frame.loc[:, list(FEATURES)]
    x_train, x_other, y_train, y_other = train_test_split(
        features, target, test_size=0.30, random_state=SEED,
    )
    x_val, x_test, y_val, y_test = train_test_split(
        x_other, y_other, test_size=0.50, random_state=SEED,
    )
    regressors = {
        "mean_baseline": DummyRegressor(),
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(n_estimators=120, random_state=SEED, n_jobs=1),
        "gradient_boosting": GradientBoostingRegressor(random_state=SEED),
    }
    fitted = {}
    validation = {}
    for name, regressor in regressors.items():
        preprocessing = ColumnTransformer([
            ("categories", OneHotEncoder(handle_unknown="ignore", sparse_output=False), list(CATEGORICAL)),
            ("numbers", StandardScaler(), list(NUMERIC)),
        ])
        pipeline = Pipeline([("preprocessing", preprocessing), ("model", regressor)])
        pipeline.fit(x_train, y_train)
        fitted[name] = pipeline
        validation[name] = metrics(y_val, pipeline.predict(x_val).clip(min=0))
    winner = min(validation, key=lambda name: validation[name]["mae_days"])
    report = {
        "data_origin": "synthetic", "version": MODEL_VERSION, "random_seed": SEED,
        "scikit_learn_version": sklearn.__version__, "features": list(FEATURES),
        "split_counts": {"train": len(x_train), "validation": len(x_val), "test": len(x_test)},
        "validation": validation, "selected": winner,
        "held_out_test": metrics(y_test, fitted[winner].predict(x_test).clip(min=0)),
        "held_out_mean_baseline": metrics(y_test, fitted["mean_baseline"].predict(x_test)),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_model = model_path.with_suffix(".tmp")
    joblib.dump({
        "pipeline": fitted[winner], "features": FEATURES, "version": MODEL_VERSION,
    }, tmp_model, compress=3)
    report["model_sha256"] = sha256(tmp_model.read_bytes()).hexdigest()
    tmp_model.replace(model_path)
    model_path.with_name("delay_evaluation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    print(json.dumps(train(default_source(ROOT)), indent=2))
