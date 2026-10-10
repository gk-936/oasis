"""Step 6 - proof packs: shareable, independently checkable evidence for one payment."""
from __future__ import annotations

from ..trust.approvals import draft_hash, verify_approval_standalone
from ..trust.audit import entry_hash
from ..trust.crypto import HybridSigner, canonical, sha256_hex, verify_hybrid
from ..trust.intents import strip_sigs
from ..trust.keystore import fingerprint


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


def verify_proof_pack(pack: dict, trusted_fingerprints=None, chain=None, approver_key_ids=None) -> dict:
    """Anyone can run this; it needs no secrets. Returns per-check results.

    A pack carries the public keys that signed it, so those keys prove nothing by themselves: a forger signs a
    modified pack with fresh keys and embeds them. `trusted_fingerprints` (a set of key fingerprints from
    `keystore.fingerprint`, obtained out of band, e.g. GET /api/trust/fingerprint or the README) pins which keys count.

    - `key_pinned`: the embedded trust keys AND pack-signing keys both have a pinned fingerprint. None = no
      fingerprint supplied, i.e. NOT checked; `ok` is then False (a standalone check can say the pack is
      self-consistent, see `consistent`, but never that it is genuine).
    - `approvals_signed`: every approval in the intent is an Ed25519 signature, by the embedded approver key, over the
      exact payment draft (payee, account, amount, currency, purpose, route, not_after, nonce). None = the intent
      carries no approvals (Tier-1 automatic payment). A role string alone can never pass.
    - `approver_keys_pinned`: with `approver_key_ids` (the key ids the server registered for its approvers, from
      GET /api/approvers, obtained out of band) each approval's key must be one of them. None = not checked. When a pack
      has approvals, `ok` additionally requires this to be True, for the same reason as `key_pinned`.
    - `anchor_on_chain`: with `chain` (an Anchor that can look blocks up: LocalAnchorChain, or FiscoAnchor whose
      `verify(digest)` reads the OasisAnchor contract) the anchor must exist with the intent hash as digest (for FISCO, in
      the block the pack names) and a local chain must be intact. None = not checked (no chain available, or
      the pack carries no anchor).
    """
    checks: dict = {}
    try:
        body = {k: v for k, v in pack.items() if k not in ("pack_signatures", "pack_public_keys")}
        checks["pack_signature"] = verify_hybrid(canonical(body), pack.get("pack_signatures", {}),
                                                 pack.get("pack_public_keys", {}))
        intent = pack["intent"]
        keys = pack.get("trust_public_keys") or {}
        checks["intent_signature"] = verify_hybrid(canonical(strip_sigs(intent)), intent.get("signatures", {}), keys)
        checks["intent_hash"] = pack["intent_hash"] == sha256_hex(canonical(strip_sigs(intent)))
        approvals = intent.get("approvals") or []
        if approvals:
            dh = draft_hash(intent)
            checks["approvals_signed"] = all(verify_approval_standalone(a, dh) for a in approvals)
        else:
            checks["approvals_signed"] = None
        e = pack["audit_entry"]
        checks["audit_entry_hash"] = entry_hash(e["i"], e["ts"], e["kind"], e["data"], e["prev"]) == e["hash"]
        anchor = pack.get("anchor")
        if anchor:
            checks["anchor_matches_intent"] = anchor["digest"] == pack["intent_hash"]
    except (KeyError, TypeError, AttributeError):
        checks["malformed"] = False
        keys, anchor = {}, None
    if trusted_fingerprints is None:
        checks["key_pinned"] = None
    else:
        trusted = set(trusted_fingerprints)
        checks["key_pinned"] = bool(keys) and fingerprint(keys) in trusted and             fingerprint(pack.get("pack_public_keys") or {}) in trusted
    approvals = (pack.get("intent") or {}).get("approvals") or [] if isinstance(pack.get("intent"), dict) else []
    if not approvals:
        checks["approver_keys_pinned"] = None
    elif approver_key_ids is None:
        checks["approver_keys_pinned"] = None
    else:
        pinned = set(approver_key_ids)
        checks["approver_keys_pinned"] = all(isinstance(a, dict) and a.get("key_id") in pinned for a in approvals)
    if chain is not None and anchor:
        blk = chain.verify(anchor.get("digest", ""))
        ok = blk is not None and blk.get("digest") == pack.get("intent_hash")
        if ok and "block_number" in anchor:
            # FISCO BCOS result shape: {tx_hash, block_number, digest, network, contract}. `verify(digest)` reads the
            # contract and returns {digest, timestamp_ms, block_number, sender, ...} (no tx hash): the anchor is on chain
            # if the contract holds this digest, in the block the pack names.
            ok = blk.get("block_number") == anchor["block_number"]
        elif ok and anchor.get("tx_hash"):
            ok = blk.get("tx_hash") == anchor["tx_hash"]
        if ok and hasattr(chain, "chain_ok"):
            ok = chain.chain_ok()
        checks["anchor_on_chain"] = bool(ok)
    else:
        checks["anchor_on_chain"] = None
    ran = {k: v for k, v in checks.items() if v is not None}
    checks["consistent"] = all(v for k, v in ran.items() if k not in ("key_pinned", "approver_keys_pinned"))
    approver_ok = checks["approver_keys_pinned"] is not False and (checks["approver_keys_pinned"] is True or not approvals)
    checks["ok"] = checks["consistent"] and checks["key_pinned"] is True and approver_ok
    return checks
