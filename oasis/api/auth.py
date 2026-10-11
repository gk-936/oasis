"""Authentication and roles: student, parent, judge.

Demo-friendly but real: each role has a passcode (OASIS_PASS_STUDENT / OASIS_PASS_PARENT / OASIS_PASS_JUDGE in .env;
documented demo defaults in .env.example). A correct passcode is exchanged for a signed, short-lived session token:

    token = base64url(json{r: role, exp, iat, jti, v}) . base64url(HMAC-SHA256(session_secret, payload))

stored in an HttpOnly, SameSite=Strict cookie (and also accepted as `Authorization: Bearer <token>`). The session secret
is a git-ignored key file (data/keys/session_secret.json) for a persistent server, random per process otherwise.
Passcodes are compared in constant time, failed logins are rate-limited per client, and a logout revokes the token id.
The demo defaults are PUBLIC, so a real deployment must set its own: with OASIS_REQUIRE_CUSTOM_PASSCODES=1 the server
refuses to start on a default passcode.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Callable

ROLES = ("student", "parent", "judge")


def judge_mode() -> bool:
    """OASIS_JUDGE_MODE=1: the bundle for letting outside judges try a sandbox. Read at call time. Effects: default (public)
    passcodes are refused unless OASIS_ALLOW_DEMO_PASSCODES=1, /docs /redoc /openapi.json are 404, and the limits are tighter
    (red-team attempts per minute, failed logins per minute, session lifetime). It adds no new capability."""
    return os.environ.get("OASIS_JUDGE_MODE") == "1"

DEMO_PASSCODES = {"student": "student-demo", "parent": "parent-demo", "judge": "judge-demo"}
SESSION_TTL_S = int(os.environ.get("OASIS_SESSION_TTL_S", "3600"))
JUDGE_SESSION_TTL_S = 1800
COOKIE = "oasis_session"


def _b(x: bytes) -> str:
    return base64.urlsafe_b64encode(x).rstrip(b"=").decode()


def _unb(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass(frozen=True)
class Principal:
    role: str
    jti: str
    exp: float


def passcodes_from_env() -> dict[str, str]:
    return {r: os.environ.get(f"OASIS_PASS_{r.upper()}") or DEMO_PASSCODES[r] for r in ROLES}


class Auth:
    def __init__(self, secret: bytes | None = None, passcodes: dict[str, str] | None = None,
                 ttl_s: int | None = None, clock: Callable[[], float] = time.time):
        self._secret = secret or secrets.token_bytes(32)
        self._pass = passcodes or passcodes_from_env()
        self.ttl_s = ttl_s or (JUDGE_SESSION_TTL_S if judge_mode() and "OASIS_SESSION_TTL_S" not in os.environ else SESSION_TTL_S)
        self._clock = clock
        self._revoked: set[str] = set()
        self.demo_defaults = [r for r in ROLES if self._pass[r] == DEMO_PASSCODES[r]]
        if judge_mode() and self.demo_defaults and os.environ.get("OASIS_ALLOW_DEMO_PASSCODES") != "1":
            raise RuntimeError(f"OASIS_JUDGE_MODE=1 refuses the public demo passcode for: {self.demo_defaults}. Set OASIS_PASS_* "
                               f"or, for a sandbox you accept is open to anyone who reads the repo, OASIS_ALLOW_DEMO_PASSCODES=1.")
        if os.environ.get("OASIS_REQUIRE_CUSTOM_PASSCODES") == "1" and self.demo_defaults:
            raise RuntimeError(f"OASIS_REQUIRE_CUSTOM_PASSCODES=1 but the demo passcode is still set for: {self.demo_defaults}")

    def _sig(self, payload_b64: str) -> str:
        return _b(hmac.new(self._secret, payload_b64.encode(), hashlib.sha256).digest())

    def login(self, role: str, passcode: str) -> tuple[str, Principal] | None:
        if role not in ROLES:
            return None
        ok = hmac.compare_digest(hashlib.sha256(str(passcode).encode("utf-8", "surrogatepass")).digest(),
                                 hashlib.sha256(self._pass[role].encode("utf-8", "surrogatepass")).digest())
        if not ok:
            return None
        now = self._clock()
        p = Principal(role, secrets.token_hex(8), now + self.ttl_s)
        payload = _b(json.dumps({"v": 1, "r": role, "iat": now, "exp": p.exp, "jti": p.jti}, separators=(",", ":")).encode())
        return f"{payload}.{self._sig(payload)}", p

    def verify(self, token: str | None) -> Principal | None:
        try:
            payload, sig = (token or "").split(".", 1)
            if not hmac.compare_digest(sig, self._sig(payload)):
                return None
            d = json.loads(_unb(payload))
            if d.get("v") != 1 or d["r"] not in ROLES or d["exp"] < self._clock() or d["jti"] in self._revoked:
                return None
            return Principal(d["r"], d["jti"], d["exp"])
        except (ValueError, KeyError, TypeError):
            return None

    def revoke(self, jti: str) -> None:
        self._revoked.add(jti)
