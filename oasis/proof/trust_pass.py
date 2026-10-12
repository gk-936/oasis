"""Oasis Trust Pass: a portable, selectively disclosable payment-reputation credential the student holds.

Credit history stops at the border, and most students have none to carry anyway: no card, no loan, no bureau file. The
Trust Pass builds a NEW record from day one, out of the tuition and rent payments that completed the full Oasis pipeline
(the same set as the Payment Reliability Record), and lets the student show it to a landlord, bank or university.

What makes it different from carrying a bureau report across borders:
- It needs no prior credit file: it is built from payments Oasis itself executed and proved.
- Every payment went to a REGISTRY-VERIFIED payee (a real university or landlord, never an account typed from a document),
  so the history cannot be padded by "paying rent" to a friend. The `verified_payees` claim states this.
- The student holds it and chooses what to show: exact claims, threshold claims ("at least 90% on time") that hide the
  exact numbers, and which individual payments (if any) to reveal.
- Anyone can check it without trusting Oasis's word: signatures (hybrid Ed25519 + ML-DSA-65) verify against a pinned key.

Mechanics (SD-JWT-style salted commitments):
- Claims are computed by the server from verified proof packs, never typed in by the student.
- Each eligible payment is committed to as sha256(salt | entry); only the digests are signed. The student keeps the salts.
- A PRESENTATION is the signed credential plus only the payments the student chooses to reveal. The verifier checks each
  revealed payment against a signed digest (and its proof pack) and learns nothing about the hidden ones but their count.
- An optional audience ("Landlord, Room 1203") is inside the signature, and the credential expires after VALID_DAYS.

- Zero-knowledge thresholds (`zk.py`): the signed credential also holds Pedersen commitments to the on-time and total payment counts.
  At presentation time the holder can prove ANY threshold ("at least 94% on time", "at least 5 payments") without revealing the
  counts, and without the issuer having pre-signed that threshold. The proof is bound to this credential and audience.

It is NOT a credit score and no credit bureau accepts it. It is evidence for a concrete request (a lower deposit, no
guarantor, a first student card); see `suggested_asks`.
"""
from __future__ import annotations

import secrets
from datetime import date, timedelta

from ..trust.crypto import HybridSigner, sha256_hex, verify_hybrid
from . import zk
from ..trust.keystore import fingerprint
from .reliability import _canon, _entry_from_pack, _entry_matches_pack, amount_band, eligible_payments, pseudonym

CREDENTIAL_TYPE = "oasis.trust_pass"
VALID_DAYS = 90
MAX_AUDIENCE = 80
EXACT_CLAIMS = ("on_time_all", "verified_payees", "on_time_streak", "rent_on_time", "tuition_on_time", "history_months",
                "no_late", "volume_band")
# Threshold claims reveal only "at least N"; the allowed N are fixed so the choice itself leaks little.
THRESHOLDS = {"on_time_pct_min": (80, 90, 100), "history_months_min": (1, 3, 6, 12), "payments_min": (2, 3, 6, 12)}
CLAIMS = EXACT_CLAIMS + tuple(THRESHOLDS)
UNVERIFIED_LEVELS = ("unverified", "rejected")
CAVEATS = (
    "SANDBOX credential: the money, payees and dates are simulated.",
    "It is not a credit score, and it is not accepted by any credit bureau.",
    "Claims are computed by the issuing server from payments with verified proof packs; hidden payments are only counted.",
    "Check it: pin the server key fingerprint out of band, then verify the signature, the expiry and each revealed payment.",
)
# Earned autonomy: the parent co-approval threshold (INR) a clean on-time record earns. Proposed, never applied without the parent.
LADDER = ((0, 50_000), (2, 75_000), (4, 100_000), (8, 150_000))
MAX_SHARES = 200


# ------------------------------------------------------------------ claims
def _entries(world) -> list[dict]:
    out = []
    for x in eligible_payments(world):
        e = _entry_from_pack(x["pack"], obligation_type=x["obligation_type"], payee_type=x["payee_type"],
                             paid_date=x["paid_date"], due_date=x["due_date"], share_amounts=True)
        e["payee_level"] = x.get("payee_level")
        out.append(e)
    return out


def _months(a: str, b: str) -> int:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    return max(0, (db.year - da.year) * 12 + db.month - da.month)


def _ratio(es: list[dict]) -> dict:
    return {"on_time": sum(1 for e in es if e["on_time"]), "of": len(es)}


