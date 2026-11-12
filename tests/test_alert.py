from memeradar.engine import build_alert
from memeradar.models import Candidate, RugCheckEvidence, SignalResult, SocialEvidence


def test_alert_renders_when_pair_age_is_missing():
    candidate = Candidate(mint="MintABC", name="Test meme", symbol="TEST")
    result = SignalResult(
        qualified=True, score=75, reasons=["liquidity okay"], blockers=[],
        pair={"baseToken": {"name": "Test meme", "symbol": "TEST"}, "liquidity": {"usd": 7000},
              "volume": {"m5": 2000}, "txns": {"m5": {"buys": 10, "sells": 5}}},
        social=SocialEvidence(posts=3, authors=2), rugcheck=RugCheckEvidence(True, 12, []),
    )
    text = build_alert(candidate, result)
    assert "Pair age: unavailable" in text