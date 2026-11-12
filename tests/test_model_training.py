import csv
from pathlib import Path

import pytest

from memeradar.training import FEATURES, fit_and_evaluate, read_labeled_rows


def make_rows(path: Path, n: int = 100) -> None:
    columns = [
        "signal_ts", "mint", "entry_price_usd", "exit_price_15m_usd", "outcome_ts", "outcome_status",
        *FEATURES,
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for i in range(n):
            positive = int((i % 10) >= 5)
            liquidity = 20_000 if positive else 1_000
            row = {
                "signal_ts": 1_700_000_000 + i * 1_300,
                "mint": f"mint-{i}",
                "entry_price_usd": 1.0,
                "exit_price_15m_usd": 1.20 if positive else 0.90,
                "outcome_ts": 1_700_000_000 + i * 1_300 + 930,
                "outcome_status": "quoted",
                "signal_score": 80 if positive else 35,
                "qualified": positive,
                "liquidity_usd": liquidity,
                "volume_5m_usd": 8_000 if positive else 400,
                "buys_5m": 30 if positive else 4,
                "sells_5m": 10 if positive else 6,
                "txns_5m": 40 if positive else 10,
                "price_change_5m_pct": 8 if positive else -12,
                "pair_age_minutes": 12 + (i % 20),
                "rugcheck_score": 10 if positive else 55,
                "rugcheck_available": 1,
                "rugcheck_danger_flag": 0,
                "x_posts": 4 if positive else 0,
                "x_authors": 3 if positive else 0,
                "x_engagement": 25 if positive else 0,
            }
            writer.writerow(row)


def test_time_ordered_rows_and_net_return_label(tmp_path):
    path = tmp_path / "training.csv"
    make_rows(path, 40)
    X, y, metadata = read_labeled_rows(path, friction=0.04)
    assert len(X) == 40
    assert y.count(1) == 20
    assert metadata[0]["signal_ts"] < metadata[-1]["signal_ts"]
    assert "exit_price_15m_usd" not in FEATURES


def test_fit_uses_newest_period_as_holdout(tmp_path):
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")
    path = tmp_path / "training.csv"
    artifact = tmp_path / "model.joblib"
    make_rows(path, 100)
    metrics = fit_and_evaluate(path, artifact, min_rows=80, min_per_class=5)
    assert artifact.exists()
    assert metrics["train_rows"] == 80
    assert metrics["test_rows"] == 20
    assert metrics["roc_auc"] >= 0.90
    assert metrics["heuristic_signal_score_roc_auc"] is not None


def test_training_refuses_too_little_data(tmp_path):
    path = tmp_path / "small.csv"
    make_rows(path, 20)
    with pytest.raises(ValueError, match="Need at least"):
        fit_and_evaluate(path, tmp_path / "m.joblib", min_rows=40, min_per_class=2)