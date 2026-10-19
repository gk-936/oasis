"""MOCK verified-payee registry (WeIdentity-style): an issuer signs credentials that bind a
payee identity to a receiving account. Demo identities only — not real institutions.

Credentials are signed with the same hybrid Ed25519 + ML-DSA-65 scheme as intents.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..trust.crypto import HybridSigner, canonical, demo_signer, verify_hybrid

# Chinese names and aliases an invoice may print (MOCK, machine-drafted, unreviewed). They sit beside the signed credential, not in
# it, so the credential body and its signatures are unchanged. Vision intake shows them to the model as a closed list.
ALIASES: dict[str, tuple[str, ...]] = {
    "payee_univ_x": ("测试大学财务处", "测试大学", "X大学财务处"),
    "payee_landlord_chen": ("陈伟", "陈先生", "房东陈伟"),
    "payee_student_self": ("本人人民币账户", "学生本人", "阿俊（本人）"),
    "payee_telecom": ("深圳移动", "深圳移动（演示）"),
    "payee_power": ("国家电网（演示）", "国家电网"),
    "payee_internet": ("深圳宽带（演示）", "深圳宽带"),
    "payee_health": ("学生医疗保险（演示）", "学生医保"),
    "payee_visa": ("出入境管理局（演示）", "出入境管理局"),
    "payee_library": ("大学图书馆（演示）", "大学图书馆"),
    "payee_gym": ("校园健身房（演示）", "校园健身房"),
    "payee_peer_priya": ("普丽娅（同学，演示）", "普丽娅"),
    "payee_us_univ": ("示例州立大学（美国）", "示例州立大学"),
    "payee_eu_univ": ("示例大学（欧盟）", "示例大学"),
}


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

    def aliases(self, payee_id: str) -> list[str]:
        return list(ALIASES.get(payee_id, ()))

    def set_contact(self, payee_id: str, channel: str, address: str) -> None:
        """The registry's verified channel for a payee (MOCK). Recovery messages go ONLY here."""
        self._contacts[payee_id] = {"channel": channel, "address": address}

    def contact(self, payee_id: str) -> dict | None:
        return dict(self._contacts[payee_id]) if payee_id in self._contacts and self.lookup(payee_id) else None
