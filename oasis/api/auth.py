"""Authentication and roles: student, parent, judge.

Demo-friendly but real: each role has a passcode (OASIS_PASS_STUDENT / OASIS_PASS_PARENT / OASIS_PASS_JUDGE in .env or the host
secrets). There are NO built-in passcodes: a role without one gets a random alphanumeric passcode generated at start-up and
printed once on stderr, so nothing usable is ever in the repository. A correct passcode is exchanged for a signed, short-lived session token:

    token = base64url(json{r: role, exp, iat, jti, v}) . base64url(HMAC-SHA256(session_secret, payload))

stored in an HttpOnly, SameSite=Strict cookie (and also accepted as `Authorization: Bearer <token>`). The session secret
is a git-ignored key file (data/keys/session_secret.json) for a persistent server, random per process otherwise.
Passcodes are compared in constant time, failed logins are rate-limited per client, and a logout revokes the token id.
With OASIS_REQUIRE_CUSTOM_PASSCODES=1 (and in judge mode) the server refuses to start unless all three are set explicitly.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Callable

ROLES = ("student", "parent", "judge")


def judge_mode() -> bool:
    """OASIS_JUDGE_MODE=1: the bundle for letting outside judges try a sandbox. Read at call time. Effects: every passcode must be
    set explicitly (none is generated), each browser gets its own sandbox, /docs /redoc /openapi.json are 404, and the limits are tighter
    (red-team attempts per minute, failed logins per minute, session lifetime). It adds no new capability."""
    return os.environ.get("OASIS_JUDGE_MODE") == "1"

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
    sandbox: str = ""          # judge mode: which sandbox this login belongs to (signed inside the token, so it cannot be forged)


_GENERATED: dict[str, str] = {}      # one random passcode per role per process, so every Auth and the chat redaction agree


def _random_passcode() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"       # no look-alike characters
    return "".join(secrets.choice(alphabet) for _ in range(16))


def passcodes_from_env() -> dict[str, str]:
    """The configured passcode per role; a role with none gets a random one for this process (printed once on stderr)."""
    out = {}
    for r in ROLES:
        v = os.environ.get(f"OASIS_PASS_{r.upper()}")
        if not v:
            if r not in _GENERATED:
                _GENERATED[r] = _random_passcode()
                print(f"[oasis] OASIS_PASS_{r.upper()} is not set: generated passcode for {r}: {_GENERATED[r]} (this run only)",
                      file=sys.stderr, flush=True)
            v = _GENERATED[r]
        out[r] = v
    return out


def missing_passcodes() -> list[str]:
    return [r for r in ROLES if not os.environ.get(f"OASIS_PASS_{r.upper()}")]


class Auth:
    def __init__(self, secret: bytes | None = None, passcodes: dict[str, str] | None = None,
                 ttl_s: int | None = None, clock: Callable[[], float] = time.time):
        self._secret = secret or secrets.token_bytes(32)
        self._pass = passcodes or passcodes_from_env()
        self.ttl_s = ttl_s or (JUDGE_SESSION_TTL_S if judge_mode() and "OASIS_SESSION_TTL_S" not in os.environ else SESSION_TTL_S)
        self._clock = clock
        self._revoked: set[str] = set()
        self.generated = missing_passcodes() if passcodes is None else []       # roles running on a random passcode
        if self.generated and (judge_mode() or os.environ.get("OASIS_REQUIRE_CUSTOM_PASSCODES") == "1"):
            raise RuntimeError(f"Set OASIS_PASS_STUDENT, OASIS_PASS_PARENT and OASIS_PASS_JUDGE explicitly (missing: {self.generated}); "
                               f"judge mode and OASIS_REQUIRE_CUSTOM_PASSCODES=1 never run on generated passcodes.")

    def _sig(self, payload_b64: str) -> str:
        return _b(hmac.new(self._secret, payload_b64.encode(), hashlib.sha256).digest())

    def login(self, role: str, passcode: str, sandbox: str = "") -> tuple[str, Principal] | None:
        if role not in ROLES:
            return None
        ok = hmac.compare_digest(hashlib.sha256(str(passcode).encode("utf-8", "surrogatepass")).digest(),
                                 hashlib.sha256(self._pass[role].encode("utf-8", "surrogatepass")).digest())
        if not ok:
            return None
        now = self._clock()
        p = Principal(role, secrets.token_hex(8), now + self.ttl_s, sandbox)
        payload = _b(json.dumps({"v": 1, "r": role, "iat": now, "exp": p.exp, "jti": p.jti, "sb": sandbox}, separators=(",", ":")).encode())
        return f"{payload}.{self._sig(payload)}", p

    def verify(self, token: str | None) -> Principal | None:
        try:
            payload, sig = (token or "").split(".", 1)
            if not hmac.compare_digest(sig, self._sig(payload)):
                return None
            d = json.loads(_unb(payload))
            if d.get("v") != 1 or d["r"] not in ROLES or d["exp"] < self._clock() or d["jti"] in self._revoked:
                return None
            return Principal(d["r"], d["jti"], d["exp"], str(d.get("sb") or ""))
        except (ValueError, KeyError, TypeError):
            return None

    def revoke(self, jti: str) -> None:
        self._revoked.add(jti)
