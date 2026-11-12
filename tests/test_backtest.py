import pytest

from memeradar.backtest import backtest_rows, REQUIRED_COLUMNS


def test_backtest_calculates_net_returns_after_friction():
    rows = [
        {"mint": "A", "signal_score": "80", "liquidity_usd": "10000", "volume_5m_usd": "5000",
         "txns_5m": "20", "rugcheck_score": "10", "entry_price_usd": "1", "exit_price_15m_usd": "1.2"},
        {"mint": "B", "signal_score": "40", "liquidity_usd": "10000", "volume_5m_usd": "5000",
         "txns_5m": "20", "rugcheck_score": "10", "entry_price_usd": "1", "exit_price_15m_usd": "2"},
    ]
    result = backtest_rows(rows, round_trip_cost=0.04)
    assert result["trades_taken"] == 1
    assert result["rows_blocked"] == 1
    assert result["trade_returns"] == pytest.approx([0.16])


def test_required_columns_are_defined():
    assert "entry_price_usd" in REQUIRED_COLUMNS
    assert "exit_price_15m_usd" in REQUIRED_COLUMNS
