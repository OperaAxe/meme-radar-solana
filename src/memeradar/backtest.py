"""Fixed-horizon historical backtest for a manually exported snapshot dataset.

CSV rows must contain features observed at signal time plus a later 15-minute
exit price. A row is never fabricated by this module.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = {
    "mint", "signal_score", "liquidity_usd", "volume_5m_usd", "txns_5m",
    "rugcheck_score", "entry_price_usd", "exit_price_15m_usd",
}


def _f(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return default


def backtest_rows(rows: list[dict[str, str]], min_score: float = 65,
                  min_liquidity: float = 5_000, min_volume_5m: float = 1_500,
                  min_txns_5m: int = 8, max_rugcheck_score: float = 40,
                  round_trip_cost: float = 0.04) -> dict[str, Any]:
    trades: list[float] = []
    blocked = 0
    for row in rows:
        entry = _f(row, "entry_price_usd")
        exit_price = _f(row, "exit_price_15m_usd")
        qualifies = (
            _f(row, "signal_score") >= min_score
            and _f(row, "liquidity_usd") >= min_liquidity
            and _f(row, "volume_5m_usd") >= min_volume_5m
            and _f(row, "txns_5m") >= min_txns_5m
            and _f(row, "rugcheck_score", 999) <= max_rugcheck_score
            and entry > 0 and exit_price > 0
        )
        if not qualifies:
            blocked += 1
            continue
        trades.append(exit_price / entry - 1.0 - round_trip_cost)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for ret in trades:
        equity *= max(0.0, 1.0 + ret)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return {
        "method": "15-minute fixed-horizon historical snapshot backtest",
        "total_rows": len(rows),
        "trades_taken": len(trades),
        "rows_blocked": blocked,
        "round_trip_cost_assumption": round_trip_cost,
        "win_rate": (sum(r > 0 for r in trades) / len(trades)) if trades else None,
        "mean_net_return_per_trade": statistics.fmean(trades) if trades else None,
        "median_net_return_per_trade": statistics.median(trades) if trades else None,
        "compounded_return_multiple": equity,
        "max_drawdown": max_drawdown,
        "trade_returns": trades,
        "limitations": [
            "No intrabar path or fill simulation; exits assume the recorded 15-minute price.",
            "Slippage and fees are a single configurable deduction, not venue-specific fills.",
            "The CSV must be collected without survivorship bias and with features frozen at signal time.",
        ],
    }


def backtest_csv(path: str | Path, **kwargs: Any) -> dict[str, Any]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError("CSV missing required columns: " + ", ".join(missing))
        rows = list(reader)
    return backtest_rows(rows, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Meme Radar against real recorded snapshots")
    parser.add_argument("csv_path", help="CSV file of time-stamped signal snapshots and 15m outcomes")
    parser.add_argument("--output", default="results/backtest.json")
    args = parser.parse_args()
    result = backtest_csv(args.csv_path)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "trade_returns"}, indent=2))


if __name__ == "__main__":
    main()
