"""Secret key files: created on first use, git-ignored, optionally wrapped with a passphrase.

HONEST LIMITS. By default these are PLAINTEXT key files (base64 inside JSON) protected only by the operating system:
written owner-only where the OS honours it (POSIX chmod 0600; on Windows `chmod` only toggles read-only, so rely on the
folder ACL / disk encryption of your account), git-ignored, never logged. Anyone who can read the file as your user can
use the key. Set `OASIS_KEY_PASSPHRASE` and new key files are written WRAPPED (scrypt -> AES-256-GCM); existing plaintext
key files are upgraded to wrapped on the next start. The passphrase then has to be supplied at every start (env var), so
it protects a copied key file / backup, not a running server whose environment an attacker can read.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .. import config
from .crypto import b64, unb64


def passphrase() -> str | None:
    return os.environ.get("OASIS_KEY_PASSPHRASE") or None


def wrap(plain: bytes, pw: str) -> dict:
    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(pw.encode())
    return {"kdf": "scrypt-n32768-r8-p1", "salt": b64(salt), "nonce": b64(nonce),
            "ct": b64(AESGCM(key).encrypt(nonce, plain, b"oasis-keyfile-v1"))}


def unwrap(w: dict, pw: str) -> bytes:
    key = Scrypt(salt=unb64(w["salt"]), length=32, n=2 ** 15, r=8, p=1).derive(pw.encode())
    try:
        return AESGCM(key).decrypt(unb64(w["nonce"]), unb64(w["ct"]), b"oasis-keyfile-v1")
    except Exception as e:     # InvalidTag
        raise ValueError("key file cannot be unwrapped: wrong OASIS_KEY_PASSPHRASE") from e


def write_private(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def read_secret_json(p: Path) -> dict:
    """Read a key file's JSON body, unwrapping it if it is wrapped. Upgrades a plaintext file when a passphrase is set."""
    d = json.loads(p.read_text(encoding="utf-8"))
    pw = passphrase()
    if "wrapped" in d:
        if not pw:
            raise ValueError(f"key file {p} is passphrase-wrapped: set OASIS_KEY_PASSPHRASE")
        return json.loads(unwrap(d["wrapped"], pw))
    if pw:      # plaintext file but a passphrase is configured: wrap it in place
        write_private(p, {"version": 1, "wrapped": wrap(json.dumps(d).encode(), pw)})
    return d


def write_secret_json(p: Path, body: dict) -> None:
    pw = passphrase()
    write_private(p, {"version": 1, "wrapped": wrap(json.dumps(body).encode(), pw)} if pw else body)


def load_or_create_secret(p: Path, nbytes: int = 32) -> bytes:
    if p.exists():
        return unb64(read_secret_json(p)["key"])
    key = os.urandom(nbytes)
    write_secret_json(p, {"version": 1, "key": b64(key)})
    return key


def default_data_key_path() -> Path:
    env = os.environ.get("OASIS_DATA_KEY")
    return Path(env) if env else config.DATA_DIR / "keys" / "data_key.json"


def default_session_secret_path() -> Path:
    env = os.environ.get("OASIS_SESSION_SECRET_FILE")
    return Path(env) if env else config.DATA_DIR / "keys" / "session_secret.json"
