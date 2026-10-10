"""Crypto-agile signing. All signing/verification goes through the Signer interface.

Hybrid rule: a signature is accepted only if BOTH the classical and post-quantum parts verify.
"""
from __future__ import annotations
import base64
import hashlib
import json
import secrets
from abc import ABC, abstractmethod
from typing import Any

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


def canonical(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def unb64(s: str) -> bytes:
    return base64.b64decode(s)


class Signer(ABC):
    algorithm: str

    @abstractmethod
    def sign(self, message: bytes) -> bytes: ...

    @abstractmethod
    def verify(self, message: bytes, signature: bytes) -> bool: ...

    @abstractmethod
    def public_key(self) -> bytes: ...


class Ed25519Signer(Signer):
    algorithm = "ed25519"

    def __init__(self, seed: bytes | None = None, public_key: bytes | None = None):
        if public_key is not None:
            self._sk, self._vk = None, VerifyKey(public_key)
        else:
            self._sk = SigningKey(seed) if seed else SigningKey.generate()
            self._vk = self._sk.verify_key

    def sign(self, message: bytes) -> bytes:
        if self._sk is None:
            raise RuntimeError("verify-only signer")
        return self._sk.sign(message).signature

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self._vk.verify(message, signature)
            return True
        except BadSignatureError:
            return False

    def public_key(self) -> bytes:
        return bytes(self._vk)


class MLDSA65Signer(Signer):
    """ML-DSA-65 (NIST FIPS 204) via the `cryptography` package."""
    algorithm = "ml-dsa-65"

    def __init__(self, seed: bytes | None = None, public_key: bytes | None = None):
        from cryptography.hazmat.primitives.asymmetric import mldsa
        self._mldsa = mldsa
        if public_key is not None:
            self._sk = None
            self._pk = mldsa.MLDSA65PublicKey.from_public_bytes(public_key)
        else:
            self._sk = (mldsa.MLDSA65PrivateKey.from_seed_bytes(seed) if seed
                        else mldsa.MLDSA65PrivateKey.generate())
            self._pk = self._sk.public_key()

    def sign(self, message: bytes) -> bytes:
        if self._sk is None:
            raise RuntimeError("verify-only signer")
        return self._sk.sign(message)

    def verify(self, message: bytes, signature: bytes) -> bool:
        from cryptography.exceptions import InvalidSignature
        try:
            self._pk.verify(signature, message)
            return True
        except InvalidSignature:
            return False

    def public_key(self) -> bytes:
        from cryptography.hazmat.primitives import serialization as s
        return self._pk.public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)


class SM2Signer(Signer):
    """SM2 digital signature (GB/T 32918.2) with SM3, default user ID "1234567812345678".

    Backed by the pure-Python `gmssl` package (not constant-time; fine for the demo, use a
    vetted HSM/library for production). Signature = r||s (64 bytes); public key = x||y (64 bytes).
    Verified against the GB/T 32918.5 / GM/T 0003.5 Fp-256 test vector in tests/test_sm2.py.
    """
    algorithm = "sm2"
    _N = int("FFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFF7203DF6B21C6052B53BBF40939D54123", 16)

    def __init__(self, seed: bytes | None = None, public_key: bytes | None = None):
        from gmssl import sm2
        if public_key is not None:
            if len(public_key) == 65 and public_key[0] == 4:
                public_key = public_key[1:]
            if len(public_key) != 64:
                raise ValueError("SM2 public key must be 64 bytes (x||y)")
            self._d = None
            pub_hex = public_key.hex()
            priv_hex = "0" * 64
        else:
            raw = int.from_bytes(seed, "big") if seed else int.from_bytes(secrets.token_bytes(32), "big")
            d = raw % (self._N - 2) + 1          # 1 <= d <= n-2
            self._d = d
            priv_hex = f"{d:064x}"
            probe = sm2.CryptSM2(priv_hex, "0" * 128)
            pub_hex = probe._kg(d, probe.ecc_table["g"])
        self._sm2 = sm2.CryptSM2(priv_hex, pub_hex)
        # gmssl's constructor does public_key.lstrip("04"), which corrupts keys whose x starts
        # with hex 0/4; set the attribute directly.
        self._sm2.public_key = pub_hex
        self._pub = bytes.fromhex(pub_hex)

    @classmethod
    def from_private_int(cls, d: int) -> "SM2Signer":
        """Signer for an exact private scalar d (1 <= d <= n-2), e.g. a published test-vector key.

        The seed constructor maps seed -> (seed mod (n-2)) + 1, so d is reached with seed = d-1.
        """
        if not 1 <= d <= cls._N - 2:
            raise ValueError("SM2 private key out of range")
        return cls(seed=(d - 1).to_bytes(32, "big"))

    def sign_with_k(self, message: bytes, k: int) -> bytes:
        """Deterministic signature with a caller-chosen nonce k. For known-answer tests ONLY: never reuse a k."""
        if self._d is None:
            raise RuntimeError("verify-only signer")
        return bytes.fromhex(self._sm2.sign_with_sm3(message, f"{k:064x}"))

    def sign(self, message: bytes) -> bytes:
        if self._d is None:
            raise RuntimeError("verify-only signer")
        while True:
            k = f"{secrets.randbelow(self._N - 1) + 1:064x}"
            sig = self._sm2.sign_with_sm3(message, k)
            if sig:
                return bytes.fromhex(sig)

    def verify(self, message: bytes, signature: bytes) -> bool:
        if len(signature) != 64:
            return False
        r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        if not (1 <= r < self._N and 1 <= s < self._N):
            return False
        try:
            return bool(self._sm2.verify_with_sm3(signature.hex(), message))
        except Exception:
            return False

    def public_key(self) -> bytes:
        return self._pub


