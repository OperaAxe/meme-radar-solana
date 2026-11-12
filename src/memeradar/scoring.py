from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import Config
from .models import RugCheckEvidence, SignalResult, SocialEvidence


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _nested_num(obj: dict[str, Any], *keys: str) -> float:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return 0.0
        cur = cur.get(key)
    return _num(cur)


def pair_age_minutes(pair: dict[str, Any], now_ms: int | None = None) -> float | None:
    created = _num(pair.get("pairCreatedAt"), -1)
    if created <= 0:
        return None
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    return max(0.0, (now_ms - created) / 60_000)


def evaluate_signal(pair: dict[str, Any], social: SocialEvidence,
                    rugcheck: RugCheckEvidence, cfg: Config,
                    now_ms: int | None = None) -> SignalResult:
    reasons: list[str] = []
    blockers: list[str] = []
    score = 0

    if pair.get("chainId") != "solana":
        blockers.append("Pair is not on Solana")

    liquidity = _nested_num(pair, "liquidity", "usd")
    volume_5m = _nested_num(pair, "volume", "m5")
    buys_5m = _nested_num(pair, "txns", "m5", "buys")
    sells_5m = _nested_num(pair, "txns", "m5", "sells")
    txns_5m = buys_5m + sells_5m
    change_5m = _nested_num(pair, "priceChange", "m5")
    age = pair_age_minutes(pair, now_ms)

    if liquidity < cfg.min_liquidity_usd:
        blockers.append(f"Liquidity below ${cfg.min_liquidity_usd:,.0f}")
    else:
        score += 20
        reasons.append(f"Liquidity ${liquidity:,.0f}")

    if volume_5m < cfg.min_volume_5m_usd:
        blockers.append(f"5m volume below ${cfg.min_volume_5m_usd:,.0f}")
    else:
        score += 15
        reasons.append(f"5m volume ${volume_5m:,.0f}")

    if txns_5m < cfg.min_txns_5m:
        blockers.append(f"Fewer than {cfg.min_txns_5m} swaps in 5m")
    else:
        score += 10
        reasons.append(f"{int(txns_5m)} swaps in 5m")

    if age is None:
        blockers.append("Pair age unavailable")
    elif age < cfg.min_pair_age_minutes or age > cfg.max_pair_age_minutes:
        blockers.append(f"Pair age {age:.1f}m outside configured window")
    else:
        score += 10
        reasons.append(f"Pair age {age:.1f}m")

    if change_5m < -35 or change_5m > cfg.max_price_change_5m_pct:
        blockers.append(f"5m price change {change_5m:+.1f}% is outside guardrails")
    else:
        score += 10
        reasons.append(f"5m price change {change_5m:+.1f}%")

    if sells_5m == 0 and buys_5m > 0:
        blockers.append("No sells observed in 5m window; flow may be one-sided or incomplete")
    elif sells_5m > 0:
        ratio = buys_5m / sells_5m
        if 1.10 <= ratio <= 3.50:
            score += 10
            reasons.append(f"Buy/sell count ratio {ratio:.2f}")
        elif ratio > 3.50:
            blockers.append(f"Buy/sell ratio {ratio:.2f} is unusually one-sided")
        else:
            reasons.append(f"Buy/sell ratio {ratio:.2f} (not a positive signal)")

    if social.posts >= 2:
        score += 10
        reasons.append(f"{social.posts} matching X posts")
    elif social.posts == 1:
        score += 5
        reasons.append("1 matching X post")
    else:
        blockers.append("No matching X posts found")

    if social.authors >= 2:
        score += 5
        reasons.append(f"{social.authors} distinct X authors")
    elif social.posts > 0:
        blockers.append("Social signal comes from fewer than 2 distinct X authors")

    if not rugcheck.available:
        if cfg.require_rugcheck:
            blockers.append("RugCheck unavailable; required safety check could not be completed")
        else:
            reasons.append("RugCheck unavailable — risk status UNKNOWN")
    else:
        risk_score = rugcheck.normalized_score
        severe = [r for r in rugcheck.risks if str(r.get("level", "")).lower() in {"danger", "critical"}]
        if severe:
            blockers.append("RugCheck reports danger/critical risk")
        if risk_score is None:
            if cfg.require_rugcheck:
                blockers.append("RugCheck returned no normalized score")
            else:
                reasons.append("RugCheck score unavailable")
        elif risk_score > cfg.max_rugcheck_score:
            blockers.append(f"RugCheck normalized score {risk_score:.0f} exceeds limit {cfg.max_rugcheck_score:.0f}")
        else:
            score += 10 if risk_score <= 20 else 5
            reasons.append(f"RugCheck normalized score {risk_score:.0f}")

    score = min(100, score)
    qualified = not blockers and score >= cfg.min_signal_score
    if not qualified and not blockers:
        blockers.append(f"Signal score {score}/100 is below {cfg.min_signal_score}")
    return SignalResult(qualified, score, reasons, blockers, pair, social, rugcheck)
