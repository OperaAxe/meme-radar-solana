from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .config import Config
from .models import Candidate
from .providers import (DexScreenerClient, PumpPortalFeed, RugCheckClient,
                        TelegramAlerter, XSearchClient, candidate_from_tweet)
from .scoring import evaluate_signal
from .storage import Store

log = logging.getLogger(__name__)


def money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def build_alert(candidate: Candidate, result: Any) -> str:
    pair = result.pair
    base = pair.get("baseToken") or {}
    liquidity = (pair.get("liquidity") or {}).get("usd")
    volume = (pair.get("volume") or {}).get("m5")
    tx = (pair.get("txns") or {}).get("m5") or {}
    buys, sells = tx.get("buys", 0), tx.get("sells", 0)
    age_mins = None
    try:
        age_mins = max(0, (time.time() * 1000 - float(pair.get("pairCreatedAt"))) / 60000)
    except (TypeError, ValueError):
        pass
    risk_text = (f"RugCheck normalized: {result.rugcheck.normalized_score:.0f}/100"
                 if result.rugcheck.available and result.rugcheck.normalized_score is not None
                 else "RugCheck: UNKNOWN")
    risk_names = [str(r.get("name")) for r in result.rugcheck.risks[:4] if isinstance(r, dict) and r.get("name")]
    reasons = "\n".join(f"• {r}" for r in result.reasons)
    social_links = "\n".join(result.social.post_urls[:3]) or "No post links returned"
    dex_url = pair.get("url") or f"https://dexscreener.com/solana/{candidate.mint}"
    age_text = f"{age_mins:.1f}m" if age_mins is not None else "unavailable"
    return (
        "MEME RADAR — WATCHLIST ALERT\n\n"
        f"{base.get('name') or candidate.name} (${base.get('symbol') or candidate.symbol})\n"
        f"Mint: {candidate.mint}\n"
        f"Signal score: {result.score}/100 (heuristic, not a probability)\n"
        f"Liquidity: {money(liquidity)} | 5m volume: {money(volume)}\n"
        f"5m swaps: {buys} buys / {sells} sells | Pair age: {age_text}\n"
        f"X: {result.social.posts} posts / {result.social.authors} authors\n"
        f"{risk_text}"
        + (f" | Flags: {', '.join(risk_names)}" if risk_names else "")
        + "\n\nPositive evidence:\n" + (reasons or "No positive reasons recorded")
        + "\n\nDEX Screener: " + dex_url
        + "\nPump.fun: " + f"https://pump.fun/coin/{candidate.mint}"
        + "\nX evidence:\n" + social_links
        + "\n\nAlert only. No trade is executed. Data can be delayed or incomplete."
        " A passed screen is not a safety guarantee or a buy recommendation."
    )


