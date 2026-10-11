"""Payment Reliability Record: a shareable, independently checkable list of payments that completed through the full
Oasis pipeline with a verified proof pack. It is NOT a credit score and no credit bureau accepts it. It is a signed
statement from this (sandbox) server that these payments were made, with the proof pack ids a checker can look up.

What is and is not proven:
- Signed by the server's hybrid trust key (Ed25519 + ML-DSA-65); a verifier pins the key fingerprint out of band.
- Each entry names a proof pack (id + intent hash). When the verifier can fetch the pack, it re-verifies it and checks the
  entry (amount or band, date, intent hash, anchor) against it.
- 'On time' = paid date <= due date, both SIMULATED-clock dates. The due date comes from the Passport (an invoice the
  student supplied), is not inside the proof pack, and so is vouched for only by the server's signature.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from ..trust.crypto import HybridSigner, canonical, sha256_hex, verify_hybrid
from ..trust.keystore import fingerprint
from .pack import verify_proof_pack

RECORD_TYPE = "oasis.payment_reliability_record"
CST = timezone(timedelta(hours=8))
MAX_ENTRIES = 500
CAVEATS = (
    "This is a payment-reliability record from a SANDBOX: the money, payees and dates are simulated.",
    "It is not a credit score, and it is not accepted by any credit bureau.",
    "'On time' compares the simulated payment date with the due date on the invoice the student supplied; the due date "
    "is not inside the proof pack.",
    "Only payments that completed through the full Oasis pipeline with a verified proof pack are listed.",
    "Check it: pin the server key fingerprint out of band, then verify the signature and each listed proof pack.",
)
BANDS = ((1_000, "under CNY 1,000"), (5_000, "CNY 1,000 to 4,999"), (20_000, "CNY 5,000 to 19,999"),
         (50_000, "CNY 20,000 to 49,999"))
TOP_BAND = "CNY 50,000 or more"


def _norm(x):
    """JSON has one number type: 30000.0 and 30000 are the same value to a browser or any JSON tool that re-saves the record.
    Integral floats are therefore turned into ints before hashing and signing, so a downloaded record still verifies."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_norm(v) for v in x]
    return x


def _canon(x) -> bytes:
    return canonical(_norm(x))


def amount_band(amount) -> str:
    for limit, label in BANDS:
        if amount < limit:
            return label
    return TOP_BAND


def pseudonym(student_id: str, fp: str) -> str:
    """A stable pseudonymous id: it links records of one student on one server but reveals neither name nor student id."""
    return "stu_" + sha256_hex(f"{fp}|{student_id}")[:16]


def _date_of_ts(ts) -> str:
    return datetime.fromtimestamp(float(ts), CST).date().isoformat()


def _anchor_ref(anchor) -> dict | None:
    if not isinstance(anchor, dict):
        return None
    return {k: anchor[k] for k in ("digest", "tx_hash", "block_number") if k in anchor} or None


def _entry_from_pack(pack: dict, *, obligation_type, payee_type, paid_date, due_date, share_amounts) -> dict:
    intent = pack["intent"]
    e = {"obligation_type": obligation_type, "payee_type": payee_type, "paid_date": paid_date, "due_date": due_date,
         "on_time": paid_date <= due_date, "proof_id": intent["intent_id"], "intent_hash": pack["intent_hash"],
         "anchor": _anchor_ref(pack.get("anchor"))}
    if share_amounts:
        e["amount_cny"] = intent["amount"]
    else:
        e["amount_band"] = amount_band(intent["amount"])
    return e


def _summary(entries: list[dict], share_amounts: bool) -> dict:
    n = len(entries)
    on = sum(1 for e in entries if e["on_time"] is True)
    s = {"payments": n, "on_time": on, "late": n - on, "on_time_share": round(on / n, 4) if n else None}
    if share_amounts:
        s["total_cny"] = round(sum(e["amount_cny"] for e in entries), 2)
    return s


def eligible_payments(world) -> list[dict]:
    """Payments that completed the full pipeline: an executed payment against a Passport obligation, to a registry
    recipient, with a signed intent whose proof pack verifies against this server's keys. Nothing else is listed."""
    p = world.passport
    fp = world.trust_fingerprint()
    seen: set[str] = set()
    out = []
    for h in world.history:
        pid = h.get("proof_id")
        pack = world.proofs.get(pid) if pid else None
        ob = p.obligation(h.get("obligation_id")) if h.get("obligation_id") else None
        rec = p.recipients.get(h.get("payee_id"))
        if not pack or ob is None or rec is None or pid in seen:
            continue
        try:
            intent = pack["intent"]
            if intent.get("obligation_id") != ob.id or intent.get("payee_id") != rec.id or intent.get("currency") != "CNY" \
                    or abs(float(intent["amount"]) - float(h["amount_cny"])) > 0.005:
                continue
            res = verify_proof_pack(pack, {fp}, world.anchor, world.approvers.pinned_key_ids())
            if not res.get("ok"):
                continue
        except Exception:
            continue
        seen.add(pid)
        out.append({"pack": pack, "obligation_type": ob.type, "payee_type": rec.payee_type,
                    "paid_date": h["date"], "due_date": ob.due})
    return out


