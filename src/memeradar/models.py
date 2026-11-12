from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    mint: str
    name: str = "Unknown"
    symbol: str = "?"
    source: str = "unknown"
    source_url: str = ""
    first_seen_ts: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0


@dataclass
class SocialEvidence:
    posts: int = 0
    authors: int = 0
    engagement: int = 0
    post_urls: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


@dataclass
class RugCheckEvidence:
    available: bool
    normalized_score: float | None = None
    risks: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""


@dataclass
class SignalResult:
    qualified: bool
    score: int
    reasons: list[str]
    blockers: list[str]
    pair: dict[str, Any]
    social: SocialEvidence
    rugcheck: RugCheckEvidence