class MemeRadar:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg.database_path)
        self.queue: asyncio.Queue[Candidate] = asyncio.Queue(maxsize=5000)
        self.session: aiohttp.ClientSession | None = None

    async def add_candidate(self, candidate: Candidate) -> None:
        created = self.store.add_candidate(candidate.mint, candidate.name, candidate.symbol,
                                           candidate.source, candidate.source_url, candidate.raw)
        if created or (candidate.source == "pumpportal_migration" and not self.store.was_alerted(candidate.mint)):
            log.info("Candidate found: %s ($%s) via %s", candidate.name, candidate.symbol, candidate.source)
            await self.queue.put(candidate)

    async def _pumpportal_loop(self) -> None:
        feed = PumpPortalFeed(self.cfg.pumpportal_api_key)
        async for candidate in feed.stream():
            await self.add_candidate(candidate)

    async def _x_discovery_loop(self, x_client: XSearchClient) -> None:
        while True:
            try:
                posts = await x_client.search_general(self.cfg.x_search_query)
                for post in posts:
                    post_id = str(post.get("id") or "")
                    if not post_id or not self.store.mark_post_seen(post_id):
                        continue
                    for candidate in candidate_from_tweet(post):
                        await self.add_candidate(candidate)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("X discovery poll failed: %s", exc)
            await asyncio.sleep(self.cfg.x_poll_seconds)

    async def _inspect(self, candidate: Candidate, dex: DexScreenerClient,
                       x_client: XSearchClient, rug: RugCheckClient,
                       alerter: TelegramAlerter) -> None:
        for attempt in range(self.cfg.candidate_retries):
            if self.store.was_alerted(candidate.mint):
                return
            try:
                pairs = await dex.token_pairs(candidate.mint)
                if not pairs:
                    self.store.mark_checked(candidate.mint)
                    log.debug("No DexScreener pair yet for %s", candidate.mint)
                    await asyncio.sleep(min(5 * (attempt + 1), 30))
                    continue
                pair = pairs[0]
                base = pair.get("baseToken") or {}
                if base.get("address") and base.get("address") != candidate.mint:
                    # A mint may appear as quote token in a pool; do not score the wrong asset.
                    matching = [p for p in pairs if (p.get("baseToken") or {}).get("address") == candidate.mint]
                    if not matching:
                        log.info("Mint not found as the base token in DEX pair; skipping %s", candidate.mint)
                        return
                    pair = matching[0]
                snapshot_ts = time.time()
                social, risk = await asyncio.gather(
                    x_client.search_token_mentions(candidate.symbol, candidate.name, candidate.mint),
                    rug.summary(candidate.mint),
                )
                result = evaluate_signal(pair, social, risk, self.cfg)
                # Record every candidate, not just alerts, to avoid training only
                # on winners that passed the current hand-built filter.
                entry_price = pair.get("priceUsd")
                try:
                    entry_price = float(entry_price)
                except (TypeError, ValueError):
                    entry_price = 0.0
                from .scoring import pair_age_minutes
                self.store.record_model_sample(
                    candidate.mint,
                    entry_price,
                    {
                        "signal_score": result.score,
                        "qualified": int(result.qualified),
                        "liquidity_usd": float((pair.get("liquidity") or {}).get("usd") or 0),
                        "volume_5m_usd": float((pair.get("volume") or {}).get("m5") or 0),
                        "buys_5m": int((((pair.get("txns") or {}).get("m5") or {}).get("buys") or 0)),
                        "sells_5m": int((((pair.get("txns") or {}).get("m5") or {}).get("sells") or 0)),
                        "txns_5m": int((((pair.get("txns") or {}).get("m5") or {}).get("buys") or 0)) + int((((pair.get("txns") or {}).get("m5") or {}).get("sells") or 0)),
                        "price_change_5m_pct": float((pair.get("priceChange") or {}).get("m5") or 0),
                        "pair_age_minutes": pair_age_minutes(pair),
                        "rugcheck_score": risk.normalized_score,
                        "rugcheck_available": int(risk.available),
                        "rugcheck_danger_flag": int(any(str(x.get("level", "")).lower() in {"danger", "critical"} for x in risk.risks if isinstance(x, dict))),
                        "x_posts": social.posts,
                        "x_authors": social.authors,
                        "x_engagement": social.engagement,
                    },
                    signal_ts=snapshot_ts,
                )
                self.store.mark_checked(candidate.mint)
                if result.qualified:
                    await alerter.send(build_alert(candidate, result))
                    self.store.mark_alerted(candidate.mint)
                    log.info("ALERT SENT: %s (%s/100)", candidate.mint, result.score)
                else:
                    log.info("Filtered %s: %s", candidate.mint, "; ".join(result.blockers))
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Candidate check %s failed: %s", candidate.mint, exc)
                await asyncio.sleep(min(5 * (attempt + 1), 30))

    async def _recheck_loop(self, dex: DexScreenerClient) -> None:
        while True:
            await asyncio.sleep(60)
            for item in self.store.candidates_to_recheck():
                await self.queue.put(Candidate(
                    mint=item["mint"], name=item["name"], symbol=item["symbol"],
                    source=item["source"], source_url=item["source_url"],
                    first_seen_ts=item["first_seen"], raw=item["raw"],
                ))
            # Capture one fixed-horizon price per candidate for a leakage-safe
            # paper dataset. An absent pool at the horizon is recorded as no_pair.
            for sample in self.store.pending_model_outcomes(limit=50):
                try:
                    pairs = await dex.token_pairs(sample["mint"])
                    matching = [p for p in pairs if (p.get("baseToken") or {}).get("address") == sample["mint"]]
                    if not matching:
                        self.store.record_model_outcome(sample["mint"], None, "no_pair")
                        continue
                    best = max(matching, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
                    exit_price = float(best.get("priceUsd") or 0)
                    if exit_price > 0:
                        self.store.record_model_outcome(sample["mint"], exit_price, "quoted")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("15m outcome collection failed for %s: %s", sample["mint"], exc)
                await asyncio.sleep(0.25)

    async def _worker(self, dex: DexScreenerClient, x_client: XSearchClient,
                      rug: RugCheckClient, alerter: TelegramAlerter) -> None:
        while True:
            candidate = await self.queue.get()
            try:
                await self._inspect(candidate, dex, x_client, rug, alerter)
            finally:
                self.queue.task_done()

    async def run(self) -> None:
        missing = self.cfg.validate_runtime()
        if missing:
            raise RuntimeError("Missing required .env settings: " + ", ".join(missing))
        timeout = aiohttp.ClientTimeout(total=20, connect=10)
        connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            self.session = session
            dex = DexScreenerClient(session, self.cfg.dexscreener_base_url)
            x_client = XSearchClient(session, self.cfg.x_bearer_token,
                                     self.cfg.x_max_results, self.cfg.x_max_searches_per_hour)
            rug = RugCheckClient(session, self.cfg.rugcheck_base_url)
            alerter = TelegramAlerter(session, self.cfg.telegram_bot_token, self.cfg.telegram_chat_id)
            log.info("Meme Radar started. Alert-only mode; no wallet or trading key is loaded.")
            tasks = [
                asyncio.create_task(self._pumpportal_loop(), name="pumpportal"),
                asyncio.create_task(self._x_discovery_loop(x_client), name="x-discovery"),
                asyncio.create_task(self._recheck_loop(dex), name="candidate-recheck"),
                *[asyncio.create_task(self._worker(dex, x_client, rug, alerter), name=f"candidate-worker-{i}") for i in range(5)],
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self.store.close()