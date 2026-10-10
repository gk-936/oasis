"""Step 6 - proof packs: shareable, independently checkable evidence for one payment."""
from __future__ import annotations

from ..trust.audit import entry_hash
from ..trust.crypto import HybridSigner, canonical, sha256_hex, verify_hybrid
from ..trust.intents import strip_sigs


def build_proof_pack(*, signer: HybridSigner, intent: dict, verification: dict, costs: dict,
                     audit_entry: dict, anchor: dict | None, trust_public_keys: dict,
                     decision: dict | None = None) -> dict:
    body = {
        "version": 1,
        "intent": intent,
        "intent_hash": sha256_hex(canonical(strip_sigs(intent))),
        "verification": verification,
        "costs": costs,
        "decision": decision,
        "audit_entry": audit_entry,
        "anchor": anchor,
        "trust_public_keys": trust_public_keys,
    }
    return {**body, "pack_signatures": signer.sign(canonical(body)), "pack_public_keys": signer.public_keys()}


def verify_proof_pack(pack: dict) -> dict:
    """Anyone can run this; it needs no secrets. Returns per-check results."""
    checks: dict[str, bool] = {}
    body = {k: v for k, v in pack.items() if k not in ("pack_signatures", "pack_public_keys")}
    checks["pack_signature"] = verify_hybrid(canonical(body), pack.get("pack_signatures", {}),
                                             pack.get("pack_public_keys", {}))
    intent = pack["intent"]
    checks["intent_signature"] = verify_hybrid(canonical(strip_sigs(intent)), intent.get("signatures", {}),
                                               pack["trust_public_keys"])
    checks["intent_hash"] = pack["intent_hash"] == sha256_hex(canonical(strip_sigs(intent)))
    e = pack["audit_entry"]
    checks["audit_entry_hash"] = entry_hash(e["i"], e["ts"], e["kind"], e["data"], e["prev"]) == e["hash"]
    if pack.get("anchor"):
        checks["anchor_matches_intent"] = pack["anchor"]["digest"] == pack["intent_hash"]
    checks["ok"] = all(checks.values())
    return checks
