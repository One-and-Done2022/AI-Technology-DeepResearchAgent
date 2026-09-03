"""Small SQLite store for auditable report evidence."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any


class EvidenceStore:
    def __init__(self, db_path: str = "data/evidence.db") -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS evidence_runs (
                    run_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    report_content TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS evidence_sources (
                    run_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, source_id)
                );
                CREATE TABLE IF NOT EXISTS evidence_claims (
                    run_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, claim_id)
                );
                """
            )

    def save_report(
        self,
        run_id: str,
        query: str,
        content: str,
        sources: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO evidence_runs
                   (run_id, query, report_content, metrics_json)
                   VALUES (?, ?, ?, ?)""",
                (run_id, query, content, json.dumps(metrics, ensure_ascii=False)),
            )
            conn.executemany(
                """INSERT OR REPLACE INTO evidence_sources
                   (run_id, source_id, payload_json) VALUES (?, ?, ?)""",
                [
                    (run_id, source.get("source_id", ""), json.dumps(source, ensure_ascii=False))
                    for source in sources
                    if source.get("source_id")
                ],
            )
            conn.executemany(
                """INSERT OR REPLACE INTO evidence_claims
                   (run_id, claim_id, payload_json) VALUES (?, ?, ?)""",
                [
                    (run_id, claim.get("claim_id", ""), json.dumps(claim, ensure_ascii=False))
                    for claim in claims
                    if claim.get("claim_id")
                ],
            )

    def load_report(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            run = conn.execute(
                "SELECT * FROM evidence_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                return None
            sources = conn.execute(
                "SELECT payload_json FROM evidence_sources WHERE run_id = ? ORDER BY source_id",
                (run_id,),
            ).fetchall()
            claims = conn.execute(
                "SELECT payload_json FROM evidence_claims WHERE run_id = ? ORDER BY claim_id",
                (run_id,),
            ).fetchall()
        return {
            "run_id": run_id,
            "query": run["query"],
            "content": run["report_content"],
            "metrics": json.loads(run["metrics_json"]),
            "sources": [json.loads(item["payload_json"]) for item in sources],
            "claims": [json.loads(item["payload_json"]) for item in claims],
        }
