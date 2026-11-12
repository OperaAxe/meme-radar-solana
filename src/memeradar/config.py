from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    x_bearer_token: str
    x_search_query: str
    x_poll_seconds: int
    x_max_results: int
    x_max_searches_per_hour: int
    pumpportal_api_key: str
    min_liquidity_usd: float
    min_volume_5m_usd: float
    min_txns_5m: int
    min_pair_age_minutes: float
    max_pair_age_minutes: float
    max_price_change_5m_pct: float
    max_rugcheck_score: float
    min_signal_score: int
    require_rugcheck: bool
    dexscreener_base_url: str
    rugcheck_base_url: str
    database_path: Path
    check_interval_seconds: int
    candidate_retries: int
    log_level: str

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Config":
        if env_file:
            load_dotenv(env_file)

        def get(name: str, default: str = "") -> str:
            return os.getenv(name, default).strip()

        def as_bool(name: str, default: bool) -> bool:
            value = get(name, str(default)).lower()
            return value in {"1", "true", "yes", "on"}

        return cls(
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=get("TELEGRAM_CHAT_ID"),
            x_bearer_token=get("X_BEARER_TOKEN"),
            x_search_query=get(
                "X_SEARCH_QUERY",
                '(pump.fun OR pumpfun OR memecoin OR "meme coin") lang:en -is:retweet -is:reply',
            ),
            x_poll_seconds=int(get("X_POLL_SECONDS", "180")),
            x_max_results=max(10, min(100, int(get("X_MAX_RESULTS", "50")))),
            x_max_searches_per_hour=max(1, int(get("X_MAX_SEARCHES_PER_HOUR", "30"))),
            pumpportal_api_key=get("PUMPPORTAL_API_KEY"),
            min_liquidity_usd=float(get("MIN_LIQUIDITY_USD", "5000")),
            min_volume_5m_usd=float(get("MIN_VOLUME_5M_USD", "1500")),
            min_txns_5m=int(get("MIN_TXNS_5M", "8")),
            min_pair_age_minutes=float(get("MIN_PAIR_AGE_MINUTES", "1")),
            max_pair_age_minutes=float(get("MAX_PAIR_AGE_MINUTES", "240")),
            max_price_change_5m_pct=float(get("MAX_PRICE_CHANGE_5M_PCT", "90")),
            max_rugcheck_score=float(get("MAX_RUGCHECK_SCORE", "40")),
            min_signal_score=int(get("MIN_SIGNAL_SCORE", "65")),
            require_rugcheck=as_bool("REQUIRE_RUGCHECK", True),
            dexscreener_base_url=get("DEXSCREENER_BASE_URL", "https://api.dexscreener.com").rstrip("/"),
            rugcheck_base_url=get("RUGCHECK_BASE_URL", "https://api.rugcheck.xyz/v1").rstrip("/"),
            database_path=Path(get("DATABASE_PATH", "data/meme_radar.sqlite3")),
            check_interval_seconds=max(5, int(get("CHECK_INTERVAL_SECONDS", "20"))),
            candidate_retries=max(1, int(get("CANDIDATE_RETRIES", "6"))),
            log_level=get("LOG_LEVEL", "INFO").upper(),
        )

    def validate_runtime(self) -> list[str]:
        missing = []
        for key, value in (
            ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
            ("TELEGRAM_CHAT_ID", self.telegram_chat_id),
            ("X_BEARER_TOKEN", self.x_bearer_token),
            ("PUMPPORTAL_API_KEY", self.pumpportal_api_key),
        ):
            if not value:
                missing.append(key)
        return missing
