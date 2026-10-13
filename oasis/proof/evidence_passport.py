"""Payment Evidence Passport: one signed, QR-verifiable bundle proving 'this payment was paid to this registry-verified payee,
and it arrived'. It reuses, never replaces, the existing pieces:

- the proof pack (signed intent, approvals, audit entry, anchor)           -> `proof.pack.verify_proof_pack`
- the registry credential binding the payee to the account                  -> `mock.registry` (MOCK issuer)
- the FlightPath journey and its reconciliation result (credited/short/delayed) -> `flightpath.core.reconcile` (MOCK rail)
- an audit-chain inclusion proof: the hash-linked entries from the payment's entry to the chain head -> `trust.audit`

Everything is signed with the server's hybrid key (Ed25519 + ML-DSA-65). The verifier needs no login and no secrets and
re-runs every check from the bundle itself; only the pins (server key, registry issuer key) come from outside.
Not a bank statement and not proof of receipt by a real bank: the rail, registry and clock are simulated."""
from __future__ import annotations

from ..flightpath import core as fp
from ..mock.rates import ROUTES
from ..trust.audit import entry_hash
from ..trust.crypto import HybridSigner, sha256_hex, verify_hybrid
from ..trust.keystore import fingerprint
from .pack import verify_proof_pack
from .reliability import _canon

TYPE = "oasis.evidence_passport"
OUTCOMES = ("credited", "short", "delayed")
MAX_SEGMENT = 500
CAVEATS = ("SANDBOX: money, registry, payment rail and clock are simulated (MOCK).",
           "The reconciliation result comes from the simulated FlightPath rail, not from a real receiving bank.",
           "Check it: pin the server key and registry issuer fingerprints out of band, then verify every signature.")


def simulate_journey(intent: dict, outcome: str, credited_cny: float | None = None) -> fp.Journey:
    """MOCK rail: drives a FlightPath journey for an executed payment to the chosen outcome."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {list(OUTCOMES)}")
    need = float(intent["amount"])
    rid = intent.get("route_id")
    j = fp.Journey(f"jr_{intent['intent_id']}", rid if rid in {r.id for r in ROUTES} else "route_inr_cny_2", 0.0, need)
    fp.advance(j, "checks_complete", 0)
    fp.advance(j, "submitted", 0)
    fp.advance(j, "processing", 1)
    if outcome == "delayed":
        fp.advance(j, "delayed", 2, reason="provider reported a delay (MOCK)")
        return j
    got = need if outcome == "credited" else (credited_cny if credited_cny is not None else need - 50.0)
    if outcome == "short" and not (0 <= got < need - fp.SHORT_TOLERANCE_CNY):
        raise ValueError("a short credit must be below the required amount")
    fp.advance(j, "credited", 2, credited_cny=round(got, 2))
    return j


def _journey_dict(j: fp.Journey) -> dict:
    return {"id": j.id, "route_id": j.route_id, "send_inr": j.send_inr, "required_cny": j.required_cny, "stage": j.stage,
            "submitted_day": j.submitted_day, "credited_cny": j.credited_cny, "history": j.history}


def _journey_from(d: dict) -> fp.Journey:
    return fp.Journey(d["id"], d["route_id"], d["send_inr"], d["required_cny"], None, d["stage"], d["submitted_day"],
                      d["credited_cny"], False, d["history"])


def status_of(f: fp.Finding, j: fp.Journey) -> str:
    return {"shortfall": "short", "delayed": "delayed", "rejected": "rejected"}.get(
        f.code, "credited" if j.stage == "credited" else "pending")


def _segment(world, entry: dict) -> list[dict]:
    es = world.audit.entries
    i = entry["i"]
    if i >= len(es) or es[i]["hash"] != entry["hash"]:
        raise ValueError("the payment's audit entry is not on this server's chain")
    return es[i:i + MAX_SEGMENT]


def issue(world, intent_id: str, outcome: str = "credited", credited_cny: float | None = None,
          today_day: int | None = None, signer: HybridSigner | None = None) -> dict:
    """Raises KeyError (no such executed payment) or ValueError. The reconciliation is MOCK-simulated."""
    pack = world.proofs.get(intent_id)
    if not pack:
        raise KeyError(intent_id)
    intent = pack["intent"]
    cred = world.registry.lookup(intent.get("payee_id"))
    if cred is None or cred.account_ref != intent.get("account_ref"):
        raise ValueError("payee is not registry-verified for this account")
    j = simulate_journey(intent, outcome, credited_cny)
    day = today_day if today_day is not None else 2
    f = fp.reconcile(j, day)
    signer = signer or world.signer
    keys = signer.public_keys()
    seg = _segment(world, pack["audit_entry"])
    body = {
        "version": 1, "type": TYPE, "issued_at": world.now_iso(), "clock": "simulated", "mock_rail": True,
        "claim": {"intent_id": intent_id, "amount": intent["amount"], "currency": intent["currency"],
                  "payee_id": intent["payee_id"], "status": status_of(f, j)},
        "proof_pack": pack,
        "payee_credential": {**cred.body(), "signatures": cred.signatures, "issuer_public_keys": world.registry.issuer_public_keys()},
        "reconciliation": {"journey": _journey_dict(j), "today_day": day,
                           "finding": {"code": f.code, "detail": f.detail, "shortfall_cny": f.shortfall_cny}},
        "audit_inclusion": {"segment": seg, "head": seg[-1]["hash"], "chain_length": len(world.audit.entries)},
        "caveats": list(CAVEATS), "trust_fingerprint": fingerprint(keys),
    }
    body["passport_hash"] = sha256_hex(_canon(body))
    world.audit.append("evidence_passport_issued", {"intent_id": intent_id, "passport_hash": body["passport_hash"],
                                                    "status": body["claim"]["status"]})
    return {**body, "signatures": signer.sign(_canon(body)), "public_keys": keys}


def verify(p, trusted=None, trusted_registry=None, approver_key_ids=None, chain=None, head_known=None) -> dict:
    """Never raises. `ok` needs every offline check AND the server key and registry issuer key pinned.
    `head_known(index, hash)` optionally confirms online that the chain head is on the server's own chain."""
    try:
        return _verify(p, trusted, trusted_registry, approver_key_ids, chain, head_known)
    except Exception:
        return {"malformed": True, "ok": False, "consistent": False, "signature": False}