def compute_claims(entries: list[dict], today: str) -> dict[str, dict]:
    """Exact claim values. Threshold claims are derived from these in `threshold_options`."""
    es = sorted(entries, key=lambda e: e["paid_date"])
    streak = 0
    for e in reversed(es):
        if not e["on_time"]:
            break
        streak += 1
    total = round(sum(e["amount_cny"] for e in es), 2)
    return {
        "on_time_all": _ratio(es),
        "verified_payees": {"verified": sum(1 for e in es if e.get("payee_level") not in UNVERIFIED_LEVELS), "of": len(es)},
        "on_time_streak": {"count": streak},
        "rent_on_time": _ratio([e for e in es if e["obligation_type"] == "rent"]),
        "tuition_on_time": _ratio([e for e in es if e["obligation_type"] == "tuition"]),
        "history_months": {"months": _months(es[0]["paid_date"], today) if es else 0},
        "no_late": {"value": bool(es) and all(e["on_time"] for e in es)},
        "volume_band": {"band": amount_band(total) if es else None},
    }


def _actual(cid: str, c: dict) -> float:
    a = c["on_time_all"]
    return {"on_time_pct_min": (100 * a["on_time"] / a["of"]) if a["of"] else 0.0,
            "history_months_min": c["history_months"]["months"], "payments_min": a["of"]}[cid]


def threshold_options(c: dict) -> dict[str, list[dict]]:
    """For each threshold claim, the allowed values and whether this record meets them."""
    return {cid: [{"at_least": n, "met": _actual(cid, c) >= n} for n in opts] for cid, opts in THRESHOLDS.items()}


def statement(cid: str, v: dict) -> str:
    """English sentence for a claim (the UI renders its own translation from the id and value)."""
    return {
        "on_time_all": lambda: f"{v['on_time']} of {v['of']} verified payments were paid on time",
        "verified_payees": lambda: f"{v['verified']} of {v['of']} payments went to registry-verified payees",
        "on_time_streak": lambda: f"{v['count']} on-time payments in a row, most recent first",
        "rent_on_time": lambda: f"Rent paid on time {v['on_time']} of {v['of']} times",
        "tuition_on_time": lambda: f"Tuition paid on time {v['on_time']} of {v['of']} times",
        "history_months": lambda: f"{v['months']} months of verified payment history",
        "no_late": lambda: "No late payments" if v["value"] else "At least one late payment",
        "volume_band": lambda: f"Total verified payments: {v['band']}",
        "on_time_pct_min": lambda: f"At least {v['at_least']}% of verified payments were paid on time",
        "history_months_min": lambda: f"At least {v['at_least']} months of verified payment history",
        "payments_min": lambda: f"At least {v['at_least']} verified payments",
    }[cid]()


def suggested_asks(claims: dict[str, dict]) -> list[str]:
    """Concrete things this record can support asking for. Ids only; never a promise that anyone will agree."""
    asks = []
    r, t, a = claims["rent_on_time"], claims["tuition_on_time"], claims["on_time_all"]
    if r["of"] >= 1 and r["on_time"] == r["of"]:
        asks.append("lower_deposit")
    if t["of"] >= 1 and t["on_time"] == t["of"]:
        asks.append("no_guarantor")
    if a["of"] >= 3 and claims["no_late"]["value"]:
        asks.append("student_card")
    if claims["history_months"]["months"] >= 6:
        asks.append("home_bank")
    return asks


def ladder(world) -> dict:
    """Earned autonomy: a clean record proposes a higher parent co-approval threshold. Any late payment resets the level."""
    c = compute_claims(_entries(world), world.today.isoformat())
    clean = c["on_time_streak"]["count"]
    level = max(i for i, (need, _) in enumerate(LADDER) if clean >= need)
    earned = LADDER[level][1]
    current = world.passport.rules.parent_coapproval_above_inr
    nxt = LADDER[level + 1] if level + 1 < len(LADDER) else None
    return {"level": level, "streak": clean, "earned_threshold_inr": earned, "current_threshold_inr": current,
            "proposal": earned > current,
            "next": {"needs_streak": nxt[0], "threshold_inr": nxt[1]} if nxt else None,
            "levels": [{"level": i, "needs_streak": n, "threshold_inr": th} for i, (n, th) in enumerate(LADDER)]}


def accept_ladder(world) -> dict:
    """Parent accepts the proposal. Raises ValueError when there is nothing to accept."""
    lv = ladder(world)
    if not lv["proposal"]:
        raise ValueError("no higher threshold has been earned")
    old = world.passport.rules.parent_coapproval_above_inr
    world.passport.rules.parent_coapproval_above_inr = lv["earned_threshold_inr"]
    world.audit.append("autonomy_level_raised", {"level": lv["level"], "from_inr": old, "to_inr": lv["earned_threshold_inr"],
                                                "streak": lv["streak"]})
    return ladder(world)


