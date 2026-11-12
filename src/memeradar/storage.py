from __future__ import annotations

import csv
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
        # One frozen feature snapshot per mint. Outcomes are collected only after
        # the 15-minute horizon so future prices never leak into model features.
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS model_samples (
                mint TEXT PRIMARY KEY,
                signal_ts REAL NOT NULL,
                entry_price_usd REAL NOT NULL,
                features_json TEXT NOT NULL,
                exit_price_15m_usd REAL,
                outcome_ts REAL,
                outcome_status TEXT
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


    def record_model_sample(self, mint: str, entry_price_usd: float,
                             features: dict[str, Any], signal_ts: float | None = None) -> bool:
        """Freeze time-t features for one mint; later outcome fields are separate."""
        try:
            entry = float(entry_price_usd)
        except (TypeError, ValueError):
            return False
        if entry <= 0:
            return False
        stamp = float(signal_ts if signal_ts is not None else time.time())
        cur = self.db.execute(
            "INSERT OR IGNORE INTO model_samples(mint,signal_ts,entry_price_usd,features_json) VALUES(?,?,?,?)",
            (mint, stamp, entry, json.dumps(features, separators=(",", ":"), allow_nan=False)),
        )
        self.db.commit()
        return cur.rowcount > 0

    def pending_model_outcomes(self, horizon_seconds: int = 900,
                               now: float | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return snapshots whose fixed 15-minute outcome is due."""
        now = float(now if now is not None else time.time())
        rows = self.db.execute(
            "SELECT mint,signal_ts FROM model_samples "
            "WHERE outcome_status IS NULL AND signal_ts<=? ORDER BY signal_ts LIMIT ?",
            (now - horizon_seconds, limit),
        ).fetchall()
        return [{"mint": row[0], "signal_ts": row[1]} for row in rows]

    def record_model_outcome(self, mint: str, exit_price_15m_usd: float | None,
                             status: str, outcome_ts: float | None = None) -> None:
        if status not in {"quoted", "no_pair"}:
            raise ValueError("status must be 'quoted' or 'no_pair'")
        exit_price = None if exit_price_15m_usd is None else float(exit_price_15m_usd)
        if status == "quoted" and (exit_price is None or exit_price <= 0):
            raise ValueError("quoted outcomes require a positive exit price")
        self.db.execute(
            "UPDATE model_samples SET exit_price_15m_usd=?,outcome_ts=?,outcome_status=? WHERE mint=? AND outcome_status IS NULL",
            (exit_price, float(outcome_ts if outcome_ts is not None else time.time()), status, mint),
        )
        self.db.commit()

    def export_model_dataset(self, path: Path) -> int:
        """Export frozen entry features plus 15m outcome labels for offline fitting."""
        columns = [
            "signal_ts", "mint", "entry_price_usd", "exit_price_15m_usd", "outcome_ts", "outcome_status",
            "signal_score", "qualified", "liquidity_usd", "volume_5m_usd", "buys_5m", "sells_5m",
            "txns_5m", "price_change_5m_pct", "pair_age_minutes", "rugcheck_score",
            "rugcheck_available", "rugcheck_danger_flag", "x_posts", "x_authors", "x_engagement",
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.db.execute(
            "SELECT signal_ts,mint,entry_price_usd,exit_price_15m_usd,outcome_ts,outcome_status,features_json "
            "FROM model_samples WHERE outcome_status IS NOT NULL ORDER BY signal_ts"
        ).fetchall()
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for signal_ts, mint, entry, exit_price, outcome_ts, status, features_json in rows:
                features = json.loads(features_json)
                writer.writerow({
                    "signal_ts": signal_ts, "mint": mint, "entry_price_usd": entry,
                    "exit_price_15m_usd": (0.0 if status == "no_pair" else exit_price),
                    "outcome_ts": outcome_ts, "outcome_status": status,
                    **{key: features.get(key, "") for key in columns[6:]},
                })
        return len(rows)

    def close(self) -> None:
        self.db.close()