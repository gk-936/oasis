"""Scripted client for Oasis: log in, chat, and sign pending drafts exactly like the browser does. Standard library + PyNaCl only.

A payment task ends as a HELD draft that needs the approver's device-key signature. A script has no browser, so this client
holds its own Ed25519 device key (a local file), registers the public half with the server, and signs the exact draft hash.
It does not bypass anything: the server still checks the signature against the registered key, the exact draft, the nonce and
the expiry. There is no auto-approve switch.

    PYTHONPATH=. python tools/oasis_client.py --base http://127.0.0.1:8000 chat "pay my rent"
    PYTHONPATH=. python tools/oasis_client.py --base http://127.0.0.1:8000 chat "pay my rent" --sign
    PYTHONPATH=. python tools/oasis_client.py task "pay my tuition" "what do I owe?" --sign    # several messages in order

Use `--role parent --passcode ...` in a second invocation to co-sign a large payment. Passcodes may come from OASIS_PASS_STUDENT /
OASIS_PASS_PARENT; the key file is created on first use (keep it out of git).
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from nacl.signing import SigningKey

VERSION = "oasis-approval-v1"          # must match oasis/trust/approvals.py
DEFAULT_PASS = {"student": "student-demo", "parent": "parent-demo"}


class ApiError(RuntimeError):
    def __init__(self, status: int, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status, self.body = status, body


class OasisClient:
    def __init__(self, base: str = "http://127.0.0.1:8000", role: str = "student", passcode: str | None = None,
                 key_file: str | os.PathLike | None = None, lang: str | None = None):
        self.base, self.role, self.lang = base.rstrip("/"), role, lang
        self.passcode = passcode or os.environ.get(f"OASIS_PASS_{role.upper()}") or DEFAULT_PASS.get(role, "")
        self.key_file = Path(key_file or f".oasis_device_key_{role}")
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._sk = self._load_key()
        self.key_id: str | None = None
        self._logged_in = False

    # ---- plumbing
    def _load_key(self) -> SigningKey:
        if self.key_file.exists():
            return SigningKey(base64.b64decode(self.key_file.read_text().strip()))
        sk = SigningKey.generate()
        self.key_file.write_text(base64.b64encode(bytes(sk)).decode())
        return sk

    @property
    def public_key(self) -> str:
        return base64.b64encode(bytes(self._sk.verify_key)).decode()

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **({"X-Oasis-Lang": self.lang} if self.lang else {})})
        try:
            with self._opener.open(req, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw.decode("utf-8", "replace")
            raise ApiError(e.code, payload) from None
        return json.loads(raw) if raw else None

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, body: dict | None = None):
        return self.request("POST", path, body or {})

    # ---- session
    def login(self) -> dict:
        out = self.post("/api/auth/login", {"role": self.role, "passcode": self.passcode})
        self._logged_in = True
        return out

    def _ensure(self) -> None:
        if not self._logged_in:
            self.login()

    def register_device(self) -> str:
        """Register this client's public key as the role's device key (the private key never leaves the key file)."""
        self._ensure()
        self.key_id = self.post("/api/device/register", {"public_key": self.public_key})["key_id"]
        return self.key_id

    def reset(self) -> dict:
        self._ensure()
        return self.post("/api/reset")

    def state(self) -> dict:
        self._ensure()
        return self.get("/api/state")

    # ---- tasks
    def chat(self, message: str) -> dict:
        """One chat turn. The reply has: reply, intent, status, pending_id, draft_hash, needs, money_moved, proof_id."""
        self._ensure()
        return self.post("/api/chat", {"message": message})

    def sign_message(self, draft_hash: str) -> str:
        return base64.b64encode(self._sk.sign(f"{VERSION}|{self.role}|{draft_hash}".encode()).signature).decode()

    def approve(self, pending_id: str, draft_hash: str | None = None) -> dict:
        """Sign the exact draft with this client's device key and send the approval. Declined by the server if the key,
        the hash or the expiry do not match."""
        self._ensure()
        if self.key_id is None:
            self.register_device()
        if draft_hash is None:
            draft_hash = next(p["draft"]["draft_hash"] for p in self.state()["pending"] if p["id"] == pending_id)
        return self.post("/api/approve", {"pending_id": pending_id, "signature": self.sign_message(draft_hash), "key_id": self.key_id})

    def decline(self, pending_id: str) -> dict:
        self._ensure()
        return self.post("/api/approve", {"pending_id": pending_id, "approve": False})

    def task(self, message: str, sign: bool = False) -> dict:
        """Chat, and (with sign=True) sign the draft the reply asks for. Returns the last result, with the chat reply under `chat`."""
        r = self.chat(message)
        if sign and r.get("pending_id") and r.get("status") == "held" and f"{self.role}_signature" in r.get("needs", []):
            out = self.approve(r["pending_id"], r.get("draft_hash"))
            return {**out, "chat": r}
        return r


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")        # replies hold arrows and Chinese text; a Windows console defaults to cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=os.environ.get("OASIS_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--role", default="student", choices=("student", "parent"))
    ap.add_argument("--passcode")
    ap.add_argument("--key-file")
    ap.add_argument("--lang", choices=("en", "zh"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("chat", "task"):
        sp = sub.add_parser(name, help="send one message" if name == "chat" else "send several messages in order")
        sp.add_argument("messages", nargs="+" if name == "task" else 1)
        sp.add_argument("--sign", action="store_true", help="sign the draft the reply asks for, with this client's device key")
    sub.add_parser("state")
    sub.add_parser("reset")
    sub.add_parser("register")
    a = ap.parse_args(argv)
    c = OasisClient(a.base, a.role, a.passcode, a.key_file, a.lang)
    try:
        if a.cmd in ("chat", "task"):
            out = [c.task(m, a.sign) for m in a.messages]
            print(json.dumps(out if a.cmd == "task" else out[0], indent=2, ensure_ascii=False))
        elif a.cmd == "state":
            print(json.dumps(c.state(), indent=2, ensure_ascii=False))
        elif a.cmd == "reset":
            print(json.dumps(c.reset()))
        else:
            print(json.dumps({"key_id": c.register_device()}))
    except ApiError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
