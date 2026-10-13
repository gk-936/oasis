"""Public-data checks on a payee: sanctions-list screening and bank-identifier sanity checks.

Sanctions: the US Treasury OFAC SDN list, a snapshot stored in `oasis/reference/ofac_sdn.json.gz` (refresh with
`python tools/fetch_reference.py`), plus the UN / UK / EU consolidated lists in `sanctions_extra.json.gz` (`tools/fetch_extra_sanctions.py`). A name that matches an entry closely produces EVIDENCE for the risk scorer and a human
review; it is never an automatic block, and a clean result is NOT a compliance clearance (one list, one snapshot, Latin names
only, fuzzy matching). Bank identifiers: Luhn and length for Chinese bank cards, shape of an Indian IFSC code. A failed card
check is information for the student, not a payment rule: the sandbox's own demo accounts are not real card numbers.
"""
from __future__ import annotations
import gzip
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

DATA = Path(__file__).with_name("reference") / "ofac_sdn.json.gz"
EXTRA = Path(__file__).with_name("reference") / "sanctions_extra.json.gz"      # UN + UK + EU consolidated lists (tools/fetch_extra_sanctions.py)
MATCH_THRESHOLD = 0.90
_PUNCT = re.compile(r"[^\w\s]", re.U)
_STOP = {"the", "of", "and", "co", "ltd", "limited", "inc", "llc", "company", "corp", "corporation"}


def _norm_tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return sorted(t for t in _PUNCT.sub(" ", s).split() if t)


class Sanctions:
    def __init__(self, path: Path | None = None, extra: Path | None = None):
        """By default the OFAC SDN snapshot plus, when present, the UN / UK / EU snapshot. An explicit `path` loads only that file
        (tests), unless `extra` is given as well."""
        self.meta: dict = {}
        self._rows: list[tuple[list[str], dict, str]] = []
        self._index: dict[str, list[int]] = {}
        files = [path or DATA] + ([extra] if extra else [EXTRA] if path is None and EXTRA.exists() else [])
        lists: dict[str, dict] = {}
        for k, fp in enumerate(files):
            try:
                with gzip.open(fp, "rt", encoding="utf-8") as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                continue
            if k == 0:
                self.meta = {key: doc.get(key) for key in ("source", "retrieved", "count")}
            lists.update(doc.get("lists") or {"OFAC": {"count": doc.get("count"), "retrieved": doc.get("retrieved")}})
            for e in doc.get("entries", []):
                e.setdefault("list", "OFAC")
                for nm, kind in [(e["name"], "name")] + [(a, "alias") for a in e.get("aliases", [])]:
                    toks = _norm_tokens(nm)
                    if not toks:
                        continue
                    i = len(self._rows)
                    self._rows.append((toks, e, kind))
                    for t in set(toks) - _STOP:
                        self._index.setdefault(t, []).append(i)
        if lists:
            self.meta["lists"] = lists

    @property
    def available(self) -> bool:
        return bool(self._rows)

    def screen(self, name: str, threshold: float = MATCH_THRESHOLD, limit: int = 3) -> list[dict]:
        q = _norm_tokens(name)
        if not q or not self.available:
            return []
        cand = {i for t in set(q) - _STOP for i in self._index.get(t, ())}
        qs = " ".join(q)
        hits: dict[str, dict] = {}
        for i in cand:
            toks, e, kind = self._rows[i]
            if abs(len(toks) - len(q)) > 1:
                continue
            score = SequenceMatcher(None, qs, " ".join(toks)).ratio()
            if score >= threshold and (e["uid"] not in hits or score > hits[e["uid"]]["score"]):
                hits[e["uid"]] = {"uid": e["uid"], "name": e["name"], "type": e["type"], "program": e["program"],
                                  "score": round(score, 3), "matched": kind, "list": e.get("list", "OFAC")}
        return sorted(hits.values(), key=lambda h: -h["score"])[:limit]


_SANCTIONS: Sanctions | None = None


def sanctions() -> Sanctions:
    global _SANCTIONS
    if _SANCTIONS is None:
        _SANCTIONS = Sanctions()
    return _SANCTIONS


# ------------------------------------------------------------------------------------------------ bank identifiers
def luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


# Six-digit issuer prefixes of some large Chinese banks. UNOFFICIAL and incomplete (no free official source exists); a miss
# means "not in this short list", never "not a real bank".
CN_BIN = {"622848": "Agricultural Bank of China", "622202": "ICBC", "621661": "Bank of China", "622700": "China Construction Bank",
          "622588": "China Merchants Bank", "622262": "Bank of Communications"}


def cn_card_check(account: str) -> dict:
    a = re.sub(r"[\s-]", "", str(account or ""))
    ok_len = a.isdigit() and 16 <= len(a) <= 19
    return {"length_ok": ok_len, "luhn_ok": luhn_ok(a) if ok_len else False, "issuer_prefix": CN_BIN.get(a[:6]),
            "note": "format check only; says nothing about whether the account exists or whose it is"}


IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def ifsc_check(code: str) -> dict:
    c = str(code or "").strip().upper()
    return {"ifsc": c, "format_ok": bool(IFSC_RE.match(c)), "bank_code": c[:4] if IFSC_RE.match(c) else None,
            "note": "shape only (4 letters, 0, 6 characters); look-up against the RBI list needs network"}


def screen_payee(name: str, account: str | None = None, ifsc: str | None = None) -> dict:
    s = sanctions()
    out = {"sanctions": {"available": s.available, "hits": s.screen(name) if s.available else [], "list": s.meta,
                         "caveat": "snapshots of the " + " / ".join((s.meta.get("lists") or {"OFAC": 0}).keys()) + " public lists only, fuzzy name match on Latin script; no hit is not a clearance and a hit is a prompt to review, not a finding"}}
    if account:
        out["card"] = cn_card_check(account)
    if ifsc:
        out["ifsc"] = ifsc_check(ifsc)
    return out
