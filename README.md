# Meme Radar — Solana Memecoin Alert Bot

**Personal, alert-only research tooling. Not an auto-trader.** Meme Radar watches Pump.fun launch/migration events, searches public X posts for Solana token contract addresses, checks the mint against DexScreener and RugCheck, and sends a scored watchlist alert to one Telegram chat.

It does **not** connect to a wallet, hold a private key, sign transactions, buy, sell, or promise profits. The $1 → $1,000 target is a 1,000× return objective; this project does not claim that outcome is achievable or likely.

## What it does

1. **Launch discovery:** listens to PumpPortal's Pump.fun/PumpSwap WebSocket for `subscribeNewToken` and `subscribeMigration` events.
2. **X discovery:** polls X recent search for public posts that mention Pump.fun/memecoins and extracts possible Solana contract addresses. Every extracted address is treated as untrusted until DEX data confirms it.
3. **Token verification:** checks the mint's Solana pools through DexScreener, selects the most liquid pool, and requires observable market data.
4. **Risk screen:** requests the RugCheck report summary. By default, alerts are blocked if RugCheck is unavailable, reports a danger/critical flag, or returns a normalized risk score above the configured limit.
5. **Signal filter:** scores liquidity, 5-minute volume and swap count, pair age, price movement, buy/sell balance, X mentions and risk evidence. The score is a transparent heuristic, **not** a probability of profit.
6. **Telegram:** sends one alert per mint to your configured private chat. It includes the mint, score, measured metrics, risk notes, X evidence and market links.
7. **Auditability:** stores seen mints and X post IDs in SQLite to reduce duplicate processing and alerts.

## Why it is alert-only

A signal bot can be wrong even when all APIs work. New memecoins can have manipulated volume, concentrated holders, removable liquidity, spoofed social activity, rapidly changing prices, failed sells and severe slippage. Public API snapshots also arrive late and may be incomplete. A passed screen is not proof that a token is safe.

No wallet secret or trading endpoint is included. Do not add a wallet private key to `.env`, GitHub Actions, this repository, or a hosted bot. A $1 account also makes friction proportionally severe; first validate alerts on a paper ledger with a larger hypothetical notional and recorded outcomes.

## Requirements

- Python 3.10+
- A PumpPortal API key (for the WebSocket connection)
- An X developer bearer token with recent-search access
- A Telegram bot token and your private Telegram chat ID
- Internet access from the machine running the bot

### API access and possible costs

- **PumpPortal:** the documented `subscribeNewToken` and `subscribeMigration` feeds are free. This project deliberately does not subscribe to metered per-token or per-account trade streams. PumpPortal says trading streams are metered and its May 1, 2026 fee schedule specifies 0.01 SOL per 10,000 messages; using those streams is unnecessary for this first version.
- **X:** the bot uses the official recent-search endpoint (`/2/tweets/search/recent`). X's recent-search window is limited to the most recent seven days. Your X developer access/credits and current plan determine whether requests work and whether they incur charges. The app caps searches per hour.
- **DexScreener:** uses the documented Solana token-pairs endpoint. DexScreener currently documents 300 requests/minute for token-pair lookups. The bot makes one lookup per candidate, with retries and a small worker pool.
- **RugCheck:** uses the public report-summary route where available. It is an independent on-chain risk signal, not an authority and not a guarantee. Its schema/availability can change; the URL is configurable.
- **Telegram:** uses Telegram's official HTTPS Bot API `sendMessage` method.

See [docs/RESEARCH.md](docs/RESEARCH.md) for source links and which statements are documented facts versus design judgments.

## Setup

### 1. Clone and install

