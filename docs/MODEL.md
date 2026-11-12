# Model protocol and current status

## Status

Meme Radar's live alert score remains a deterministic heuristic. The repository includes a supervised training and evaluation path, but **there is no trained predictive artifact checked in** because no real Meme Radar signal/outcome dataset exists yet. Do not describe the model as profitable or deploy its predictions until it has passed a chronological holdout test on live-collected observations.

## Target definition

For each unique mint, freeze the first available signal-time feature snapshot and entry price. At 15 minutes or later, record a DexScreener price from the matching Solana base-token pool. The target is: `exit_price / entry_price - 1 - round_trip_friction > 0`. A `no_pair` status at the horizon is treated as a failed quote / negative outcome. It is not asserted to be a literal on-chain 100% loss.

This is a mark-to-market label, not a fill simulation. It does not include transaction inclusion, priority fees, route quotes, exact spread, slippage, market impact, MEV or failed sells. The 4% round-trip cost is only a starting assumption and must be replaced with observed quotes/fill data before interpreting economics.

## Leakage controls

- Store only the first feature snapshot per mint.
- Include rejected and accepted candidates; do not train only on alerts.
- Never include exit price, outcome timestamp, outcome status or net return among model features.
- Drop outcomes captured before 15 minutes or later than 20 minutes; delayed snapshots are not silently treated as the intended horizon.
- Sort by signal time, train on the oldest contiguous 80%, test on the newest 20%.
- Refuse training unless each class has enough examples in both periods.
- Compare model ROC AUC with the existing hand-built `signal_score` baseline.

## Features

The trainer uses the signal-time score/qualification flag, liquidity, 5-minute volume, buys, sells, swaps, price change, pair age, RugCheck score/availability/danger flag, and X post/author/engagement counts. No token name, ticker or mint is used as a predictive feature.

## How to run

```bash
pip install -e ".[ml]"
python scripts/export_training_data.py
python scripts/train_model.py data/model_training.csv --artifact models/meme_radar_15m.joblib
```

The training script writes an artifact and reports holdout metrics. It does not alter the live scoring rules. Any future deployment must add a second untouched temporal test, paper-trading calibration, drift monitoring, and a kill switch.

## Public research data considered

Mongardini and Mei's public release lists 34,988 curated meme coins across four chains, including 10,468 Solana tokens. Its high-performing cohort contains 707 tokens selected for >100% three-month performance; the associated OHLCV files are for that high-performing cohort. That is not a representative sample of all launch candidates at signal time. It was therefore not used to train this launch-return model.

Source: [Zenodo dataset and code (DOI 10.5281/zenodo.17830944)](https://doi.org/10.5281/zenodo.17830944); [paper](https://arxiv.org/abs/2507.01963).