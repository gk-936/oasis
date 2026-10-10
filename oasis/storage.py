"""SQLite persistence (stdlib sqlite3) for the API session: Passport, audit log, proofs, why-cards, ledger, pending.

ENCRYPTED AT REST. Every payload column (the `json` column of kv / audit / proofs / cards) is stored as
`enc1:` + base64(nonce || AES-256-GCM ciphertext), with the table and row id bound in as associated data so a row cannot
be copied to another place. The data key comes from a git-ignored key file (data/keys/data_key.json, override with
OASIS_DATA_KEY; see trust/keyfile.py for the honest limits and the optional passphrase wrapping). The database file
alone therefore reveals no payee names, amounts, account numbers or approvals. What stays in clear: table names, row
ids (kv key names such as "passport", proof/intent ids like "int_0001", audit indexes) and the row count. The audit
hash chain is computed over the decrypted entries and is verified after every load.

In-memory stays the default for tests and the benchmark (they never create a store). The API attaches a store so
state survives a restart. Audit entries are written as they are appended; everything else is saved as a snapshot after
each state-changing request. Trust signing keys are NOT stored here (trust/keystore.py).

Migration: a database written by an older version (plaintext JSON, no `meta` table) is migrated in place, once, inside
one transaction, the first time it is opened with a data key. Afterwards a plaintext row inside an encrypted database is
refused (it can only have been injected). A database that cannot be decrypted with the current key is refused with a
clear message, never silently emptied.
"""
from __future__ import annotations
import json
import os
import sqlite3
import threading
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .trust.crypto import b64, unb64
from .trust.keyfile import default_data_key_path, load_or_create_secret

PREFIX = "enc1:"
TABLES = {"kv": "key", "audit": "i", "proofs": "id", "cards": "id"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS kv     (key TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit  (i INTEGER PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proofs (id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards  (id TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta   (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class StoreError(RuntimeError):
    """The database cannot be opened safely (wrong key, tampered or plaintext row)."""


class Cipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("data key must be 32 bytes")
        self._aes = AESGCM(key)

    def seal(self, table: str, rowid, plain: str) -> str:
        nonce = os.urandom(12)
        return PREFIX + b64(nonce + self._aes.encrypt(nonce, plain.encode(), f"{table}|{rowid}".encode()))

    def open(self, table: str, rowid, sealed: str) -> str:
        if not sealed.startswith(PREFIX):
            raise StoreError(f"{table} row {rowid!r} is plaintext inside an encrypted database; refusing to load it")
        raw = unb64(sealed[len(PREFIX):])
        try:
            return self._aes.decrypt(raw[:12], raw[12:], f"{table}|{rowid}".encode()).decode()
        except InvalidTag as e:
            raise StoreError(f"cannot decrypt {table} row {rowid!r}: wrong data key, or the row was altered") from e


class SqliteStore:
    def __init__(self, path: str | Path, key: bytes | None = None, key_path: str | Path | None = None):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._cipher = Cipher(key if key is not None else load_or_create_secret(Path(key_path) if key_path else default_data_key_path()))
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self.migrated_rows = 0
        with self._lock:
            has_tables = self._db.execute("SELECT count(*) FROM sqlite_master WHERE name='kv'").fetchone()[0] > 0
            legacy_rows = has_tables and sum(self._db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES) > 0
            has_meta = self._db.execute("SELECT count(*) FROM sqlite_master WHERE name='meta'").fetchone()[0] > 0
            self._db.executescript(SCHEMA)
            fmt = self._db.execute("SELECT value FROM meta WHERE key='keycheck'").fetchone()
            if fmt is None:
                if legacy_rows and not has_meta:
                    self._migrate_plaintext()
                elif legacy_rows:
                    raise StoreError("database has data but no key check: refusing to open it")
                self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('keycheck', ?)",
                                 (self._cipher.seal("meta", "keycheck", "oasis-store-v1"),))
                self._db.commit()
            elif self._cipher.open("meta", "keycheck", fmt[0]) != "oasis-store-v1":
                raise StoreError("data key check failed")

    def _migrate_plaintext(self) -> None:
        """Old plaintext database -> encrypted, in one transaction."""
        n = 0
        for table, col in TABLES.items():
            for rowid, js in self._db.execute(f"SELECT {col}, json FROM {table}").fetchall():
                if js.startswith(PREFIX):
                    continue
                json.loads(js)    # must be valid JSON before we trust it
                self._db.execute(f"UPDATE {table} SET json=? WHERE {col}=?", (self._cipher.seal(table, rowid, js), rowid))
                n += 1
        self.migrated_rows = n

    def _seal(self, table: str, rowid, obj) -> str:
        return self._cipher.seal(table, rowid, json.dumps(obj, sort_keys=True, default=str))

    def _open(self, table: str, rowid, sealed: str):
        return json.loads(self._cipher.open(table, rowid, sealed))

    # -- audit log (append-only, written as it happens) -------------------------------------------
    def append_audit(self, entry: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO audit(i, json) VALUES (?, ?)",
                             (entry["i"], self._seal("audit", entry["i"], entry)))
            self._db.commit()

    def load_audit(self) -> list[dict]:
        rows = self._db.execute("SELECT i, json FROM audit ORDER BY i").fetchall()
        return [self._open("audit", i, js) for i, js in rows]

    # -- snapshot ----------------------------------------------------------------------------------
    def save(self, snapshot: dict) -> None:
        """snapshot: {"kv": {key: obj}, "proofs": {id: pack}, "cards": [card, ...]}"""
        with self._lock:
            c = self._db
            for k, v in snapshot.get("kv", {}).items():
                c.execute("INSERT OR REPLACE INTO kv(key, json) VALUES (?, ?)", (k, self._seal("kv", k, v)))
            for k, v in snapshot.get("proofs", {}).items():
                c.execute("INSERT OR REPLACE INTO proofs(id, json) VALUES (?, ?)", (k, self._seal("proofs", k, v)))
            for card in snapshot.get("cards", []):
                c.execute("INSERT OR REPLACE INTO cards(id, json) VALUES (?, ?)", (card["id"], self._seal("cards", card["id"], card)))
            c.commit()

    def load(self) -> dict | None:
        """Return the stored snapshot, or None if nothing has been saved yet."""
        with self._lock:
            kv = {k: self._open("kv", k, v) for k, v in self._db.execute("SELECT key, json FROM kv")}
            if "passport" not in kv:
                return None
            proofs = {k: self._open("proofs", k, v) for k, v in self._db.execute("SELECT id, json FROM proofs")}
            cards = [self._open("cards", i, v) for i, v in self._db.execute("SELECT id, json FROM cards ORDER BY id")]
            audit = self.load_audit()
        return {"kv": kv, "proofs": proofs, "cards": cards, "audit": audit}

    def clear(self) -> None:
        with self._lock:
            for t in TABLES:
                self._db.execute(f"DELETE FROM {t}")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
