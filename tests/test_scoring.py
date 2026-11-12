from memeradar.config import Config
from memeradar.models import RugCheckEvidence, SocialEvidence
from memeradar.scoring import evaluate_signal


def good_pair():
    return {
        "chainId": "solana",
        "baseToken": {"address": "Mint111111111111111111111111111111111111"},
        "pairCreatedAt": 1_795_000_000_000,
        "liquidity": {"usd": 25_000},
        "volume": {"m5": 8_000},
        "txns": {"m5": {"buys": 35, "sells": 15}},
        "priceChange": {"m5": 12.0},
    }


def test_valid_snapshot_passes_with_social_and_risk_evidence():
    cfg = Config.from_env(env_file=None)
    result = evaluate_signal(
        good_pair(), SocialEvidence(posts=5, authors=3),
        RugCheckEvidence(True, 12, []), cfg,
        now_ms=1_795_000_000_000 + 30 * 60_000,
    )
    assert result.qualified
    assert result.score >= cfg.min_signal_score
    assert not result.blockers


def test_missing_rugcheck_blocks_by_default():
    cfg = Config.from_env(env_file=None)
    result = evaluate_signal(
        good_pair(), SocialEvidence(posts=5, authors=3),
        RugCheckEvidence(False), cfg,
        now_ms=1_795_000_000_000 + 30 * 60_000,
    )
    assert not result.qualified
    assert any("RugCheck unavailable" in item for item in result.blockers)


def test_low_liquidity_and_vertical_price_move_are_rejected():
    cfg = Config.from_env(env_file=None)
    pair = good_pair()
    pair["liquidity"]["usd"] = 900
    pair["priceChange"]["m5"] = 220
    result = evaluate_signal(
        pair, SocialEvidence(posts=5, authors=3), RugCheckEvidence(True, 12, []), cfg,
        now_ms=1_795_000_000_000 + 30 * 60_000,
    )
    assert not result.qualified
    assert any("Liquidity below" in item for item in result.blockers)
    assert any("price change" in item for item in result.blockers)


def test_severe_rugcheck_flag_blocks_even_if_score_is_low():
    cfg = Config.from_env(env_file=None)
    result = evaluate_signal(
        good_pair(), SocialEvidence(posts=5, authors=3),
        RugCheckEvidence(True, 10, [{"name": "Dangerous mint authority", "level": "danger"}]), cfg,
        now_ms=1_795_000_000_000 + 30 * 60_000,
    )
    assert not result.qualified
    assert any("danger/critical" in item for item in result.blockers)
