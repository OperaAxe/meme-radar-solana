# Research notes and source register

**As-of date:** 12 November 2026. These links document API behaviour and relevant risk considerations. API providers can change access, pricing, rate limits and response fields; re-check each source before deployment.

## Documented facts

| Area | What the source documents | Source |
|---|---|---|
| Pump.fun event feed | PumpPortal exposes a WebSocket data feed for Pump.fun/PumpSwap. `subscribeNewToken` and `subscribeMigration` are listed as free; token/account trade subscriptions are metered. It asks clients to use one WebSocket connection rather than opening one per token. | https://pumpportal.fun/data-api/real-time/ |
| PumpPortal fees | Its fee page states that, effective 1 May 2026, trading data requires an API key and token/account trade messages incur 0.01 SOL per 10,000 events. | https://pumpportal.fun/fees/ |
| DexScreener | The API documents `/token-pairs/v1/{chainId}/{tokenAddress}` and returns pool fields including token addresses, price, transactions, volume, price change, liquidity, FDV/market cap and pair-created time. The documented token/pair lookup limit is 300 requests/minute. | https://docs.dexscreener.com/api/reference |
| X recent search | X has a recent-search endpoint for public posts and separate full-archive search. Recent search covers the last seven days; the X developer docs describe query operators and the search-posts endpoints. | https://docs.x.com/x-api/posts/search/introduction |
| X pagination | X search responses use pagination metadata such as `next_token`, and search pages can return up to 100 posts. This project uses a single page per poll and caps request volume. | https://docs.x.com/xdks/python/pagination |
| Telegram delivery | Telegram's Bot API is HTTPS-based and its `sendMessage` method sends text to a chat ID. A bot cannot initiate a private conversation until the user has started it. | https://core.telegram.org/bots/api |
| Solana token authorities | Solana's token documentation describes mint and freeze authorities and how revoking an authority removes that authority role. A remaining freeze authority can freeze token accounts. | https://solana.com/docs/tokens/basics/set-authority and https://solana.com/docs/tokens/basics/freeze-account |
| Token verification is not safety certification | Solana documents that verification helps identify the canonical token/name/symbol/mint, but is not an endorsement or guarantee of value, safety or legitimacy. The docs describe RugCheck as an independent risk provider that evaluates authorities, holder distribution and liquidity. | https://solana.com/docs/tokens/how-to-verify-a-token |
| RugCheck summary route | A third-party API reference mirrors the RugCheck summary endpoint and example response, including `score_normalised`, liquidity-risk items and `risks`. The implementation treats this dependency as optional/volatile and blocks by default if no report is available. | https://fluxrpc.com/docs/rugcheck/getTokenReportSummary |

## Engineering judgments (not facts guaranteed by the sources)

1. **New-token + migration event feeds are the lowest-cost launch-discovery starting point.** This project uses PumpPortal for those feeds only, then checks DexScreener. It does not need the metered per-token trade stream in the first iteration.
2. **A mint address should be treated as untrusted until resolved to a Solana pool.** X posts can contain typos, spoofed addresses, copy-paste scams or irrelevant long strings; DexScreener is used as a market-data cross-check, not a safety endorsement.
3. **Liquidity, volume and transaction-count gates reduce obvious thin-market candidates, but do not prove executable liquidity.** Pools may be manipulated; the alert should never be treated as an executable quote.
4. **A very vertical short-term price move is a risk flag rather than an automatic bullish feature.** The bot blocks extreme 5-minute increases and sharp negative moves in the initial configuration.
5. **Failing closed on missing RugCheck data is safer than silently assuming the token passed.** This may reduce alert volume. If the endpoint becomes unavailable, investigate and update the integration rather than weakening the filter blindly.
6. **Signal thresholds are provisional.** They are designed for filtering and transparent review, not to claim an edge. The project does not report a historical win rate until a sufficiently complete, timestamped real dataset has been recorded and backtested.
7. **No code can guarantee a 1,000× outcome.** The intended validation sequence is alerts → paper log → historical test with out-of-sample period → manual small-size evaluation. A $1 notional is particularly sensitive to friction and may not meet venue execution constraints.

## References to keep watching

- X API search docs: https://docs.x.com/x-api/posts/search/introduction
- X API rate-limit docs: https://docs.x.com/x-api/fundamentals/rate-limits
- PumpPortal data feed: https://pumpportal.fun/data-api/real-time/
- PumpPortal fee notes: https://pumpportal.fun/fees/
- DexScreener API reference: https://docs.dexscreener.com/api/reference
- Telegram Bot API: https://core.telegram.org/bots/api
- Solana token authority docs: https://solana.com/docs/tokens/basics/set-authority
- Solana token verification caveats: https://solana.com/docs/tokens/how-to-verify-a-token
- RugCheck Swagger: https://api.rugcheck.xyz/swagger/index.html
