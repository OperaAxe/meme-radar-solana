"""Monte Carlo stress testing of alert-driven trade hypotheses.

These are explicitly synthetic assumptions, not historical memecoin returns or a
prediction. The simulator models capital exposed per trade, trading friction,
losing trades and total rugs. It never submits orders.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Scenario:
    win_probability: float
    rug_probability: float
    average_win_return: float
    average_loss: float
    round_trip_friction: float
    position_fraction: float = 0.10


SCENARIOS: dict[str, Scenario] = {
    "optimistic": Scenario(0.50, 0.05, 1.60, 0.25, 0.03, 0.10),
    "base": Scenario(0.32, 0.12, 0.90, 0.35, 0.05, 0.10),
    "adverse": Scenario(0.25, 0.20, 1.00, 0.45, 0.08, 0.10),
}


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    weight = index - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def _one_path(rng: random.Random, scenario: Scenario, trades: int,
              start: float, target: float) -> tuple[float, float, bool]:
    capital = start
    peak = start
    max_drawdown = 0.0
    hit_target = False
    p_loss = max(0.0, 1.0 - scenario.win_probability - scenario.rug_probability)
    if scenario.win_probability + scenario.rug_probability > 1:
        raise ValueError("win_probability + rug_probability must be <= 1")

    for _ in range(trades):
        if capital <= start * 0.01:
            break
        roll = rng.random()
        if roll < scenario.rug_probability:
            position_return = -1.0  # a rug wipes the allocated position
        elif roll < scenario.rug_probability + scenario.win_probability:
            position_return = max(-1.0, rng.uniform(0.5, 1.5) * scenario.average_win_return
                                  - scenario.round_trip_friction)
        else:
            position_return = -min(1.0, scenario.average_loss * rng.uniform(0.5, 1.5)
                                   + scenario.round_trip_friction)
        capital *= max(0.0, 1.0 + scenario.position_fraction * position_return)
        peak = max(peak, capital)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - capital) / peak)
        if capital >= target:
            hit_target = True
            break
    return capital, max_drawdown, hit_target


def run_monte_carlo(paths: int = 10_000, trades_per_path: int = 100,
                    start: float = 1.0, target: float = 1_000.0,
                    seed: int = 42) -> dict[str, Any]:
    if paths < 1 or trades_per_path < 1 or start <= 0 or target <= start:
        raise ValueError("paths/trades must be positive and target must exceed start")

    rng = random.Random(seed)
    output: dict[str, Any] = {
        "method": "synthetic Monte Carlo; not historical backtesting or a return forecast",
        "seed": seed,
        "paths_per_scenario": paths,
        "trades_per_path": trades_per_path,
        "starting_capital_usd": start,
        "target_capital_usd": target,
        "target_multiple": target / start,
        "assumptions": {},
        "results": {},
    }

    scenarios: dict[str, list[Scenario]] = {
        name: [scenario] * paths for name, scenario in SCENARIOS.items()
    }
    # Each uncertainty path draws its own edge and friction assumptions. This is
    # deliberately broad: we do not know the true win/rug/slippage distributions.
    scenarios["parameter_uncertainty"] = [
        Scenario(
            win_probability=(w := rng.uniform(0.20, 0.48)),
            rug_probability=min(rng.uniform(0.05, 0.25), 0.95 - w),
            average_win_return=rng.uniform(0.30, 2.50),
            average_loss=rng.uniform(0.15, 0.55),
            round_trip_friction=rng.uniform(0.02, 0.12),
            position_fraction=rng.uniform(0.05, 0.15),
        )
        for _ in range(paths)
    ]

    for name, scenario_list in scenarios.items():
        finals: list[float] = []
        drawdowns: list[float] = []
        hit_count = 0
        for scenario in scenario_list:
            final, drawdown, hit = _one_path(rng, scenario, trades_per_path, start, target)
            finals.append(final)
            drawdowns.append(drawdown)
            hit_count += int(hit)
        output["assumptions"][name] = asdict(scenario_list[0]) if name != "parameter_uncertainty" else {
            "win_probability_range": [0.20, 0.48],
            "rug_probability_range": [0.05, 0.25],
            "average_win_return_range": [0.30, 2.50],
            "average_loss_range": [0.15, 0.55],
            "round_trip_friction_range": [0.02, 0.12],
            "position_fraction_range": [0.05, 0.15],
        }
        output["results"][name] = {
            "probability_reach_target": hit_count / paths,
            "probability_lose_80pct_or_more": sum(v <= start * 0.20 for v in finals) / paths,
            "probability_end_below_50pct": sum(v < start * 0.50 for v in finals) / paths,
            "median_final_usd": statistics.median(finals),
            "p05_final_usd": _percentile(finals, 0.05),
            "p95_final_usd": _percentile(finals, 0.95),
            "mean_final_usd": statistics.fmean(finals),
            "median_max_drawdown": statistics.median(drawdowns),
            "worst_final_usd": min(finals),
            "best_final_usd": max(finals),
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic memecoin trading stress tests")
    parser.add_argument("--paths", type=int, default=10_000)
    parser.add_argument("--trades", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="results/monte_carlo.json")
    args = parser.parse_args()
    result = run_monte_carlo(args.paths, args.trades, seed=args.seed)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved {args.paths:,} paths per scenario to {path}")
    for name, stats in result["results"].items():
        print(f"{name:22} target={stats['probability_reach_target']:.2%} "
              f"median=${stats['median_final_usd']:.4f} "
              f"80%-loss={stats['probability_lose_80pct_or_more']:.2%} "
              f"median-DD={stats['median_max_drawdown']:.1%}")


if __name__ == "__main__":
    main()
