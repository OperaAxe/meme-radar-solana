from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from typing import Any, AsyncIterator
from urllib.parse import quote

import aiohttp
import websockets

from .config import Config
from .models import Candidate, RugCheckEvidence, SocialEvidence

log = logging.getLogger(__name__)

# Solana public keys use base58. Any match is only a candidate until DexScreener validates it.
SOLANA_ADDRESS_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")


class PumpPortalFeed:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = f"wss://pumpportal.fun/api/data?api-key={quote(api_key, safe='')}"

    async def stream(self) -> AsyncIterator[Candidate]:
        backoff = 2
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    await ws.send('{"method":"subscribeNewToken"}')
                    await ws.send('{"method":"subscribeMigration"}')
                    log.info("Connected to PumpPortal; subscribed to new-token and migration feeds")
                    backoff = 2
                    async for message in ws:
                        try:
                            item = __import__("json").loads(message)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(item, dict):
                            continue
                        mint = item.get("mint") or item.get("tokenAddress") or item.get("address")
                        if not isinstance(mint, str) or not 32 <= len(mint) <= 44:
                            continue
                        yield Candidate(
                            mint=mint,
                            name=str(item.get("name") or "Unknown"),
                            symbol=str(item.get("symbol") or "?"),
                            source="pumpportal_migration" if item.get("txType") == "migrate" else "pumpportal_new_token",
                            source_url=f"https://pump.fun/coin/{mint}",
                            first_seen_ts=time.time(),
                            raw=item,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # reconnect on transient websocket/network errors
                log.warning("PumpPortal stream disconnected: %s; retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


class DexScreenerClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str):
        self.session = session
        self.base_url = base_url

    async def token_pairs(self, mint: str) -> list[dict[str, Any]]:
        url = f"{self.base_url}/token-pairs/v1/solana/{quote(mint, safe='')}"
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status == 429:
                raise RuntimeError("DexScreener rate limit (429)")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        if not isinstance(data, list):
            return []
        valid = [p for p in data if isinstance(p, dict) and p.get("chainId") == "solana"]
        valid.sort(key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)
        return valid


class XSearchClient:
    SEARCH_URL = "https://api.x.com/2/tweets/search/recent"

    def __init__(self, session: aiohttp.ClientSession, bearer_token: str,
                 max_results: int = 50, max_searches_per_hour: int = 30):
        self.session = session
        self.headers = {"Authorization": f"Bearer {bearer_token}"}
        self.max_results = max(10, min(100, max_results))
        self.max_searches_per_hour = max_searches_per_hour
        self.calls: deque[float] = deque()

    async def _get_posts(self, query: str) -> list[dict[str, Any]]:
        now = time.time()
        while self.calls and now - self.calls[0] > 3600:
            self.calls.popleft()
        if len(self.calls) >= self.max_searches_per_hour:
            log.warning("X query budget exhausted for this hour; skipping query")
            return []
        params = {
            "query": query[:512],
            "max_results": str(self.max_results),
            "tweet.fields": "created_at,public_metrics,author_id,entities,lang",
            "expansions": "author_id",
            "user.fields": "username,public_metrics,verified",
        }
        async with self.session.get(self.SEARCH_URL, headers=self.headers, params=params,
                                    timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 429:
                log.warning("X recent-search rate limit (429)")
                return []
            if resp.status in {401, 403}:
                raise RuntimeError(f"X API authentication/access error ({resp.status}); check bearer token and plan")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        self.calls.append(now)
        users = {u.get("id"): u for u in data.get("includes", {}).get("users", []) if isinstance(u, dict)}
        posts = []
        for post in data.get("data", []) or []:
            if not isinstance(post, dict):
                continue
            user = users.get(post.get("author_id"), {})
            metrics = post.get("public_metrics") or {}
            post["_username"] = user.get("username", "unknown")
            post["_followers"] = int((user.get("public_metrics") or {}).get("followers_count") or 0)
            post["_engagement"] = sum(int(metrics.get(k) or 0) for k in ("like_count", "reply_count", "retweet_count", "quote_count"))
            posts.append(post)
        return posts

    async def search_general(self, query: str) -> list[dict[str, Any]]:
        return await self._get_posts(query)

    async def search_token_mentions(self, symbol: str, name: str, mint: str) -> SocialEvidence:
        terms = []
        if symbol and symbol != "?":
            terms.append(f'"${symbol}"')
            terms.append(f'"{symbol}"')
        if name and name != "Unknown" and len(name) > 2:
            terms.append(f'"{name}"')
        terms.append(mint)
        query = "(" + " OR ".join(dict.fromkeys(terms)) + ") lang:en -is:retweet"
        try:
            posts = await self._get_posts(query)
        except Exception as exc:
            log.warning("X mention lookup failed for %s: %s", mint, exc)
            return SocialEvidence()
        authors = {p.get("author_id") for p in posts if p.get("author_id")}
        urls = [f"https://x.com/{p.get('_username','i')}/status/{p.get('id')}" for p in posts if p.get("id")]
        samples = [str(p.get("text", ""))[:180] for p in posts[:3]]
        return SocialEvidence(
            posts=len(posts), authors=len(authors),
            engagement=sum(int(p.get("_engagement") or 0) for p in posts),
            post_urls=urls[:5], samples=samples,
        )


class RugCheckClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str):
        self.session = session
        self.base_url = base_url

    async def summary(self, mint: str) -> RugCheckEvidence:
        url = f"{self.base_url}/tokens/{quote(mint, safe='')}/report/summary"
        try:
            async with self.session.get(url, headers={"accept": "application/json"},
                                        timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status in {401, 403, 404, 429, 500, 502, 503, 504}:
                    return RugCheckEvidence(False, summary=f"HTTP {resp.status}")
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            if not isinstance(data, dict):
                return RugCheckEvidence(False, summary="Unexpected response")
            risks = data.get("risks") if isinstance(data.get("risks"), list) else []
            normalized = data.get("score_normalised")
            try:
                normalized = float(normalized) if normalized is not None else None
            except (TypeError, ValueError):
                normalized = None
            labels = [str(r.get("name")) for r in risks if isinstance(r, dict) and r.get("name")]
            return RugCheckEvidence(True, normalized, risks, ", ".join(labels[:5]))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            return RugCheckEvidence(False, summary=type(exc).__name__)


class TelegramAlerter:
    def __init__(self, session: aiohttp.ClientSession, bot_token: str, chat_id: str):
        self.session = session
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id

    async def send(self, text: str) -> None:
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        async with self.session.post(self.url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400 or not data.get("ok"):
                raise RuntimeError(f"Telegram send failed ({resp.status}): {data.get('description', 'unknown error')}")


def extract_solana_addresses(text: str) -> set[str]:
    return set(SOLANA_ADDRESS_RE.findall(text or ""))


def candidate_from_tweet(post: dict[str, Any]) -> list[Candidate]:
    text = str(post.get("text") or "")
    post_id = str(post.get("id") or "")
    username = str(post.get("_username") or "unknown")
    post_url = f"https://x.com/{username}/status/{post_id}" if post_id else ""
    return [Candidate(mint=mint, name="X-discovered token", symbol="?", source="x_post",
                      source_url=post_url, first_seen_ts=time.time(), raw={"tweet": text[:500]})
            for mint in extract_solana_addresses(text)]