```bash
git clone https://github.com/OperaAxe/meme-radar-solana.git
cd meme-radar-solana
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Create credentials

- **Telegram:** open `@BotFather`, create a bot with `/newbot`, and copy the token. Open your new bot and send `/start`. Retrieve your chat ID from the bot's `getUpdates` response (do not paste the bot token into public chat or commit it).
- **X:** create an app in the X Developer Console and copy its bearer token. Grant only the read/search access needed for recent public posts. If recent search returns 401/403, check the app's access level and account credits.
- **PumpPortal:** create an API key in PumpPortal. For this bot, only the new-token and migration data streams are used.

### 3. Configure the environment

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and fill these four values:

```dotenv
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_private_chat_id
X_BEARER_TOKEN=your_x_bearer_token
PUMPPORTAL_API_KEY=your_pumpportal_api_key
```

Keep `.env` local. It is excluded by `.gitignore`. Never put real tokens in source code, screenshots, GitHub issues or commits.

### 4. Run tests, then start

```bash
pytest -q
python bot.py
```

The bot will stop cleanly with `Ctrl+C`. SQLite state is stored at `data/meme_radar.sqlite3` by default.

## Initial filter defaults

These are deliberately conservative starting parameters, not proven profitable values:

| Filter | Default | Reason |
|---|---:|---|
| Minimum pool liquidity | $5,000 | Avoid the thinnest pools; still not enough to guarantee an exit |
| Minimum 5m volume | $1,500 | Require some recent market activity |
| Minimum 5m swaps | 8 | Reject near-dead pools |
| Pair age | 1–240 minutes | Avoid the very first seconds and stale launches |
| Maximum 5m price rise | 90% | Reject highly vertical recent moves |
| Minimum X evidence | 1 post; 2 authors preferred | Reduce pure on-chain/no-social false positives |
| RugCheck normalized score | 40 max | Block reported high-risk tokens; lower is treated as better by this rule |
| Minimum alert score | 65/100 | Require multiple independent conditions |
| RugCheck availability | Required | Fail closed when the risk lookup is unavailable |

Change thresholds in `.env` only after collecting and reviewing results. Do not tune on the same sample used to judge performance.

## How to read an alert

- **Signal score:** points awarded by the explicit rules in `src/memeradar/scoring.py`. It is not machine-learning output, a win probability, or a recommendation to buy.
- **Liquidity:** DEX-reported liquidity at snapshot time. It does not guarantee that you can sell your entire position at the displayed price.
- **5m volume/swaps:** activity reported by DexScreener; volume can be manipulated and swaps are not unique traders.
- **X posts/authors:** matching recent-search results, not proof of organic community support. Search results can miss posts and may include spam.
- **RugCheck:** independent report snapshot. A missing report blocks alerts by default; a green/low score still does not make a token safe.

## Backtesting and the 10,000-path simulation

### A. Synthetic Monte Carlo stress test

Run:

```bash
python -m memeradar.simulation --paths 10000 --trades 100 --seed 42 --output results/monte_carlo.json
```

The command simulates **10,000 paths per scenario** (optimistic, base, adverse and parameter-uncertainty), each with up to 100 theoretical trades. It varies win/loss/rug assumptions and deducts a round-trip friction allowance. It reports target-hit frequency, severe-loss frequency, final-balance percentiles and drawdown.

**Critical limitation:** these are synthetic paths, not observed memecoin history. The assumed probabilities and returns are illustrative stress inputs, not estimates of the true strategy edge. A 0% or non-zero target-hit result in this simulation is not a promise about future trading.

### Recorded run (seed 42, 10,000 paths per scenario)

The simulation shipped with this repository produced the following outputs for $1 starting capital, a $1,000 target, up to 100 trades per path and 10% of capital exposed per trade:

| Synthetic scenario | Paths reaching $1,000 | Median final balance | Paths losing at least 80% |
|---|---:|---:|---:|
| Optimistic | 6.78% | $225.57 | 0.00% |
| Base | 0.00% | $0.38 | 16.07% |
| Adverse | 0.00% | $0.05 | 96.30% |
| Parameter uncertainty | 2.12% | $1.08 | 23.79% |

Full machine-readable output: [`results/monte_carlo.json`](results/monte_carlo.json). The optimistic/base/adverse cases are fixed hypothetical assumptions; the uncertainty case randomly samples broad assumptions. These figures must not be interpreted as a live strategy's probability of success.

### B. Actual historical backtest

A genuine backtest requires a timestamped dataset of signals and later outcomes. This repository does not invent one. Record every eligible and rejected candidate at signal time, then join the price 15 minutes later. The CSV must contain:

```text
mint,signal_score,liquidity_usd,volume_5m_usd,txns_5m,rugcheck_score,entry_price_usd,exit_price_15m_usd
```

Run:

```bash
python -m memeradar.backtest path/to/your_real_observations.csv --output results/backtest.json
```

The backtest subtracts a configurable 4% round-trip friction assumption by default. Change it only with evidence from realistic execution quotes. It uses a fixed 15-minute exit, so it does not model intrabar stops, latency, priority fees, failed sells, market impact, or MEV. For research quality, capture every signal—including ones that later rug or disappear—and avoid survivorship bias.

## Failure controls included

- API timeouts and transient-error handling
- WebSocket reconnect with exponential backoff
- DexScreener missing-pair retries and periodic rechecks
- Per-hour X query budget and 429 handling
- X/DexScreener/RugCheck data treated as untrusted and nullable
- RugCheck fail-closed mode by default
- Liquidity, volume, transaction-count, age and vertical-price-move gates
- One alert per mint, persisted in SQLite
- No wallet secret, transaction signer or buy/sell route

## Known limitations / next validation steps

1. X query matching is noisy. Symbols collide and some tokens have no public contract-address post. The initial implementation only treats explicit mint-address matches as X-discovered tokens.
2. RugCheck's response can be stale, missing or temporarily inaccessible. The bot blocks alerts on missing data by default; do not turn off this control just to increase alert volume.
3. DexScreener liquidity and volume are snapshots. They are not executable quotes and do not measure unique wallet count or holder concentration by themselves.
4. The score is a rule-based filter. No parameter has been proven profitable. Collect at least several weeks of paper-trading logs and compare against a baseline before changing it.
5. The $1 → $1,000 plan is not something this tool can make happen. Validate with simulated positions first; a $1 amount can be overwhelmed by fees, spread, slippage and minimum execution constraints.

## License

MIT. For personal research and educational use. External API terms, rate limits, and costs still apply.