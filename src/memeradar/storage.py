from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                mint TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL,
                first_seen REAL NOT NULL,
                last_checked REAL NOT NULL DEFAULT 0,
                alerted INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id TEXT PRIMARY KEY,
                seen_at REAL NOT NULL
            )
        """)
        self.db.commit()

    def add_candidate(self, mint: str, name: str, symbol: str, source: str,
                      source_url: str = "", raw: dict[str, Any] | None = None) -> bool:
        now = time.time()
        cur = self.db.execute(
            "INSERT OR IGNORE INTO candidates(mint,name,symbol,source,source_url,first_seen,raw_json) VALUES(?,?,?,?,?,?,?)",
            (mint, name or "Unknown", symbol or "?", source, source_url, now,
             json.dumps(raw or {}, separators=(",", ":"))),
        )
        self.db.commit()
        return cur.rowcount > 0

    def mark_checked(self, mint: str) -> None:
        self.db.execute("UPDATE candidates SET last_checked=? WHERE mint=?", (time.time(), mint))
        self.db.commit()

    def mark_alerted(self, mint: str) -> None:
        self.db.execute("UPDATE candidates SET alerted=1,last_checked=? WHERE mint=?", (time.time(), mint))
        self.db.commit()

    def was_alerted(self, mint: str) -> bool:
        row = self.db.execute("SELECT alerted FROM candidates WHERE mint=?", (mint,)).fetchone()
        return bool(row and row[0])

    def mark_post_seen(self, post_id: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO seen_posts(post_id,seen_at) VALUES(?,?)", (post_id, time.time()))
        self.db.commit()
        return cur.rowcount > 0

    def candidates_to_recheck(self, older_than_seconds: int = 300, max_age_seconds: int = 14_400, limit: int = 100) -> list[dict[str, Any]]:
        now = time.time()
        rows = self.db.execute(
            "SELECT mint,name,symbol,source,source_url,first_seen,raw_json FROM candidates "
            "WHERE alerted=0 AND first_seen>? AND (last_checked=0 OR last_checked<?) "
            "ORDER BY first_seen DESC LIMIT ?",
            (now - max_age_seconds, now - older_than_seconds, limit),
        ).fetchall()
        return [
            {"mint": r[0], "name": r[1], "symbol": r[2], "source": r[3],
             "source_url": r[4], "first_seen": r[5], "raw": json.loads(r[6])}
            for r in rows
        ]

    def get_candidate(self, mint: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT mint,name,symbol,source,source_url,first_seen,raw_json FROM candidates WHERE mint=?",
            (mint,),
        ).fetchone()
        if not row:
            return None
        return {"mint": row[0], "name": row[1], "symbol": row[2], "source": row[3],
                "source_url": row[4], "first_seen": row[5], "raw": json.loads(row[6])}

    def close(self) -> None:
        self.db.close()