# ------------------------------------------------------------------ issue / present
def _digest(d: dict) -> str:
    return sha256_hex(_canon({"salt": d["salt"], "entry": d["entry"]}))


def issue(world, claim_ids, audience: str | None = None, thresholds: dict | None = None,
          signer: HybridSigner | None = None) -> dict:
    """The holder copy: {"credential": signed, "disclosures": [{salt, entry}, ...]}. Keep the disclosures private.
    Threshold claims need a value from THRESHOLDS in `thresholds` and are refused (ValueError) if the record misses it."""
    want = set(claim_ids or ())
    ids = [c for c in CLAIMS if c in want]
    if not ids:
        raise ValueError("choose at least one claim")
    thresholds = thresholds or {}
    aud = (audience or "").strip()[:MAX_AUDIENCE] or None
    signer = signer or world.signer
    keys = signer.public_keys()
    fp = fingerprint(keys)
    entries = _entries(world)
    today = world.today
    exact = compute_claims(entries, today.isoformat())
    claims = []
    for c in ids:
        if c in THRESHOLDS:
            n = thresholds.get(c)
            if n not in THRESHOLDS[c]:
                raise ValueError(f"{c} needs one of {list(THRESHOLDS[c])}")
            if _actual(c, exact) < n:
                raise ValueError(f"the record does not meet {c} >= {n}")
            v = {"at_least": n}
        else:
            v = exact[c]
        claims.append({"id": c, "value": v, "statement": statement(c, v)})
    disclosures = [{"salt": secrets.token_hex(16), "entry": e} for e in entries]
    zk_pub = zk_priv = None
    if entries:
        zk_pub, zk_priv = zk.commit_counts(sum(1 for e in entries if e["on_time"]), len(entries))
    body = {
        "version": 1, "type": CREDENTIAL_TYPE, "issued_at": world.now_iso(), "clock": "simulated",
        "valid_from": today.isoformat(), "valid_until": (today + timedelta(days=VALID_DAYS)).isoformat(),
        "subject": {"pseudonym": pseudonym(world.passport.student.id, fp)}, "audience": aud,
        "claims": claims,
        "commitments": sorted(_digest(d) for d in disclosures), "zk": zk_pub,
        "caveats": list(CAVEATS), "trust_fingerprint": fp,
    }
    body["credential_hash"] = sha256_hex(_canon(body))
    cred = {**body, "signatures": signer.sign(_canon(body)), "public_keys": keys}
    world.audit.append("trust_pass_issued", {"credential_hash": body["credential_hash"], "claims": ids,
                                            "payments": len(entries), "audience_set": aud is not None})
    return {"credential": cred, "disclosures": disclosures, "zk_openings": zk_priv, "suggested_asks": suggested_asks(exact)}


MAX_ZK_PROOFS = 6


def _zk_ctx(cred: dict) -> bytes:
    return f"{cred.get('credential_hash')}|{cred.get('audience') or ''}".encode()


def zk_statement(kind: str, k: int) -> str:
    return (f"At least {k}% of payments were on time (proved without revealing the counts)" if kind == "rate"
            else f"At least {k} payments (proved without revealing the exact number)")


def zk_prove(credential: dict, openings: dict, kind: str, k: int) -> dict:
    """Holder side: one zero-knowledge threshold claim for this credential and audience. Raises ValueError if the record does
    not meet it (an honest prover cannot prove a false statement), or if the openings do not match the signed commitments."""
    pub = credential.get("zk")
    if not pub or not isinstance(openings, dict):
        raise ValueError("this Trust Pass has no committed counts (issue a new one after at least one payment)")
    try:
        if zk.commit(int(openings["on"]), int(openings["r_on"], 16)).hex() != pub["c_on"] or                 zk.commit(int(openings["tot"]), int(openings["r_tot"], 16)).hex() != pub["c_tot"]:
            raise ValueError("the private openings do not match this credential")
        if kind == "rate":
            c = zk.prove_rate(pub, openings, int(k), _zk_ctx(credential))
        elif kind == "count":
            c = zk.prove_count(pub, openings, int(k), _zk_ctx(credential))
        else:
            raise ValueError("kind must be 'rate' or 'count'")
    except (KeyError, TypeError) as e:
        raise ValueError("malformed openings") from e
    return c


def present(holder: dict, reveal: list[int] | None = None, zk_proofs: list[dict] | None = None) -> dict:
    ds = holder["disclosures"]
    picked = sorted({i for i in (reveal or []) if isinstance(i, int) and 0 <= i < len(ds)})
    out = {"credential": holder["credential"], "disclosures": [ds[i] for i in picked]}
    if zk_proofs:
        out["zk_proofs"] = list(zk_proofs)[:MAX_ZK_PROOFS]
    return out