def _verify(p, trusted, trusted_reg, approvers, chain, head_known) -> dict:
    if not isinstance(p, dict) or p.get("type") != TYPE:
        raise ValueError("shape")
    body = {k: v for k, v in p.items() if k not in ("signatures", "public_keys")}
    keys = p["public_keys"]
    c: dict = {"malformed": False}
    c["signature"] = bool(verify_hybrid(_canon(body), p["signatures"], keys))
    c["passport_hash"] = p.get("passport_hash") == sha256_hex(_canon({k: v for k, v in body.items() if k != "passport_hash"}))
    fpr = fingerprint(keys)
    c["fingerprint_matches"] = p.get("trust_fingerprint") == fpr
    c["key_pinned"] = None if trusted is None else bool(keys) and fpr in set(trusted)
    pack = p["proof_pack"]
    intent = pack["intent"]
    pr = verify_proof_pack(pack, trusted, chain, approvers)
    c["proof_pack"] = bool(pr.get("consistent"))
    c["pack_key_pinned"] = pr.get("key_pinned")
    c["approvals_signed"] = pr.get("approvals_signed")
    cl = p["claim"]
    c["claim_matches_intent"] = (cl["intent_id"] == intent["intent_id"] and cl["payee_id"] == intent["payee_id"]
                                 and cl["amount"] == intent["amount"] and cl["currency"] == intent["currency"])
    cr = p["payee_credential"]
    cbody = {k: cr[k] for k in ("payee_id", "name", "payee_type", "account_ref", "issued_at")}
    c["payee_credential"] = bool(verify_hybrid(_canon(cbody), cr["signatures"], cr["issuer_public_keys"]))
    c["payee_bound"] = cr["payee_id"] == intent["payee_id"] and cr["account_ref"] == intent["account_ref"]
    c["registry_pinned"] = None if trusted_reg is None else fingerprint(cr["issuer_public_keys"]) in set(trusted_reg)
    # the reconciliation is recomputed from the journey, never taken from the stated finding
    rc = p["reconciliation"]
    j = _journey_from(rc["journey"])
    f = fp.reconcile(j, rc["today_day"])
    c["reconciliation_recomputed"] = (f.code == rc["finding"]["code"] and abs(f.shortfall_cny - rc["finding"]["shortfall_cny"]) < 0.005
                                      and status_of(f, j) == cl["status"] and j.required_cny == float(intent["amount"]))
    seg = p["audit_inclusion"]["segment"]
    ok_chain = bool(seg) and len(seg) <= MAX_SEGMENT and seg[0] == pack["audit_entry"]
    for a, b in zip(seg, seg[1:]):
        ok_chain = ok_chain and b["prev"] == a["hash"] and b["i"] == a["i"] + 1
    ok_chain = ok_chain and all(entry_hash(e["i"], e["ts"], e["kind"], e["data"], e["prev"]) == e["hash"] for e in seg)
    c["audit_chain_linked"] = bool(ok_chain) and p["audit_inclusion"]["head"] == seg[-1]["hash"]
    first = seg[0]
    c["payment_in_chain"] = (first["kind"] == "transfer_executed" and first["data"].get("intent_id") == intent["intent_id"]
                             and first["data"].get("to") == intent["account_ref"])
    c["head_on_server_chain"] = None if head_known is None else bool(head_known(seg[-1]["i"], seg[-1]["hash"]))
    c["status"] = cl["status"]
    c["claim"] = cl
    c["payee"] = {k: cr[k] for k in ("payee_id", "name", "payee_type")}
    c["finding"] = rc["finding"]
    c["audit_head"] = seg[-1]["hash"]
    c["issued_at"] = p.get("issued_at")
    base = ("signature", "passport_hash", "fingerprint_matches", "proof_pack", "claim_matches_intent", "payee_credential",
            "payee_bound", "reconciliation_recomputed", "audit_chain_linked", "payment_in_chain")
    c["consistent"] = all(c[k] for k in base) and c["approvals_signed"] is not False and c["head_on_server_chain"] is not False
    c["ok"] = c["consistent"] and c["key_pinned"] is True and c["pack_key_pinned"] is True and c["registry_pinned"] is True
    return c
