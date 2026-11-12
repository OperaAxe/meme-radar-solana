from pathlib import Path

from memeradar.providers import extract_solana_addresses
from memeradar.storage import Store


def test_extracts_base58_candidate_address():
    address = "So11111111111111111111111111111111111111112"
    assert address in extract_solana_addresses(f"New meme token CA: {address}")


def test_store_deduplicates_candidates_and_posts(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite3")
    assert store.add_candidate("Mint123", "Name", "SYM", "test")
    assert not store.add_candidate("Mint123", "Name", "SYM", "test")
    assert store.mark_post_seen("post-1")
    assert not store.mark_post_seen("post-1")
    store.close()


def test_model_snapshot_is_frozen_and_outcome_exported(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite3")
    assert store.record_model_sample("MintABC", 0.01, {"signal_score": 72, "liquidity_usd": 9000}, signal_ts=1000)
    assert not store.record_model_sample("MintABC", 0.02, {"signal_score": 99}, signal_ts=1001)
    assert store.pending_model_outcomes(horizon_seconds=900, now=1899) == []
    assert store.pending_model_outcomes(horizon_seconds=900, now=1900)[0]["mint"] == "MintABC"
    store.record_model_outcome("MintABC", 0.012, "quoted", outcome_ts=1901)
    out = tmp_path / "training.csv"
    assert store.export_model_dataset(out) == 1
    content = out.read_text(encoding="utf-8")
    assert "MintABC" in content
    assert "0.012" in content
    store.close()