# ------------------------------------------------------------------ share codes (for the QR / public verify page)
def share(store: dict, pres: dict, today: str) -> str:
    """Keep a presentation under a short unguessable code so a verifier can scan a QR instead of pasting JSON. The code
    only LOCATES the presentation; the verify page still checks every signature. Expired shares are dropped first."""
    for k in [k for k, v in store.items() if v["valid_until"] < today]:
        del store[k]
    while len(store) >= MAX_SHARES:
        store.pop(next(iter(store)))
    code = secrets.token_urlsafe(9)
    store[code] = {"presentation": pres, "valid_until": pres["credential"]["valid_until"]}
    return code


# ------------------------------------------------------------------ verify
def verify_presentation(pres, trusted_fingerprints=None, today: str | None = None, proof_lookup=None,
                        pack_verifier=None) -> dict:
    """Never raises. `ok` needs a valid signature from a pinned key, an intact hash, an unexpired credential and every
    revealed payment matching a signed commitment (and its proof pack, when a lookup is given)."""
    try:
        return _verify(pres, trusted_fingerprints, today, proof_lookup, pack_verifier)
    except Exception:
        return {"malformed": True, "signature": False, "key_pinned": False if trusted_fingerprints is not None else None,
                "credential_hash": False, "fingerprint_matches": False, "not_expired": False, "disclosures_valid": False,
                "proofs_checked": None, "zk_claims": [], "zk_valid": False, "claims": [], "revealed": [], "hidden": None, "ok": False}


def _verify(pres, trusted, today, lookup, pack_verifier) -> dict:
    cred = pres["credential"]
    if not isinstance(cred, dict) or cred.get("type") != CREDENTIAL_TYPE:
        raise ValueError("shape")
    body = {k: v for k, v in cred.items() if k not in ("signatures", "public_keys")}
    keys, sigs = cred["public_keys"], cred["signatures"]
    c: dict = {"malformed": False}
    c["signature"] = bool(verify_hybrid(_canon(body), sigs, keys))
    fp = fingerprint(keys)
    c["fingerprint_matches"] = cred.get("trust_fingerprint") == fp
    c["key_pinned"] = None if trusted is None else (bool(keys) and fp in set(trusted))
    inner = {k: v for k, v in body.items() if k != "credential_hash"}
    c["credential_hash"] = cred.get("credential_hash") == sha256_hex(_canon(inner))
    c["not_expired"] = True if today is None else cred["valid_from"] <= today <= cred["valid_until"]
    commits = set(cred["commitments"])
    ds = pres.get("disclosures") or []
    if not isinstance(ds, list) or len(ds) > len(commits):
        raise ValueError("disclosures")
    digests = [_digest(d) for d in ds]
    c["disclosures_valid"] = len(set(digests)) == len(digests) and all(
        dg in commits and d["entry"]["on_time"] is (d["entry"]["paid_date"] <= d["entry"]["due_date"])
        for dg, d in zip(digests, ds))
    if lookup is None or not ds:
        c["proofs_checked"] = None
    else:
        c["proofs_checked"] = all(_entry_matches_pack(d["entry"], lookup, True, pack_verifier, trusted) for d in ds)
    zp = pres.get("zk_proofs") or []
    if not isinstance(zp, list) or len(zp) > MAX_ZK_PROOFS:
        raise ValueError("zk_proofs")
    c["zk_claims"] = [{"kind": z.get("kind"), "k": z.get("k"),
                       "statement": zk_statement(z.get("kind"), int(z.get("k"))) if z.get("kind") in ("rate", "count") else "unreadable",
                       "verified": bool(cred.get("zk")) and zk.verify_claim(cred["zk"], z, _zk_ctx(cred))} for z in zp]
    c["zk_valid"] = all(z["verified"] for z in c["zk_claims"])
    c["claims"] = [{"id": x["id"], "value": x["value"], "statement": x["statement"]} for x in cred["claims"]]
    c["revealed"] = [d["entry"] for d in ds]
    c["hidden"] = len(commits) - len(ds)
    c["audience"] = cred.get("audience")
    c["valid_until"] = cred.get("valid_until")
    base = ("signature", "fingerprint_matches", "credential_hash", "not_expired", "disclosures_valid")
    c["consistent"] = all(c[k] for k in base) and c["proofs_checked"] is not False and c["zk_valid"]
    c["ok"] = c["consistent"] and c["key_pinned"] is True
    return c
