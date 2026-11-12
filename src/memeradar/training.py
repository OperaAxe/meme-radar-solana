"""Leakage-aware model fitting for fixed-horizon Meme Radar outcomes.

The model predicts whether a token's observed 15-minute mark-to-market return
would be positive after a configurable round-trip friction assumption. It is a
paper-research ranking model, not a profitability guarantee or execution model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

FEATURES = (
    "signal_score", "qualified", "liquidity_usd", "volume_5m_usd", "buys_5m",
    "sells_5m", "txns_5m", "price_change_5m_pct", "pair_age_minutes",
    "rugcheck_score", "rugcheck_available", "rugcheck_danger_flag", "x_posts",
    "x_authors", "x_engagement",
)
REQUIRED = {
    "signal_ts", "mint", "entry_price_usd", "exit_price_15m_usd",
    "outcome_ts", "outcome_status", *FEATURES,
}


def _number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_labeled_rows(path: str | Path, friction: float = 0.04,
                      min_horizon_seconds: float = 900,
                      max_horizon_seconds: float = 1200) -> tuple[list[list[float | None]], list[int], list[dict[str, Any]]]:
    """Read only complete fixed-horizon outcomes; no future fields enter X."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = sorted(REQUIRED - set(reader.fieldnames or []))
        if missing:
            raise ValueError("CSV missing required columns: " + ", ".join(missing))
        records = list(reader)

    eligible: list[tuple[float, list[float | None], int, dict[str, Any]]] = []
    for row in records:
        signal_ts = _number(row.get("signal_ts"))
        outcome_ts = _number(row.get("outcome_ts"))
        entry = _number(row.get("entry_price_usd"))
        exit_price = _number(row.get("exit_price_15m_usd"))
        status = (row.get("outcome_status") or "").strip().lower()
        if signal_ts is None or outcome_ts is None or entry is None or entry <= 0:
            continue
        horizon = outcome_ts - signal_ts
        if horizon < min_horizon_seconds or horizon > max_horizon_seconds:
            continue
        if status == "quoted":
            if exit_price is None or exit_price <= 0:
                continue
            net_return = exit_price / entry - 1.0 - friction
        elif status == "no_pair":
            # No DEX pool to quote at the fixed horizon is counted as a failed exit.
            net_return = -1.0
        else:
            continue
        features = [_number(row.get(name)) for name in FEATURES]
        label = int(net_return > 0)
        metadata = {
            "mint": row.get("mint", ""),
            "signal_ts": signal_ts,
            "net_15m_return": net_return,
            "outcome_status": status,
            "signal_score": _number(row.get("signal_score")),
        }
        eligible.append((signal_ts, features, label, metadata))

    eligible.sort(key=lambda item: item[0])
    return ([item[1] for item in eligible], [item[2] for item in eligible],
            [item[3] for item in eligible])


def fit_and_evaluate(csv_path: str | Path, artifact_path: str | Path,
                     friction: float = 0.04, test_fraction: float = 0.20,
                     min_rows: int = 200, min_per_class: int = 20) -> dict[str, Any]:
    """Fit on the oldest rows; reserve the newest contiguous period for testing."""
    try:
        import joblib
        import numpy as np
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import (accuracy_score, average_precision_score,
                                     brier_score_loss, confusion_matrix, f1_score,
                                     precision_score, recall_score, roc_auc_score)
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError("Install the ML extra with: pip install -e '.[ml]'") from exc

    if not 0.10 <= test_fraction <= 0.40:
        raise ValueError("test_fraction must be between 0.10 and 0.40")
    X, y, metadata = read_labeled_rows(csv_path, friction=friction)
    if len(X) < min_rows:
        raise ValueError(f"Need at least {min_rows} eligible real outcomes; found {len(X)}")

    split = int(len(X) * (1.0 - test_fraction))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    train_pos, test_pos = sum(y_train), sum(y_test)
    if min(train_pos, len(y_train)-train_pos, test_pos, len(y_test)-test_pos) < min_per_class:
        raise ValueError(
            "Chronological train/test split needs at least "
            f"{min_per_class} examples of each class in both periods; "
            f"train positives={train_pos}/{len(y_train)}, "
            f"test positives={test_pos}/{len(y_test)}"
        )

    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scale", StandardScaler()),
        ("classifier", LogisticRegression(C=0.5, class_weight="balanced", max_iter=3000, random_state=42)),
    ])
    pipeline.fit(np.asarray(X_train, dtype=float), np.asarray(y_train, dtype=int))
    probabilities = pipeline.predict_proba(np.asarray(X_test, dtype=float))[:, 1]
    predictions = (probabilities >= 0.5).astype(int)

    auc = float(roc_auc_score(y_test, probabilities))
    ap = float(average_precision_score(y_test, probabilities))
    prevalence = float(sum(y_test) / len(y_test))
    test_scores = [m["signal_score"] for m in metadata[split:]]
    heuristic_auc = None
    if all(v is not None for v in test_scores):
        heuristic_auc = float(roc_auc_score(y_test, test_scores))
    metrics = {
        "rows_eligible": len(X),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "train_positive_rate": train_pos / len(y_train),
        "test_positive_rate": prevalence,
        "roc_auc": auc,
        "average_precision": ap,
        "positive_class_baseline_average_precision": prevalence,
        "brier_score": float(brier_score_loss(y_test, probabilities)),
        "majority_baseline_accuracy": max(prevalence, 1.0-prevalence),
        "accuracy_at_0_50": float(accuracy_score(y_test, predictions)),
        "precision_at_0_50": float(precision_score(y_test, predictions, zero_division=0)),
        "recall_at_0_50": float(recall_score(y_test, predictions, zero_division=0)),
        "f1_at_0_50": float(f1_score(y_test, predictions, zero_division=0)),
        "confusion_matrix_labels_0_1": confusion_matrix(y_test, predictions, labels=[0, 1]).tolist(),
        "heuristic_signal_score_roc_auc": heuristic_auc,
        "test_start_signal_ts": metadata[split]["signal_ts"],
        "test_end_signal_ts": metadata[-1]["signal_ts"],
        "friction_assumption": friction,
        "decision_threshold": 0.50,
        "model": "median-imputed standardized logistic regression, balanced classes",
        "warning": "Paper-data ranking only. Mark prices are not fills; API snapshot time, spread, slippage, MEV and failed execution are not fully modelled.",
    }

    artifact = {
        "pipeline": pipeline,
        "features": list(FEATURES),
        "metrics": metrics,
        "friction_assumption": friction,
        "train_end_signal_ts": metadata[split-1]["signal_ts"],
        "test_start_signal_ts": metadata[split]["signal_ts"],
    }
    output = Path(artifact_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit/evaluate the Meme Radar 15m paper-return model")
    parser.add_argument("csv_path", help="CSV exported by Meme Radar after collecting 15m outcomes")
    parser.add_argument("--artifact", default="models/meme_radar_15m.joblib")
    parser.add_argument("--friction", type=float, default=0.04, help="Round-trip cost fraction")
    args = parser.parse_args()
    metrics = fit_and_evaluate(args.csv_path, args.artifact, friction=args.friction)
    print(json.dumps(metrics, indent=2))
    print(f"\nSaved model artifact to {args.artifact}")


if __name__ == "__main__":
    main()