def sm3_hex(data: bytes | str) -> str:
    """SM3 digest (GB/T 32905) as hex."""
    from gmssl import func, sm3
    if isinstance(data, str):
        data = data.encode()
    return sm3.sm3_hash(func.bytes_to_list(data))


_VERIFIERS = {"ed25519": Ed25519Signer, "ml-dsa-65": MLDSA65Signer, "sm2": SM2Signer}


class HybridSigner:
    """Signs with several algorithms; verifies only if every listed signature is valid."""

    def __init__(self, signers: list[Signer] | None = None, key_id: str = "oasis-trust-key-1"):
        self.signers = signers or [Ed25519Signer(), MLDSA65Signer()]
        self.key_id = key_id

    def sign(self, message: bytes) -> dict[str, str]:
        return {s.algorithm: b64(s.sign(message)) for s in self.signers}

    def public_keys(self) -> dict[str, str]:
        return {s.algorithm: b64(s.public_key()) for s in self.signers}

    def verify(self, message: bytes, signatures: dict[str, str]) -> bool:
        return verify_hybrid(message, signatures, self.public_keys(),
                             required=[s.algorithm for s in self.signers])


def demo_signer(label: str, key_id: str) -> HybridSigner:
    """Seeded hybrid signer for the scripted demo ONLY: keys are public demo keys, so runs are reproducible.

    Never use for anything but the labelled demo; real deployments generate keys in a vault/HSM.
    """
    ed = hashlib.sha256(f"oasis-demo-ed25519:{label}".encode()).digest()
    pq = hashlib.sha256(f"oasis-demo-mldsa65:{label}".encode()).digest()
    return HybridSigner([Ed25519Signer(seed=ed), MLDSA65Signer(seed=pq)], key_id=key_id)


def sm2_hybrid_signer(label: str, key_id: str, replace_ed25519: bool = False) -> HybridSigner:
    """Crypto-agility demo (seeded, demo keys only): Ed25519 + ML-DSA-65 + SM2, or SM2 in place of Ed25519."""
    pq = MLDSA65Signer(seed=hashlib.sha256(f"oasis-demo-mldsa65:{label}".encode()).digest())
    sm = SM2Signer(seed=hashlib.sha256(f"oasis-demo-sm2:{label}".encode()).digest())
    if replace_ed25519:
        return HybridSigner([sm, pq], key_id=key_id)
    ed = Ed25519Signer(seed=hashlib.sha256(f"oasis-demo-ed25519:{label}".encode()).digest())
    return HybridSigner([ed, pq, sm], key_id=key_id)


def verify_hybrid(message: bytes, signatures: dict[str, str], public_keys: dict[str, str],
                  required: list[str] | None = None) -> bool:
    """Standalone verifier (anyone holding public keys can check a proof pack)."""
    required = required or sorted(public_keys)
    if not required:
        return False
    for alg in required:
        if alg not in signatures or alg not in public_keys or alg not in _VERIFIERS:
            return False
        try:
            v = _VERIFIERS[alg](public_key=unb64(public_keys[alg]))
            if not v.verify(message, unb64(signatures[alg])):
                return False
        except Exception:
            return False
    return True
