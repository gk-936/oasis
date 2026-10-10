"""MOCK verified-payee registry (WeIdentity-style): an issuer signs credentials that bind a
payee identity to a receiving account. Demo identities only — not real institutions.

Credentials are signed with the same hybrid Ed25519 + ML-DSA-65 scheme as intents.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..trust.crypto import HybridSigner, canonical, demo_signer, verify_hybrid


@dataclass
class Credential:
    payee_id: str
    name: str
    payee_type: str
    account_ref: str
    issued_at: str
    signatures: dict

    def body(self) -> dict:
        return {"payee_id": self.payee_id, "name": self.name, "payee_type": self.payee_type,
                "account_ref": self.account_ref, "issued_at": self.issued_at}


class VerifiedPayeeRegistry:
    def __init__(self, deterministic: bool = False):
        self._issuer = demo_signer("registry-issuer", "demo-issuer-1") if deterministic else HybridSigner(key_id="demo-issuer-1")
        self._creds: dict[str, Credential] = {}
        self._contacts: dict[str, dict] = {}    # payee_id -> verified contact channel (MOCK), kept beside the credential

    def issuer_public_keys(self) -> dict:
        return self._issuer.public_keys()

    def issue(self, payee_id: str, name: str, payee_type: str, account_ref: str,
              issued_at: str = "2026-10-01") -> Credential:
        body = {"payee_id": payee_id, "name": name, "payee_type": payee_type,
                "account_ref": account_ref, "issued_at": issued_at}
        cred = Credential(**body, signatures=self._issuer.sign(canonical(body)))
        self._creds[payee_id] = cred
        return cred

    def lookup(self, payee_id: str) -> Credential | None:
        c = self._creds.get(payee_id)
        if c and verify_hybrid(canonical(c.body()), c.signatures, self.issuer_public_keys()):
            return c
        return None

    def all(self) -> list[dict]:
        return [c.body() for c in self._creds.values()]

    def lookup_by_name(self, name: str) -> Credential | None:
        """Exact (case-insensitive) identity match only — lookalike names must NOT resolve."""
        for c in self._creds.values():
            if c.name.casefold() == name.casefold():
                return self.lookup(c.payee_id)
        return None

    def set_contact(self, payee_id: str, channel: str, address: str) -> None:
        """The registry's verified channel for a payee (MOCK). Recovery messages go ONLY here."""
        self._contacts[payee_id] = {"channel": channel, "address": address}

    def contact(self, payee_id: str) -> dict | None:
        return dict(self._contacts[payee_id]) if payee_id in self._contacts and self.lookup(payee_id) else None
