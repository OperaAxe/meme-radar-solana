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
