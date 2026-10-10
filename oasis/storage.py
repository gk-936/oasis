"""SQLite persistence (stdlib sqlite3) for the API session: Passport, audit log, proofs and why-cards.

In-memory stays the default for tests and the benchmark (they never create a store). The API attaches a
store so state survives a restart. Audit entries are written as they are appended; everything else is
saved as a snapshot after each state-changing request. Signing keys are NOT stored: they are ephemeral per
process in this build (proof packs embed their public keys, so packs issued before a restart still verify).
"""
from __future__ import annotations
import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv     (key TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit  (i INTEGER PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proofs (id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards  (id TEXT PRIMARY KEY, json TEXT NOT NULL);
"""


class SqliteStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # -- audit log (append-only, written as it happens) -------------------------------------------
    def append_audit(self, entry: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO audit(i, json) VALUES (?, ?)",
                             (entry["i"], json.dumps(entry, sort_keys=True)))
            self._db.commit()

    def load_audit(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT json FROM audit ORDER BY i").fetchall()
        return [json.loads(r[0]) for r in rows]

    # -- snapshot ----------------------------------------------------------------------------------
    def save(self, snapshot: dict) -> None:
        """snapshot: {"kv": {key: obj}, "proofs": {id: pack}, "cards": [card, ...]}"""
        with self._lock:
            c = self._db
            for k, v in snapshot.get("kv", {}).items():
                c.execute("INSERT OR REPLACE INTO kv(key, json) VALUES (?, ?)", (k, json.dumps(v, default=str)))
            for k, v in snapshot.get("proofs", {}).items():
                c.execute("INSERT OR REPLACE INTO proofs(id, json) VALUES (?, ?)", (k, json.dumps(v, default=str)))
            for card in snapshot.get("cards", []):
                c.execute("INSERT OR REPLACE INTO cards(id, json) VALUES (?, ?)", (card["id"], json.dumps(card, default=str)))
            c.commit()

    def load(self) -> dict | None:
        """Return the stored snapshot, or None if nothing has been saved yet."""
        with self._lock:
            kv = {k: json.loads(v) for k, v in self._db.execute("SELECT key, json FROM kv")}
            if "passport" not in kv:
                return None
            proofs = {k: json.loads(v) for k, v in self._db.execute("SELECT id, json FROM proofs")}
            cards = [json.loads(v) for (v,) in self._db.execute("SELECT json FROM cards ORDER BY id")]
        return {"kv": kv, "proofs": proofs, "cards": cards, "audit": self.load_audit()}

    def clear(self) -> None:
        with self._lock:
            for t in ("kv", "audit", "proofs", "cards"):
                self._db.execute(f"DELETE FROM {t}")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
