"""Persistent SQLite Versioned Counterexample Ledger."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from cegar_harness.models import CounterexampleRecord


class CounterexampleLedger:
    """SQLite-backed versioned ledger storing verified failure witnesses across compactions."""

    VALID_STATUSES = frozenset({"ACTIVE", "RESOLVED", "OBSOLETE"})

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._conn.execute("PRAGMA foreign_keys = ON;")
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS counterexamples (
                        ce_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        target_file TEXT NOT NULL,
                        target_symbol TEXT NOT NULL,
                        contract_version TEXT NOT NULL,
                        ast_hash TEXT NOT NULL,
                        witness_name TEXT NOT NULL,
                        witness_test_code TEXT NOT NULL,
                        failure_predicate TEXT NOT NULL,
                        discovered_at_step INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ACTIVE',
                        provenance TEXT NOT NULL DEFAULT 'oracle_test_failure'
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ce_task ON counterexamples(task_id, status)"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ce_ast ON counterexamples(task_id, ast_hash)"
                )

    def record(self, ce: CounterexampleRecord) -> None:
        """Inserts or updates a counterexample witness in the ledger."""
        if ce.status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid counterexample status: {ce.status!r}. Must be one of {sorted(self.VALID_STATUSES)}")
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO counterexamples (
                    ce_id, task_id, target_file, target_symbol, contract_version,
                    ast_hash, witness_name, witness_test_code, failure_predicate,
                    discovered_at_step, status, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ce.ce_id,
                    ce.task_id,
                    ce.target_file,
                    ce.target_symbol,
                    ce.contract_version,
                    ce.ast_hash,
                    ce.witness_name,
                    ce.witness_test_code,
                    ce.failure_predicate,
                    ce.discovered_at_step,
                    ce.status,
                    ce.provenance,
                ),
            )

    def get_by_task(self, task_id: str, include_resolved: bool = True) -> List[CounterexampleRecord]:
        """Retrieves counterexamples for a given task."""
        query = "SELECT * FROM counterexamples WHERE task_id = ?"
        params: list[object] = [task_id]
        if not include_resolved:
            query += " AND status = 'ACTIVE'"
        query += " ORDER BY discovered_at_step ASC, ce_id ASC"
        with self._lock:
            cur = self._conn.execute(query, params)
            return [self._row_to_record(r) for r in cur.fetchall()]

    def find_by_ast_hash(self, task_id: str, ast_hash: str) -> Optional[CounterexampleRecord]:
        """Looks up a counterexample by task_id and canonical AST hash."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM counterexamples WHERE task_id = ? AND ast_hash = ? LIMIT 1",
                (task_id, ast_hash),
            )
            row = cur.fetchone()
            return self._row_to_record(row) if row else None

    def mark_status(self, ce_id: str, status: str) -> None:
        """Updates the lifecycle status ('ACTIVE', 'RESOLVED', 'OBSOLETE') of a witness."""
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid counterexample status: {status!r}. Must be one of {sorted(self.VALID_STATUSES)}")
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE counterexamples SET status = ? WHERE ce_id = ?",
                (status, ce_id),
            )

    def count(self, task_id: Optional[str] = None) -> int:
        with self._lock:
            if task_id:
                cur = self._conn.execute(
                    "SELECT COUNT(*) AS cnt FROM counterexamples WHERE task_id = ?", (task_id,)
                )
            else:
                cur = self._conn.execute("SELECT COUNT(*) AS cnt FROM counterexamples")
            return int(cur.fetchone()["cnt"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CounterexampleRecord:
        return CounterexampleRecord(
            ce_id=row["ce_id"],
            task_id=row["task_id"],
            target_file=row["target_file"],
            target_symbol=row["target_symbol"],
            contract_version=row["contract_version"],
            ast_hash=row["ast_hash"],
            witness_name=row["witness_name"],
            witness_test_code=row["witness_test_code"],
            failure_predicate=row["failure_predicate"],
            discovered_at_step=int(row["discovered_at_step"]),
            status=row["status"],
            provenance=row["provenance"],
        )
