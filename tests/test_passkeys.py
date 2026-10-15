"""Passkey second factor: a software authenticator (P-256, 'none' attestation) drives the real endpoints."""
import base64
import hashlib
import json
import os
import struct

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from fastapi.testclient import TestClient

RP_ID, ORIGIN = "testserver", "http://testserver"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Authenticator:
    def __init__(self, origin=ORIGIN, rp_id=RP_ID):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0
        self.origin, self.rp_id = origin, rp_id

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def create(self, options: dict) -> dict:
        cd = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": self.origin}).encode()
        auth = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x41]) + struct.pack(">I", 0) + bytes(16)
                + struct.pack(">H", len(self.cred_id)) + self.cred_id + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cd), "attestationObject": b64(att)}}

    def get(self, options: dict, bump=True, wrong_key=False) -> dict:
        if bump:
            self.count += 1
        cd = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": self.origin}).encode()
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x01]) + struct.pack(">I", self.count)
        key = ec.generate_private_key(ec.SECP256R1()) if wrong_key else self.key
        sig = key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cd), "authenticatorData": b64(auth), "signature": b64(sig)}}


def passcode_login(client, role="student"):
    return client.post("/api/auth/login", json={"role": role, "passcode": f"{role}-demo"})


def enrol(client, auth: Authenticator):
    b = client.post("/api/auth/passkey/register/begin").json()
    r = client.post("/api/auth/passkey/register/finish",
                    json={"challenge_id": b["challenge_id"], "credential": auth.create(b["options"])})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def fresh(api_session):
    from oasis.api import main as api
    return TestClient(api.app)


def test_off_by_default_login_unchanged(api_session, fresh):
    enrol_client = passcode_login(fresh)
    assert enrol_client.status_code == 200 and "mfa_required" not in enrol_client.json()
    enrol(fresh, Authenticator())
    other = TestClient(fresh.app)
    assert passcode_login(other).json().get("role") == "student"         # not required, so passcode alone still works


def test_enrol_then_passkey_required(api_session, fresh, monkeypatch):
    passcode_login(fresh)
    a = Authenticator()
    assert enrol(fresh, a)["count"] == 1
    monkeypatch.setenv("OASIS_REQUIRE_PASSKEY", "1")
    c = TestClient(fresh.app)
    r = passcode_login(c).json()
    assert r["mfa_required"] is True and "role" not in r
    assert c.get("/api/auth/me").json()["role"] is None                  # passcode alone gave no session
    f = c.post("/api/auth/passkey/login/finish", json={"challenge_id": r["challenge_id"], "credential": a.get(r["options"])})
    assert f.status_code == 200 and f.json()["role"] == "student"
    assert c.get("/api/auth/me").json()["role"] == "student"


def test_role_without_passkey_can_still_enrol(api_session, fresh, monkeypatch):
    passcode_login(fresh)
    enrol(fresh, Authenticator())                                        # student has one
    monkeypatch.setenv("OASIS_REQUIRE_PASSKEY", "1")
    p = TestClient(fresh.app)
    assert passcode_login(p, "parent").json()["role"] == "parent"        # parent has none yet: bootstrap allowed


def _begin(client, monkeypatch, a):
    passcode_login(client)
    enrol(client, a)
    monkeypatch.setenv("OASIS_REQUIRE_PASSKEY", "1")
    c = TestClient(client.app)
    return c, passcode_login(c).json()


def test_challenge_single_use(api_session, fresh, monkeypatch):
    a = Authenticator()
    c, r = _begin(fresh, monkeypatch, a)
    cred = a.get(r["options"])
    assert c.post("/api/auth/passkey/login/finish", json={"challenge_id": r["challenge_id"], "credential": cred}).status_code == 200
    again = TestClient(c.app).post("/api/auth/passkey/login/finish", json={"challenge_id": r["challenge_id"], "credential": cred})
    assert again.status_code == 401                                      # replayed assertion + used challenge


