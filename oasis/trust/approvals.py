"""Signed human approvals (Ed25519 device keys).

An approval is NOT a role string. It is a signature, made with the approver's device key, over the exact payment
draft: payee, account, amount, currency, purpose, route, not_after and nonce. The draft hash binds the approval to
that one payment: change any field (or the nonce) and the signature no longer verifies.

    message = "oasis-approval-v1|<role>|<draft_hash>"        signature = Ed25519(device_private_key, message)

Where the private keys live:
- Real approvers (API): the private key is generated in the approver's BROWSER on first login and never leaves it
  (see frontend/src/crypto.js); the server only ever holds the public key, registered per role in the
  `ApproverRegistry`. A stolen database or a compromised server cannot forge an approval.
- Sandbox worlds (benchmark, scripted demo, red-team console, unit tests): the "humans" are simulated in-process, so a
  `SimDevices` object holds their keys. It exists only in worlds that have no real human, never in the API's main world.

The policy engine and the executor accept a role's approval only if its signature verifies against that role's
registered public key. `verify_proof_pack` re-checks the signatures offline against pinned approver key ids.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from .crypto import b64, canonical, sha256_hex, unb64

DRAFT_FIELDS = ("payee_id", "account_ref", "amount", "currency", "purpose", "route_id", "not_after", "nonce")
APPROVER_ROLES = ("student", "parent")
VERSION = "oasis-approval-v1"


def make_draft(*, payee_id: str, account_ref: str, amount: float, currency: str, purpose: str, route_id: str,
               not_after: str, nonce: str) -> dict:
    d = {"payee_id": payee_id, "account_ref": account_ref, "amount": float(amount), "currency": currency,
         "purpose": purpose, "route_id": route_id, "not_after": not_after, "nonce": nonce}
    d["canonical"] = canonical({k: d[k] for k in DRAFT_FIELDS}).decode()
    d["draft_hash"] = sha256_hex(d["canonical"])
    return d


def draft_hash(fields: dict) -> str:
    """Hash of the draft fields of a draft, an intent or a payload dict (extra keys are ignored)."""
    return sha256_hex(canonical({k: (float(fields[k]) if k == "amount" else fields[k]) for k in DRAFT_FIELDS}))


def approval_message(role: str, dhash: str) -> bytes:
    return f"{VERSION}|{role}|{dhash}".encode()


def key_id_of(public_key_b64: str) -> str:
    return hashlib.sha256(unb64(public_key_b64)).hexdigest()[:16]


def _verify(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        VerifyKey(unb64(public_key_b64)).verify(message, unb64(signature_b64))
        return True
    except (BadSignatureError, ValueError, TypeError):   # malformed base64 / wrong length are just "invalid"
        return False


def verify_approval_standalone(approval: dict, dhash: str) -> bool:
    """Offline check used by proof packs: the embedded key must match its key_id and the signature must verify."""
    try:
        pk = approval["public_key"]
        return (key_id_of(pk) == approval["key_id"]
                and _verify(pk, approval_message(approval["role"], dhash), approval["signature"]))
    except (KeyError, TypeError, ValueError):
        return False


class ApproverRegistry:
    """Role -> registered Ed25519 public key(s). Only the ACTIVE key of a role can approve; retired keys are kept so
    that old proof packs can still be pinned."""

    def __init__(self):
        self.keys: list[dict] = []

    def register(self, role: str, public_key_b64: str, at: str | None = None) -> dict:
        if role not in APPROVER_ROLES:
            raise ValueError(f"role {role!r} cannot hold an approval key")
        raw = unb64(public_key_b64)
        if len(raw) != 32:
            raise ValueError("an Ed25519 public key is 32 bytes")
        kid = key_id_of(public_key_b64)
        for k in self.keys:
            if k["role"] == role and k["active"]:
                k["active"] = False
        existing = next((k for k in self.keys if k["key_id"] == kid and k["role"] == role), None)
        if existing:
            existing["active"] = True
            return existing
        rec = {"role": role, "key_id": kid, "public_key": public_key_b64, "active": True,
               "registered_at": at or datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.keys.append(rec)
        return rec

    def active(self, role: str) -> dict | None:
        return next((k for k in self.keys if k["role"] == role and k["active"]), None)

    def verify(self, role: str, dhash: str, signature_b64: str, key_id: str | None = None) -> dict | None:
        """The registered key record if `signature_b64` is a valid signature by `role`'s active key over `dhash`."""
        k = self.active(role)
        if k is None or (key_id and key_id != k["key_id"]):
            return None
        return k if _verify(k["public_key"], approval_message(role, dhash), signature_b64) else None

    def verify_record(self, rec: dict, dhash: str) -> bool:
        try:
            return self.verify(rec["role"], dhash, rec["signature"], rec.get("key_id")) is not None
        except (KeyError, TypeError):
            return False

    def make_record(self, role: str, signature_b64: str, at: str) -> dict:
        """The approval record stored in the intent: everything an offline verifier needs."""
        k = self.active(role)
        return {"role": role, "key_id": k["key_id"], "public_key": k["public_key"], "signature": signature_b64, "at": at}

    def pinned_key_ids(self) -> set[str]:
        return {k["key_id"] for k in self.keys}

    def public_view(self) -> list[dict]:
        return [{k: v for k, v in rec.items()} for rec in self.keys]

    def load(self, keys: list[dict]) -> None:
        self.keys = [dict(k) for k in keys]


class SimDevices:
    """In-process device keys for SIMULATED humans (sandbox worlds only). `seed` makes them reproducible for the demo."""

    def __init__(self, registry: ApproverRegistry, seed: bytes | None = None):
        self._sk: dict[str, SigningKey] = {}
        for role in APPROVER_ROLES:
            s = hashlib.sha256(seed + role.encode()).digest() if seed else None
            sk = SigningKey(s) if s else SigningKey.generate()
            self._sk[role] = sk
            registry.register(role, b64(bytes(sk.verify_key)), at="sandbox")

    def sign(self, role: str, dhash: str) -> str:
        return b64(self._sk[role].sign(approval_message(role, dhash)).signature)


class Device:
    """A test/harness stand-in for the browser: holds a role's private key, registers it, signs drafts."""

    def __init__(self, role: str, seed: bytes | None = None):
        self.role = role
        self._sk = SigningKey(seed) if seed else SigningKey.generate()
        self.public_key = b64(bytes(self._sk.verify_key))

    def sign(self, dhash: str, role: str | None = None) -> str:
        r = role or self.role
        return b64(self._sk.sign(approval_message(r, dhash)).signature)
