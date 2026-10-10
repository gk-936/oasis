"""Persistent trust signing keys and the public-key fingerprint that verifiers pin.

A proof pack embeds the public keys that signed it, so a pack alone proves nothing: anyone can forge a pack with
fresh keys and embed those. A verifier must therefore pin the fingerprint of the keys it trusts (published by the
server, shown in the Proof tab and the README). For that fingerprint to stay stable across restarts the server's
signing keys are generated ONCE and kept in a git-ignored key file (default data/keys/trust_key.json, override with
OASIS_TRUST_KEY). Tests pass an explicit tmp path or use in-memory keys; the scripted demo keeps its seeded, public
demo keys (see `crypto.demo_signer`) and is never trusted by a real server.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from .. import config
from .crypto import Ed25519Signer, HybridSigner, MLDSA65Signer, b64, canonical, sha256_hex, unb64

KEY_ID = "oasis-trust-key-1"


def default_key_path() -> Path:
    env = os.environ.get("OASIS_TRUST_KEY")
    return Path(env) if env else config.DATA_DIR / "keys" / "trust_key.json"


def fingerprint(public_keys: dict[str, str]) -> str:
    """sha256 over the canonical JSON of {algorithm: base64 public key}."""
    return sha256_hex(canonical({k: public_keys[k] for k in sorted(public_keys)}))


def load_or_create_signer(path: Path | str | None = None, key_id: str = KEY_ID) -> HybridSigner:
    """The server's hybrid (Ed25519 + ML-DSA-65) signer, created on first use and reloaded afterwards.

    The file holds private seeds: it is git-ignored, written owner-only where the OS supports it, and must never be
    committed or logged."""
    p = Path(path) if path else default_key_path()
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        signer = HybridSigner([Ed25519Signer(seed=unb64(d["ed25519_seed"])),
                               MLDSA65Signer(seed=unb64(d["ml-dsa-65_seed"]))], key_id=d.get("key_id", key_id))
        if "fingerprint" in d and d["fingerprint"] != fingerprint(signer.public_keys()):
            raise ValueError(f"trust key file {p} is inconsistent (fingerprint mismatch)")
        return signer
    ed_seed, pq_seed = os.urandom(32), os.urandom(32)
    signer = HybridSigner([Ed25519Signer(seed=ed_seed), MLDSA65Signer(seed=pq_seed)], key_id=key_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key_id": key_id, "ed25519_seed": b64(ed_seed), "ml-dsa-65_seed": b64(pq_seed),
                             "fingerprint": fingerprint(signer.public_keys())}, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return signer
