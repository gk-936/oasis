"""Passkeys (WebAuthn) as a second login factor.

A passcode alone is a shared secret. With OASIS_REQUIRE_PASSKEY=1, a role that has registered a passkey must ALSO prove
possession of it (platform authenticator, security key or phone) before a session is issued: the passcode step returns a
challenge instead of a cookie, and the cookie is issued only after a valid assertion. A role with no passkey yet can still log
in by passcode so it can enrol one (that bootstrap is the honest limit: enrol before exposing the server). Off by default, so
the offline judge scripts and tests keep working unchanged.

Only public keys are stored (data/passkeys.json). Challenges are single-use and expire after 5 minutes; the signature counter
is checked so a cloned authenticator is refused. Verification is done by py_webauthn; this module adds storage, challenge
handling and the pending-login state. Not independently audited.
"""
from __future__ import annotations
import base64
import json
import os
import secrets
import time
from pathlib import Path

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

CHALLENGE_TTL_S = 300
MAX_PER_ROLE = 5


def required() -> bool:
    return os.environ.get("OASIS_REQUIRE_PASSKEY") == "1"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class PasskeyError(ValueError):
    """Registration or assertion refused (bad/expired challenge, wrong origin, bad signature, replayed counter)."""


class PasskeyService:
    def __init__(self, path: Path | None = None, clock=time.time):
        self.path, self.clock = path, clock
        self._creds: dict[str, list[dict]] = {}
        self._pending: dict[str, dict] = {}        # challenge id -> {challenge, role, purpose, exp, [token, principal]}
        if path and path.exists():
            try:
                self._creds = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._creds = {}

    # -- storage ---------------------------------------------------------------------------------
    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._creds), encoding="utf-8")

    def registered(self, role: str) -> bool:
        return bool(self._creds.get(role))

    def count(self, role: str) -> int:
        return len(self._creds.get(role, []))

    def must_use(self, role: str) -> bool:
        """The passcode alone is not enough for this role."""
        return required() and self.registered(role)

    def _put(self, kind: str, role: str, challenge: bytes, **extra) -> str:
        now = self.clock()
        for k in [k for k, v in self._pending.items() if v["exp"] < now]:
            del self._pending[k]
        cid = secrets.token_urlsafe(18)
        self._pending[cid] = {"challenge": challenge, "role": role, "kind": kind, "exp": now + CHALLENGE_TTL_S, **extra}
        return cid

    def _take(self, cid: str, kind: str, role: str | None = None) -> dict:
        e = self._pending.pop(cid or "", None)          # single use, even when the assertion then fails
        if not e or e["kind"] != kind or e["exp"] < self.clock() or (role is not None and e["role"] != role):
            raise PasskeyError("challenge missing, expired or already used")
        return e

    # -- registration (needs an existing session) -------------------------------------------------
    def register_begin(self, role: str, rp_id: str) -> dict:
        if self.count(role) >= MAX_PER_ROLE:
            raise PasskeyError(f"at most {MAX_PER_ROLE} passkeys per role")
        opts = generate_registration_options(
            rp_id=rp_id, rp_name="Oasis (sandbox)", user_id=role.encode(), user_name=role, user_display_name=role.title(),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=_unb64(c["id"])) for c in self._creds.get(role, [])],
            authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED,
                                                                   user_verification=UserVerificationRequirement.PREFERRED))
        cid = self._put("register", role, opts.challenge)
        return {"challenge_id": cid, "options": json.loads(options_to_json(opts))}

    def register_finish(self, role: str, challenge_id: str, credential: dict, rp_id: str, origin: str) -> dict:
        e = self._take(challenge_id, "register", role)
        try:
            v = verify_registration_response(credential=credential, expected_challenge=e["challenge"],
                                             expected_rp_id=rp_id, expected_origin=origin)
        except Exception as ex:  # noqa: BLE001 - py_webauthn raises several types; all mean "refused"
            raise PasskeyError(f"registration refused: {type(ex).__name__}") from None
        cid = _b64(v.credential_id)
        if any(c["id"] == cid for c in self._creds.get(role, [])):
            raise PasskeyError("this passkey is already registered")
        self._creds.setdefault(role, []).append({"id": cid, "public_key": _b64(v.credential_public_key),
                                                 "sign_count": v.sign_count, "created": time.strftime("%Y-%m-%d")})
        self._save()
        return {"registered": True, "count": self.count(role)}

    # -- login (second factor after a correct passcode) ------------------------------------------
    def login_begin(self, role: str, rp_id: str, token: str, principal) -> dict:
        opts = generate_authentication_options(
            rp_id=rp_id, user_verification=UserVerificationRequirement.PREFERRED,
            allow_credentials=[PublicKeyCredentialDescriptor(id=_unb64(c["id"])) for c in self._creds.get(role, [])])
        cid = self._put("login", role, opts.challenge, token=token, principal=principal)
        return {"mfa_required": True, "challenge_id": cid, "options": json.loads(options_to_json(opts))}

    def login_finish(self, challenge_id: str, credential: dict, rp_id: str, origin: str):
        """Returns (token, principal) when the assertion verifies; raises PasskeyError otherwise."""
        e = self._take(challenge_id, "login")
        role = e["role"]
        try:
            raw_id = _b64(_unb64(str(credential.get("rawId") or credential.get("id") or "")))
        except Exception:  # noqa: BLE001
            raise PasskeyError("assertion refused: malformed credential id") from None
        cred = next((c for c in self._creds.get(role, []) if c["id"] == raw_id), None)
        if cred is None:
            raise PasskeyError("assertion refused: unknown passkey for this role")
        try:
            v = verify_authentication_response(credential=credential, expected_challenge=e["challenge"], expected_rp_id=rp_id,
                                               expected_origin=origin, credential_public_key=_unb64(cred["public_key"]),
                                               credential_current_sign_count=cred["sign_count"])
        except Exception as ex:  # noqa: BLE001
            raise PasskeyError(f"assertion refused: {type(ex).__name__}") from None
        cred["sign_count"] = v.new_sign_count
        self._save()
        return e["token"], e["principal"]
