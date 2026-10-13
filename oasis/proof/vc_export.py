"""W3C Verifiable Credentials Data Model 1.1 export of the Oasis Trust Pass (an ADDITIONAL format; the native one is unchanged).

See docs/w3c-vc.md for exactly what is and is not spec-conformant. In short: the envelope, did:key identifiers and
multibase signatures follow the specs, but the proof is computed over Oasis sorted-key canonical JSON, not RDF
Dataset Canonicalization, so a stock Ed25519Signature2020 verifier will not accept it. `verify_vc` here does.
"""
from __future__ import annotations

import hashlib

from nacl.signing import SigningKey

from ..trust.crypto import Ed25519Signer, HybridSigner, canonical, unb64, verify_hybrid

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ED25519_MULTICODEC = b"\xed\x01"
VC_CONTEXT = ["https://www.w3.org/2018/credentials/v1", "https://w3id.org/security/suites/ed25519-2020/v1",
              {"@vocab": "https://oasis.example/vocab#"}]
PROOF_CANON = "oasis-sorted-json-v1"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)          # ValueError on a bad character
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def did_key(ed25519_public: bytes) -> str:
    return "did:key:z" + b58encode(_ED25519_MULTICODEC + ed25519_public)


def did_key_public(did: str) -> bytes:
    if not isinstance(did, str) or not did.startswith("did:key:z"):
        raise ValueError("not a did:key")
    raw = b58decode(did[9:])
    if raw[:2] != _ED25519_MULTICODEC or len(raw) != 34:
        raise ValueError("not an Ed25519 did:key")
    return raw[2:]


def holder_did(pseudonym: str) -> str:
    """Pseudonymous holder DID derived from the Trust Pass subject pseudonym. The seed is public, so it names the
    subject but proves no possession of a key."""
    seed = hashlib.sha256(b"oasis-holder-did:" + pseudonym.encode()).digest()
    return did_key(bytes(SigningKey(seed).verify_key))


def _ed(signer: HybridSigner) -> Ed25519Signer:
    for s in signer.signers:
        if isinstance(s, Ed25519Signer):
            return s
    raise ValueError("signer has no Ed25519 key")


def _vm(did: str) -> str:
    return f"{did}#{did[8:]}"


def export_vc(holder: dict, signer: HybridSigner) -> dict:
    """holder: output of trust_pass.issue. Only the credential is exported: no salts, no ZK openings."""
    cred = holder["credential"]
    ed = _ed(signer)
    issuer = did_key(ed.public_key())
    issued = cred["issued_at"] if "T" in cred["issued_at"] else cred["valid_from"] + "T00:00:00Z"
    issued = issued.replace("+00:00", "Z")
    vc = {
        "@context": VC_CONTEXT,
        "id": f"urn:oasis:trust-pass:{cred['credential_hash']}",
        "type": ["VerifiableCredential", "OasisTrustPass"],
        "issuer": issuer,
        "issuanceDate": issued,
        "expirationDate": cred["valid_until"] + "T00:00:00Z",
        "credentialSubject": {
            "id": holder_did(cred["subject"]["pseudonym"]),
            "audience": cred.get("audience"),
            "claims": cred["claims"],
            "paymentCommitments": cred["commitments"],
            "zkCommitments": cred.get("zk"),
        },
        "evidence": [{"type": "OasisNativeCredential", "credential": cred}],
    }
    proof = {"type": "Ed25519Signature2020", "created": issued, "verificationMethod": _vm(issuer),
             "proofPurpose": "assertionMethod", "canonicalization": PROOF_CANON}
    proof["proofValue"] = "z" + b58encode(ed.sign(canonical({**vc, "proof": {k: v for k, v in proof.items()}})))
    return {**vc, "proof": proof}


def verify_vc(vc, trusted_fingerprints: set[str] | None = None) -> dict:
    """Checks the proof against the issuer's did:key, then the embedded native credential (hybrid signatures, same
    claims/commitments/issuer key). With trusted_fingerprints, also pins the issuer key set. Never raises."""
    checks: dict[str, bool] = {}
    try:
        proof = vc["proof"]
        opts = {k: v for k, v in proof.items() if k != "proofValue"}
        body = {**{k: v for k, v in vc.items() if k != "proof"}, "proof": opts}
        pub = did_key_public(vc["issuer"])
        checks["types"] = vc["type"] == ["VerifiableCredential", "OasisTrustPass"]
        checks["proof_ed25519"] = (proof["type"] == "Ed25519Signature2020" and proof["verificationMethod"] == _vm(vc["issuer"])
                                   and proof["proofValue"].startswith("z")
                                   and Ed25519Signer(public_key=pub).verify(canonical(body), b58decode(proof["proofValue"][1:])))
        cred = vc["evidence"][0]["credential"]
        keys = cred["public_keys"]
        nat = {k: v for k, v in cred.items() if k not in ("signatures", "public_keys")}
        checks["native_signatures"] = verify_hybrid(canonical(nat), cred["signatures"], keys)
        checks["issuer_matches_native_key"] = unb64(keys["ed25519"]) == pub
        s = vc["credentialSubject"]
        checks["subject_matches_native"] = (s["claims"] == cred["claims"] and s["paymentCommitments"] == cred["commitments"]
                                            and s.get("zkCommitments") == cred.get("zk") and s.get("audience") == cred.get("audience")
                                            and s["id"] == holder_did(cred["subject"]["pseudonym"])
                                            and vc["id"] == f"urn:oasis:trust-pass:{cred['credential_hash']}")
        if trusted_fingerprints is not None:
            checks["key_pinned"] = cred.get("trust_fingerprint") in trusted_fingerprints
    except Exception:
        checks["well_formed"] = False
        return {"ok": False, "checks": checks}
    return {"ok": all(checks.values()), "checks": checks}


def import_vc(vc, trusted_fingerprints: set[str] | None = None) -> dict:
    """Round trip back to the native credential. Raises ValueError unless verify_vc passes."""
    res = verify_vc(vc, trusted_fingerprints)
    if not res["ok"]:
        raise ValueError("invalid Verifiable Credential: " + ", ".join(k for k, v in res["checks"].items() if not v))
    return vc["evidence"][0]["credential"]