def build_reliability_record(world, *, include_name: bool = False, share_amounts: bool = False,
                             signer: HybridSigner | None = None) -> dict:
    signer = signer or world.signer
    keys = signer.public_keys()
    fp = fingerprint(keys)
    entries = [_entry_from_pack(x["pack"], obligation_type=x["obligation_type"], payee_type=x["payee_type"],
                                paid_date=x["paid_date"], due_date=x["due_date"], share_amounts=bool(share_amounts))
               for x in eligible_payments(world)][:MAX_ENTRIES]
    st = world.passport.student
    student = {"pseudonym": pseudonym(st.id, fp)}
    if include_name:
        student["name"] = st.name
    dates = sorted(e["paid_date"] for e in entries)
    body = {
        "version": 1, "type": RECORD_TYPE, "issued_at": world.now_iso(), "clock": "simulated",
        "student": student,
        "options": {"include_name": bool(include_name), "share_amounts": bool(share_amounts)},
        "period": {"from": dates[0] if dates else None, "to": world.today.isoformat()},
        "payments": entries, "summary": _summary(entries, bool(share_amounts)),
        "caveats": list(CAVEATS), "trust_fingerprint": fp,
    }
    body["record_hash"] = sha256_hex(_canon(body))
    return {**body, "signatures": signer.sign(_canon(body)), "public_keys": keys}


def verify_reliability_record(record, trusted_fingerprints=None, proof_lookup: Callable[[str], dict | None] | None = None,
                              pack_verifier: Callable[[dict], bool] | None = None) -> dict:
    """Never raises. Returns per-check results; `ok` needs signature, pinned key, hash and internal consistency, and (when
    proof packs are available) every listed proof. `key_pinned` None = no fingerprint supplied, so `ok` is False.
    `proofs_checked` None = no proof lookup, i.e. the entries were NOT cross-checked against their packs."""
    try:
        return _verify(record, trusted_fingerprints, proof_lookup, pack_verifier)
    except Exception:
        return {"malformed": True, "signature": False, "key_pinned": False if trusted_fingerprints is not None else None,
                "fingerprint_matches": False, "record_hash": False, "summary_consistent": False, "on_time_consistent": False,
                "proofs_checked": None, "consistent": False, "ok": False}


def _verify(record, trusted, lookup, pack_verifier) -> dict:
    c: dict = {"malformed": False}
    if not isinstance(record, dict):
        raise ValueError("not an object")
    body = {k: v for k, v in record.items() if k not in ("signatures", "public_keys")}
    keys = record.get("public_keys")
    sigs = record.get("signatures")
    if not isinstance(keys, dict) or not isinstance(sigs, dict) or record.get("type") != RECORD_TYPE:
        raise ValueError("shape")
    c["signature"] = bool(verify_hybrid(_canon(body), sigs, keys))
    fp = fingerprint(keys)
    c["fingerprint_matches"] = record.get("trust_fingerprint") == fp
    if trusted is None:
        c["key_pinned"] = None
    else:
        c["key_pinned"] = bool(keys) and fp in set(trusted)
    inner = {k: v for k, v in body.items() if k != "record_hash"}
    c["record_hash"] = record.get("record_hash") == sha256_hex(_canon(inner))
    entries = record["payments"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError("payments")
    share = bool((record.get("options") or {}).get("share_amounts"))
    c["summary_consistent"] = record.get("summary") == _summary(entries, share) if all(
        isinstance(e, dict) and (isinstance(e.get("amount_cny"), (int, float)) or not share) for e in entries) else False
    c["on_time_consistent"] = all(isinstance(e, dict) and isinstance(e.get("paid_date"), str) and isinstance(e.get("due_date"), str)
                                  and e.get("on_time") is (e["paid_date"] <= e["due_date"]) for e in entries)
    c["unique_proofs"] = len({e.get("proof_id") for e in entries}) == len(entries)
    if lookup is None:
        c["proofs_checked"] = None
    else:
        c["proofs_checked"] = all(_entry_matches_pack(e, lookup, share, pack_verifier, trusted) for e in entries)
    base = ("signature", "fingerprint_matches", "record_hash", "summary_consistent", "on_time_consistent", "unique_proofs")
    c["consistent"] = all(c[k] for k in base) and c["proofs_checked"] is not False
    c["ok"] = c["consistent"] and c["key_pinned"] is True
    return c


def _entry_matches_pack(e: dict, lookup, share: bool, pack_verifier, trusted) -> bool:
    try:
        pack = lookup(e["proof_id"])
        if not isinstance(pack, dict):
            return False
        if pack_verifier is not None:
            if not pack_verifier(pack):
                return False
        else:
            r = verify_proof_pack(pack, trusted)
            if not (r.get("consistent") and r.get("key_pinned")):
                return False
        intent = pack["intent"]
        if pack["intent_hash"] != e["intent_hash"] or intent["intent_id"] != e["proof_id"]:
            return False
        if share:
            if abs(float(intent["amount"]) - float(e["amount_cny"])) > 0.005:
                return False
        elif amount_band(intent["amount"]) != e["amount_band"]:
            return False
        if _date_of_ts(pack["audit_entry"]["ts"]) != e["paid_date"]:
            return False
        if e["on_time"] is not (e["paid_date"] <= e["due_date"]):
            return False
        return _anchor_ref(pack.get("anchor")) == e.get("anchor")
    except Exception:
        return False
