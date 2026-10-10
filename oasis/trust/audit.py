"""Hash-chained audit log (SHA-256) with a verifier that reports the first broken link."""
from __future__ import annotations
import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .crypto import canonical, sha256_hex

GENESIS = "0" * 64


def entry_hash(index: int, ts: float, kind: str, data: dict, prev_hash: str) -> str:
    return sha256_hex(canonical({"i": index, "ts": ts, "kind": kind, "data": data, "prev": prev_hash}))


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    first_broken: int | None = None
    reason: str = ""


class AuditLog:
    def __init__(self, path: Path | None = None, clock=time.time, on_append=None):
        self.entries: list[dict] = []
        self.path = path
        self.clock = clock
        self.on_append = on_append      # persistence hook (SQLite store)
        if path and path.exists():
            self.entries = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def append(self, kind: str, data: dict) -> dict:
        i = len(self.entries)
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        data = copy.deepcopy(data)       # entries are immutable once written; callers may keep mutating their dicts
        ts = round(self.clock(), 3)
        e = {"i": i, "ts": ts, "kind": kind, "data": data, "prev": prev,
             "hash": entry_hash(i, ts, kind, data, prev)}
        self.entries.append(e)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        if self.on_append:
            self.on_append(e)
        return e

    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def find(self, kind: str | None = None, **match) -> list[dict]:
        return [e for e in self.entries if (kind is None or e["kind"] == kind)
                and all(e["data"].get(k) == v for k, v in match.items())]


def verify_chain(entries: list[dict]) -> VerifyResult:
    prev = GENESIS
    for n, e in enumerate(entries):
        if e.get("i") != n:
            return VerifyResult(False, len(entries), n, "index out of sequence")
        if e.get("prev") != prev:
            return VerifyResult(False, len(entries), n, "prev hash does not match")
        if entry_hash(e["i"], e["ts"], e["kind"], e["data"], e["prev"]) != e.get("hash"):
            return VerifyResult(False, len(entries), n, "entry content was altered")
        prev = e["hash"]
    return VerifyResult(True, len(entries))