def test_wrong_key_refused(api_session, fresh, monkeypatch):
    a = Authenticator()
    c, r = _begin(fresh, monkeypatch, a)
    bad = c.post("/api/auth/passkey/login/finish",
                 json={"challenge_id": r["challenge_id"], "credential": a.get(r["options"], wrong_key=True)})
    assert bad.status_code == 401
    assert c.get("/api/auth/me").json()["role"] is None


def test_wrong_origin_refused(api_session, fresh, monkeypatch):
    a = Authenticator()
    c, r = _begin(fresh, monkeypatch, a)
    a.origin = "http://evil.example"
    bad = c.post("/api/auth/passkey/login/finish", json={"challenge_id": r["challenge_id"], "credential": a.get(r["options"])})
    assert bad.status_code == 401


def test_cloned_authenticator_counter_refused(api_session, fresh, monkeypatch):
    a = Authenticator()
    c, r = _begin(fresh, monkeypatch, a)
    a.count = 5
    assert c.post("/api/auth/passkey/login/finish", json={"challenge_id": r["challenge_id"], "credential": a.get(r["options"], bump=False)}).status_code == 200
    r2 = passcode_login(TestClient(c.app)).json()
    old = a.get(r2["options"], bump=False)                               # counter 5 again: not greater than stored 5
    assert TestClient(c.app).post("/api/auth/passkey/login/finish",
                                  json={"challenge_id": r2["challenge_id"], "credential": old}).status_code == 401


def test_unknown_passkey_and_garbage_refused(api_session, fresh, monkeypatch):
    a = Authenticator()
    c, r = _begin(fresh, monkeypatch, a)
    other = Authenticator()
    assert c.post("/api/auth/passkey/login/finish",
                  json={"challenge_id": r["challenge_id"], "credential": other.get(r["options"])}).status_code == 401
    r3 = passcode_login(TestClient(c.app)).json()
    assert c.post("/api/auth/passkey/login/finish",
                  json={"challenge_id": r3["challenge_id"], "credential": {"rawId": "!!", "response": {}}}).status_code == 401
    assert c.post("/api/auth/passkey/login/finish", json={"challenge_id": "nope", "credential": {}}).status_code == 401


def test_registration_needs_session_and_valid_challenge(api_session, fresh):
    assert fresh.post("/api/auth/passkey/register/begin").status_code == 401
    passcode_login(fresh)
    b = fresh.post("/api/auth/passkey/register/begin").json()
    a = Authenticator(origin="http://evil.example")
    r = fresh.post("/api/auth/passkey/register/finish", json={"challenge_id": b["challenge_id"], "credential": a.create(b["options"])})
    assert r.status_code == 400


def test_failed_second_factor_counts_toward_login_limit(api_session, fresh, monkeypatch):
    a = Authenticator()
    c, r = _begin(fresh, monkeypatch, a)
    codes = []
    for _ in range(12):
        codes.append(c.post("/api/auth/passkey/login/finish", json={"challenge_id": "x", "credential": {}}).status_code)
    assert 429 in codes


def test_passkeys_persist(tmp_path):
    from oasis.api.passkeys import PasskeyService
    p = tmp_path / "pk.json"
    s = PasskeyService(p)
    b = s.register_begin("student", RP_ID)
    a = Authenticator()
    s.register_finish("student", b["challenge_id"], a.create(b["options"]), RP_ID, ORIGIN)
    assert PasskeyService(p).registered("student")
    assert "private" not in p.read_text()


def test_rp_origin_follows_the_browsers_origin_behind_a_tls_proxy():
    from types import SimpleNamespace as NS
    from oasis.api import main
    req = lambda origin: NS(headers={"host": "oasis.example.com", **({"origin": origin} if origin else {})}, url=NS(scheme="http"))
    assert main._rp(req("https://oasis.example.com")) == ("oasis.example.com", "https://oasis.example.com")
    assert main._rp(req(None)) == ("oasis.example.com", "http://oasis.example.com")
    assert main._rp(req("https://evil.example"))[1] == "http://oasis.example.com"      # a different host never becomes the expected origin
