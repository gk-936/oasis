"""Security hardening: roles, signed approvals, encryption at rest, red-team limits, short-lived tool tokens.
Hermetic: in-memory sessions or tmp_path files, no network."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_helpers import Approver, PASS, login, new_client
from eval.approver import SimulatedHumans
from eval.scenarios import tuition
from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.api import main as api
from oasis.api.auth import Auth
from oasis.api.ratelimit import RateLimiter
from oasis.mock.ledger import SandboxLedger, TokenError
from oasis.proof.pack import verify_proof_pack
from oasis.storage import PREFIX, SqliteStore, StoreError
from oasis.trust import keyfile
from oasis.trust.approvals import Device, draft_hash
from oasis.trust.audit import verify_chain
from oasis.world import Features, World

TUITION = ("Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
           "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15")
TOPUP = ("Payee: Arjun (own CNY account)\nPayee ID: payee_student_self\nAccount: acct_student_cny\n"
         "Amount: CNY 8,000\nPurpose: family_support")


# ======================================================================================= authentication + roles
PUBLIC = [("get", "/api/health"), ("get", "/api/auth/config"), ("get", "/api/trust/fingerprint")]

PROTECTED = [("get", "/api/state"), ("get", "/api/audit"), ("get", "/api/audit/verify"), ("get", "/api/proof/int_0001"),
             ("get", "/api/benchmark"), ("get", "/api/plans"), ("get", "/api/parent/pending"), ("get", "/api/redteam/log"),
             ("get", "/api/demo/state"), ("get", "/api/approvers"), ("get", "/api/corridor/rules"), ("get", "/api/reliability/mine"),
             ("post", "/api/reliability/record"),
             ("post", "/api/intake"), ("post", "/api/chat"), ("post", "/api/approve"), ("post", "/api/pay-again"), ("post", "/api/reset"),
             ("post", "/api/redteam"), ("post", "/api/plan"), ("post", "/api/plan/plan_001/accept"),
             ("post", "/api/plan/plan_001/execute"), ("post", "/api/plan/plan_001/consent"), ("post", "/api/rate-target"),
             ("post", "/api/autonomy/tick"), ("post", "/api/spending/add"), ("post", "/api/demo/start"),
             ("post", "/api/demo/run"), ("post", "/api/demo/reset"), ("post", "/api/device/register"),
             ("post", "/api/recovery/approve"), ("post", "/api/auth/logout"), ("post", "/api/student/language")]


def _call(c, method, path):
    return c.get(path) if method == "get" else c.post(path, json={})


def test_public_endpoints_need_no_login(api_session):
    c = TestClient(api_session.app)
    for m, p in PUBLIC:
        assert _call(c, m, p).status_code == 200, p
    assert c.get("/api/proof/int_9999/verify").status_code == 404            # public, and harmless: nothing to leak
    assert c.post("/api/proof/verify", json={"nonsense": 1}).json()["ok"] is False
    assert c.post("/api/reliability/verify", json={"nonsense": 1}).json()["ok"] is False        # public too


@pytest.mark.parametrize("method,path", PROTECTED)
def test_unauthenticated_is_401(api_session, method, path):
    assert _call(TestClient(api_session.app), method, path).status_code == 401


# role -> (method, path) it must NOT be allowed to call (403)
FORBIDDEN = {
    "parent": [("post", "/api/intake"), ("post", "/api/chat"), ("post", "/api/reset"), ("post", "/api/redteam"),
               ("post", "/api/plan"), ("post", "/api/plan/plan_001/accept"), ("post", "/api/rate-target"),
               ("post", "/api/autonomy/tick"), ("post", "/api/demo/start"), ("post", "/api/demo/run"),
               ("post", "/api/recovery/approve"), ("post", "/api/spending/add"),
               ("post", "/api/reliability/record"), ("get", "/api/reliability/mine"), ("post", "/api/student/language"),
               ("get", "/api/audit"), ("get", "/api/redteam/log"), ("get", "/api/plans"), ("get", "/api/benchmark")],
    "judge": [("post", "/api/intake"), ("post", "/api/chat"), ("post", "/api/approve"), ("post", "/api/pay-again"), ("post", "/api/reset"),
              ("post", "/api/plan"), ("post", "/api/plan/plan_001/accept"), ("post", "/api/plan/plan_001/consent"),
              ("post", "/api/rate-target"), ("post", "/api/autonomy/tick"), ("post", "/api/demo/start"),
              ("post", "/api/demo/run"), ("post", "/api/recovery/approve"), ("post", "/api/device/register"),
              ("post", "/api/spending/add"), ("post", "/api/reliability/record"), ("get", "/api/reliability/mine"),
              ("post", "/api/student/language")],
    "student": [("post", "/api/redteam"), ("get", "/api/redteam/log"), ("post", "/api/plan/plan_001/consent")],
}


@pytest.mark.parametrize("role", sorted(FORBIDDEN))
def test_wrong_role_is_403(api_session, role):
    c = new_client(role)
    for m, p in FORBIDDEN[role]:
        assert _call(c, m, p).status_code == 403, (role, m, p)


def test_each_role_can_do_its_own_things(api_session):
    st, pa, ju = new_client("student"), new_client("parent"), new_client("judge")
    assert st.post("/api/intake", json={"text": TUITION}).status_code == 200
    assert st.get("/api/state").status_code == 200 and ju.get("/api/state").status_code == 200
    assert ju.get("/api/audit/verify").json()["ok"] and ju.get("/api/redteam/log").status_code == 200
    assert pa.get("/api/parent/pending").status_code == 200
    # least privilege: the parent's state view carries no passport, balances or ledger
    ps = pa.get("/api/state").json()
    assert "passport" not in ps and "ledger_money_lost" not in ps and ps["role"] == "parent"


def test_login_failures_cookie_flags_and_logout(api_session):
    c = TestClient(api_session.app)
    assert c.post("/api/auth/login", json={"role": "student", "passcode": "nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"role": "admin", "passcode": "x"}).status_code == 401
    r = c.post("/api/auth/login", json={"role": "judge", "passcode": PASS["judge"]})
    assert r.status_code == 200 and "token" not in r.json()                      # the browser never sees the token
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert c.get("/api/auth/me").json()["role"] == "judge"
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").json() == {"role": None}                        # the revoked token no longer works (200 probe, no role)


def test_student_passcode_does_not_log_in_as_parent(api_session):
    c = TestClient(api_session.app)
    assert c.post("/api/auth/login", json={"role": "parent", "passcode": PASS["student"]}).status_code == 401


def test_failed_logins_are_rate_limited(api_session):
    c = TestClient(api_session.app)
    codes = [c.post("/api/auth/login", json={"role": "student", "passcode": "bad"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert c.post("/api/auth/login", json={"role": "student", "passcode": PASS["student"]}).status_code == 429


def test_token_expiry_tampering_and_bearer_header():
    now = [1000.0]
    a = Auth(secret=b"k" * 32, ttl_s=60, clock=lambda: now[0])
    tok, p = a.login("student", "student-demo")
    assert a.verify(tok).role == "student"
    payload, sig = tok.split(".")
    assert a.verify(payload + "." + sig[:-2] + "AA") is None                     # signature tampered
    forged = Auth(secret=b"z" * 32, clock=lambda: now[0]).login("judge", "judge-demo")[0]
    assert a.verify(forged) is None                                              # signed with another secret
    now[0] += 61
    assert a.verify(tok) is None                                                 # expired
    assert a.verify("garbage") is None and a.verify(None) is None


def test_bearer_token_header_is_accepted(api_session):
    c = TestClient(api_session.app)
    tok = c.post("/api/auth/login?return_token=true", json={"role": "judge", "passcode": PASS["judge"]}).json()["token"]
    fresh = TestClient(api_session.app)
    assert fresh.get("/api/auth/me").json() == {"role": None}
    assert fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()["role"] == "judge"


def test_strict_mode_refuses_demo_passcodes(monkeypatch):
    monkeypatch.setenv("OASIS_REQUIRE_CUSTOM_PASSCODES", "1")
    with pytest.raises(RuntimeError):
        Auth()
    ok = Auth(passcodes={"student": "s3cret-a", "parent": "s3cret-b", "judge": "s3cret-c"})
    assert ok.demo_defaults == []


# ======================================================================================= signed approvals
def _held(c, text=TUITION, **kw):
    o = c.post("/api/intake", json={"text": text, **kw}).json()
    assert o["status"] == "held" and o["pending_id"]
    return o


def test_approval_without_signature_is_refused(api_client):
    o = _held(api_client)
    Approver(api_client, "student")
    r = api_client.post("/api/approve", json={"pending_id": o["pending_id"]})
    assert r.status_code == 403 and "signed approval" in r.json()["detail"]
    assert api_client.get("/api/state").json()["ledger_money_lost"] == 0
    assert api_session_transfers() == []


def api_session_transfers():
    return api.S.world.ledger.transfers


def test_forged_signature_is_refused(api_client):
    o = _held(api_client)
    me = Approver(api_client, "student")
    attacker = Device("student")                     # a different private key claiming to be the student
    dh = me.draft_hash(o["pending_id"])
    for sig in (attacker.sign(dh), "AAAA", "not base64 at all!!", me.device.sign(dh)[:-4] + "AAAA"):
        r = api_client.post("/api/approve", json={"pending_id": o["pending_id"], "signature": sig, "key_id": me.key_id})
        assert r.status_code == 403, sig
    assert api_session_transfers() == []
    assert api.S.world.audit.find("approval_rejected")
    assert me.approve(o["pending_id"]).json()["status"] == "paid"             # the genuine one still works


def test_signature_for_a_different_payment_is_refused(api_client):
    a = _held(api_client)
    b = _held(api_client, TUITION.replace("30,000", "29,000"))                 # a different amount: different draft
    me = Approver(api_client, "student")
    sig_for_a = me.signature(a["pending_id"])
    r = api_client.post("/api/approve", json={"pending_id": b["pending_id"], "signature": sig_for_a, "key_id": me.key_id})
    assert r.status_code == 403
    assert me.draft_hash(a["pending_id"]) != me.draft_hash(b["pending_id"])
    assert api_session_transfers() == []


def test_a_role_string_without_a_signature_grants_nothing(api_client, as_role):
    parent_c = as_role("parent")
    o = _held(api_client, TOPUP, remitter="parent")
    student, parent = Approver(api_client, "student"), Approver(parent_c, "parent")
    assert student.approve(o["pending_id"]).json()["status"] == "waiting"
    # the student claims to be the parent: a "role" field is ignored, the session role decides, and the key must match
    r = api_client.post("/api/approve", json={"pending_id": o["pending_id"], "role": "parent",
                                              "signature": student.signature(o["pending_id"]), "key_id": student.key_id})
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["missing"] == ["parent"]
    # the parent session with the STUDENT's signature, or with none, is refused
    assert parent_c.post("/api/approve", json={"pending_id": o["pending_id"],
                                               "signature": student.signature(o["pending_id"])}).status_code == 403
    assert parent_c.post("/api/approve", json={"pending_id": o["pending_id"]}).status_code == 403
    assert api_session_transfers() == []
    assert parent.approve(o["pending_id"]).json()["status"] == "paid"


def test_unregistered_device_cannot_approve(api_client):
    o = _held(api_client)
    ghost = Device("student")                         # never registered with the server
    sig = ghost.sign(api.S.pending[o["pending_id"]]["outcome"]["draft"]["draft_hash"])
    assert api_client.post("/api/approve", json={"pending_id": o["pending_id"], "signature": sig}).status_code == 403


def test_rotating_the_device_key_retires_the_old_one(api_client):
    o = _held(api_client)
    old = Approver(api_client, "student")
    sig_old = old.signature(o["pending_id"])
    new = Approver(api_client, "student")
    assert api_client.post("/api/approve", json={"pending_id": o["pending_id"], "signature": sig_old}).status_code == 403
    assert new.approve(o["pending_id"]).json()["status"] == "paid"


def test_pipeline_ignores_role_strings_and_forged_signed_approvals():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    a = OasisAgent(w)
    req = Request(tuition())
    req.approvals = ("student", "parent")                                      # the old way: a role string
    o = a.handle(req)
    assert o.status == "held" and w.ledger.transfers == []
    assert w.audit.find("unsigned_approval_ignored")
    rogue = Device("student")
    req2 = Request(tuition(), signed_approvals=({"role": "student", "key_id": "x", "signature": rogue.sign(o.draft["draft_hash"]),
                                                 "at": w.now_iso()},), draft={"nonce": o.draft["nonce"], "not_after": o.draft["not_after"]})
    o2 = a.handle(req2)
    assert o2.status == "held" and o2.rejected_approvals and w.audit.find("approval_rejected")
    ok = a.handle(a.sim_approve(Request(tuition()), o, ["student"]))
    assert ok.status == "paid" and ok.intent["approvals"][0]["signature"]


def test_approval_is_bound_to_the_exact_draft_so_a_changed_amount_is_not_approved():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    a = OasisAgent(w)
    held = a.handle(Request(tuition()))
    req = a.sim_approve(Request(tuition().replace("30,000", "29,000")), held, ["student"])    # signatures made for 30,000
    o = a.handle(req)
    assert o.status == "held" and o.rejected_approvals and w.ledger.transfers == []


def test_executor_refuses_an_intent_whose_approval_has_no_valid_signature():
    from oasis.trust.policy import PolicyInput, decide
    w = World(Features.full(), OfflineLLM())
    w.ledger.accounts["acct_student_cny"].balance = 1000
    nonce = w.builder.new_nonce()
    b = dict(student_id="stu_001", payee_id="payee_univ_x", account_ref="6228480000001234", amount=100.0, currency="CNY",
             purpose="tuition", route_id="r", not_after=w.now.replace(hour=23, minute=59).isoformat(), tier=2, nonce=nonce,
             approvals=[{"role": "student", "key_id": "ab", "public_key": "AA==", "signature": "AA==", "at": w.now_iso()}])
    it = w.builder.build(**b)                                                  # properly signed by the SERVER, but the approval is junk
    payload = {k: it[k] for k in ("payee_id", "account_ref", "amount", "currency", "route_id")}
    seen = []
    res = w.executor.execute(it, payload, lambda appr: seen.append(appr), "acct_student_cny")
    assert res.status == "frozen" and any("no valid signature" in r for r in res.reasons)
    assert seen == [] and w.ledger.transfers == []                             # policy was never even consulted


def test_proof_pack_records_and_verifies_approver_signatures(api_client):
    o = _held(api_client)
    me = Approver(api_client, "student")
    r = me.approve(o["pending_id"]).json()
    pack = api_client.get(f"/api/proof/{r['proof_id']}").json()
    ap = pack["intent"]["approvals"][0]
    assert ap["role"] == "student" and ap["key_id"] == me.key_id and ap["signature"] and ap["public_key"] == me.device.public_key
    v = api_client.get(f"/api/proof/{r['proof_id']}/verify").json()
    assert v["ok"] and v["approvals_signed"] is True and v["approver_keys_pinned"] is True
    # a pack whose approval was swapped for one signed by an attacker's key fails, even if re-signed by someone
    bad = copy.deepcopy(pack)
    rogue = Device("student")
    bad["intent"]["approvals"][0] = {**ap, "key_id": "0" * 16, "public_key": rogue.public_key,
                                     "signature": rogue.sign(pack["intent_hash"])}
    res = api_client.post("/api/proof/verify", json=bad).json()
    assert not res["ok"]
    # an approval over a different draft fails on its own
    bad2 = copy.deepcopy(pack)
    bad2["intent"]["amount"] = 1.0
    res2 = api_client.post("/api/proof/verify", json=bad2).json()
    assert res2["approvals_signed"] is False and not res2["ok"]
    # offline: valid signatures but the approver key is not pinned -> not ok
    w = api.S.world
    off = verify_proof_pack(pack, {w.trust_fingerprint()}, w.anchor, {"deadbeefdeadbeef"})
    assert off["approvals_signed"] is True and off["approver_keys_pinned"] is False and not off["ok"]
    assert verify_proof_pack(pack, {w.trust_fingerprint()}, w.anchor)["ok"] is False      # no pin supplied: never "ok"


def test_parent_conversion_consent_needs_the_parents_signature(api_client, as_role):
    from oasis.planning.scenarios import build_scenario_world
    parent_c = as_role("parent")
    p = api_client.post("/api/plan", json={"goal": "pay everything"}).json()
    api_client.post(f"/api/plan/{p['id']}/accept")
    ex = api_client.post(f"/api/plan/{p['id']}/execute").json()
    needs = api_client.get(f"/api/plan/{p['id']}").json()["parent_consents"]
    if not needs:
        pytest.skip("the default plan has no parent-remitted conversion")
    parent = Approver(parent_c, "parent")
    step = needs[0]
    assert parent_c.post(f"/api/plan/{p['id']}/consent", json={"step": step["step"], "signature": "AAAA"}).status_code == 403
    assert parent_c.post(f"/api/plan/{p['id']}/consent", json={"step": step["step"],
                                                              "signature": parent.device.sign(step["draft_hash"])}).status_code == 200


# ======================================================================================= encryption at rest
def _pay_on_disk(tmp_path):
    db = str(tmp_path / "enc.db")
    s = api.Session(db, key_path=tmp_path / "keys" / "trust_key.json")
    saved, api.S = api.S, s
    try:
        c = login(TestClient(api.app), "student")
        o = c.post("/api/intake", json={"text": TUITION}).json()
        r = Approver(c, "student").approve(o["pending_id"]).json()
        assert r["status"] == "paid"
        c.post("/api/intake", json={"text": TUITION.replace("6228480000001234", "6228480000009999")})
    finally:
        api.S = saved
    s.store.close()
    return db, tmp_path / "keys" / "trust_key.json", r["proof_id"]


def test_database_file_reveals_nothing_without_the_key(tmp_path):
    db, keys, proof_id = _pay_on_disk(tmp_path)
    raw = Path(db).read_bytes()
    for needle in (b"University X", b"6228480000001234", b"6228480000009999", b"payee_univ_x", b"tuition", b"Arjun",
                   b"30000", b"transfer_executed", b"signature", b"Chen Wei"):
        assert needle not in raw, needle
    con = sqlite3.connect(db)
    for table in ("kv", "audit", "proofs", "cards"):
        rows = con.execute(f"SELECT json FROM {table}").fetchall()
        assert rows and all(r[0].startswith(PREFIX) for r in rows), table
    con.close()
    # control: the same facts ARE in the plaintext data, so the grep above is meaningful
    s2 = api.Session(db, key_path=keys)
    assert b"University X" in json.dumps(s2.world.snapshot(), default=str).encode()
    s2.store.close()


def test_restart_decrypts_and_the_audit_chain_verifies(tmp_path):
    db, keys, proof_id = _pay_on_disk(tmp_path)
    s2 = api.Session(db, key_path=keys)
    assert verify_chain(s2.world.audit.entries).ok and len(s2.world.audit.entries) > 5
    assert s2.world.passport.obligation("obl_tuition_1").status == "paid"
    pack = s2.world.proofs[proof_id]
    assert verify_proof_pack(pack, {s2.world.trust_fingerprint()}, s2.world.anchor, s2.approvers.pinned_key_ids())["ok"]
    s2.store.close()


def test_wrong_data_key_and_tampered_rows_are_refused(tmp_path):
    db, keys, _ = _pay_on_disk(tmp_path)
    with pytest.raises(StoreError, match="cannot decrypt"):
        SqliteStore(db, key=b"\x01" * 32)
    con = sqlite3.connect(db)
    rows = dict(con.execute("SELECT key, json FROM kv").fetchall())
    con.execute("UPDATE kv SET json=? WHERE key='history'", (rows["passport"],))        # move a row to another place
    con.commit()
    con.close()
    with pytest.raises(StoreError):
        api.Session(db, key_path=keys).store.load()


def test_old_plaintext_database_is_migrated_once_and_plaintext_rows_are_then_refused(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE kv (key TEXT PRIMARY KEY, json TEXT NOT NULL);"
                      "CREATE TABLE audit (i INTEGER PRIMARY KEY, json TEXT NOT NULL);"
                      "CREATE TABLE proofs (id TEXT PRIMARY KEY, json TEXT NOT NULL);"
                      "CREATE TABLE cards (id TEXT PRIMARY KEY, json TEXT NOT NULL);")
    con.execute("INSERT INTO kv VALUES ('passport', ?)", (json.dumps({"student": "Arjun the legacy student"}),))
    con.execute("INSERT INTO audit VALUES (0, ?)", (json.dumps({"i": 0, "kind": "x"}),))
    con.commit()
    con.close()
    assert b"legacy student" in db.read_bytes()
    st = SqliteStore(db, key=b"\x02" * 32)
    assert st.migrated_rows == 2
    assert st.load()["kv"]["passport"]["student"] == "Arjun the legacy student"
    st.close()
    assert b"legacy student" not in db.read_bytes()
    con = sqlite3.connect(db)
    con.execute("INSERT INTO kv VALUES ('evil', ?)", (json.dumps({"x": 1}),))             # injected plaintext row
    con.commit()
    con.close()
    st2 = SqliteStore(db, key=b"\x02" * 32)
    with pytest.raises(StoreError, match="plaintext"):
        st2.load()


def test_key_files_can_be_wrapped_with_a_passphrase(tmp_path, monkeypatch):
    p = tmp_path / "data_key.json"
    key = keyfile.load_or_create_secret(p)                                    # no passphrase: plaintext key file (documented)
    assert json.loads(p.read_text())["key"]
    monkeypatch.setenv("OASIS_KEY_PASSPHRASE", "correct horse")
    assert keyfile.load_or_create_secret(p) == key                            # upgraded in place
    assert "wrapped" in json.loads(p.read_text()) and "key" not in json.loads(p.read_text())
    assert keyfile.load_or_create_secret(p) == key
    monkeypatch.setenv("OASIS_KEY_PASSPHRASE", "wrong")
    with pytest.raises(ValueError, match="wrong OASIS_KEY_PASSPHRASE"):
        keyfile.load_or_create_secret(p)
    monkeypatch.delenv("OASIS_KEY_PASSPHRASE")
    with pytest.raises(ValueError, match="set OASIS_KEY_PASSPHRASE"):
        keyfile.load_or_create_secret(p)
    # the trust signing key is wrapped the same way and keeps its fingerprint
    from oasis.trust.keystore import load_or_create_signer, fingerprint
    monkeypatch.setenv("OASIS_KEY_PASSPHRASE", "pw")
    t = tmp_path / "trust_key.json"
    s1 = load_or_create_signer(t)
    assert "ed25519_seed" not in t.read_text()
    assert fingerprint(load_or_create_signer(t).public_keys()) == fingerprint(s1.public_keys())


# ======================================================================================= short-lived tool tokens
def _ledger(now):
    led = SandboxLedger(clock=lambda: now[0])
    led.open("a", "student", balance=1000)
    led.open("b", "payee")
    return led


def test_tool_token_is_single_use_bound_and_short_lived():
    now = [100.0]
    led = _ledger(now)
    issuer = led.executor_credential()
    tok = led.mint_tool_token(issuer, intent_id="int_1", from_ref="a", to_ref="b", amount=10.0)
    led.transfer(tok, "a", "b", 10.0, "CNY", intent_id="int_1")
    with pytest.raises(TokenError, match="already used"):                       # replay
        led.transfer(tok, "a", "b", 10.0, "CNY", intent_id="int_1")
    assert led.accounts["b"].balance == 10.0
    t2 = led.mint_tool_token(issuer, intent_id="int_2", from_ref="a", to_ref="b", amount=10.0, ttl_s=30)
    now[0] += 31
    with pytest.raises(TokenError, match="expired"):                            # expiry
        led.transfer(t2, "a", "b", 10.0, "CNY", intent_id="int_2")
    t3 = led.mint_tool_token(issuer, intent_id="int_3", from_ref="a", to_ref="b", amount=10.0)
    for kw in (dict(to_ref="c"), dict(amount=11.0), dict(intent_id="int_9"), dict(from_ref="b")):
        args = dict(from_ref="a", to_ref="b", amount=10.0, currency="CNY", intent_id="int_3") | kw
        with pytest.raises(TokenError, match="different transfer"):
            led.transfer(t3, args["from_ref"], args["to_ref"], args["amount"], args["currency"], intent_id=args["intent_id"])
    assert led.accounts["b"].balance == 10.0                                    # nothing moved on any refusal
    with pytest.raises(TokenError):
        led.transfer("tt_made_up", "a", "b", 1.0)
    with pytest.raises(TokenError):                                             # the issuer secret cannot pay, only mint
        led.transfer(issuer, "a", "b", 1.0)
    with pytest.raises(TokenError):
        led.mint_tool_token("not-the-issuer", intent_id="x", from_ref="a", to_ref="b", amount=1.0)


def test_executor_mints_a_token_per_payment_and_never_exposes_it():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    o = OasisAgent(w).handle(Request(tuition()), SimulatedHumans())
    assert o.status == "paid"
    blob = json.dumps([o.to_dict(), w.audit.entries, list(w.proofs.values())], default=str)
    assert "tt_" not in blob and w.ledger.executor_credential() not in blob     # the agent/LLM/outputs never carry a credential
    assert all(t["used"] for t in w.ledger._tokens.values()) and len(w.ledger._tokens) == 1     # exactly one token, for the one payment
    led = w.ledger
    with pytest.raises(TokenError):                                             # in a protected world the issuer secret cannot pay
        led.transfer(led.executor_credential(), "acct_student_cny", "6666000000000001", 1.0)


def test_the_unprotected_baseline_keeps_its_static_credential():
    w = World(Features.baseline(), OfflineLLM(susceptible=True))                # the thing the benchmark measures against
    w.ledger.accounts["acct_student_cny"].balance = 10
    w.ledger.transfer(w.ledger.executor_credential(), "acct_student_cny", "6228480000001234", 1.0)


def test_executor_payment_cannot_be_replayed_with_the_same_intent():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    a = OasisAgent(w)
    held = a.handle(Request(tuition()))
    req = a.sim_approve(Request(tuition()), held, ["student"])
    assert a.handle(req).status == "paid"
    again = a.handle(req)                                                       # the same signed approvals + nonce again
    assert again.status == "held" and again.decision["rule"] == "R17_duplicate_payment"   # first line of defence: duplicate hold
    req.pay_again = True                                                        # bypass it: the executor's replay check still stops it
    again = a.handle(req)
    assert again.status == "frozen" and any("replay" in t for t in again.trace)
    assert sum(1 for t in w.ledger.transfers if t.to_ref == "6228480000001234" and t.amount == 30000) == 1


# ======================================================================================= red-team console
@pytest.fixture
def judge_client(tmp_path):
    saved = api.S
    api.S = api.Session(":memory:", attempts_path=tmp_path / "attempts.jsonl")
    try:
        yield new_client("judge"), api.S
    finally:
        api.S = saved


def test_redteam_runs_only_in_its_own_sandbox_and_never_touches_the_main_ledger(judge_client):
    c, S = judge_client
    main_before = [(a.ref, a.balance) for a in S.world.ledger.accounts.values()]
    r = c.post("/api/redteam", json={"text": TUITION.replace("6228480000001234", "6228480000009999")}).json()
    assert r["status"] == "rejected" and r["money_lost_this_attempt"] == 0
    c.post("/api/redteam", json={"text": TUITION, "tool_poison": {"account_ref": "6666000000000002"}})
    assert S.world.ledger.transfers == [] and main_before == [(a.ref, a.balance) for a in S.world.ledger.accounts.values()]
    assert S.world.passport.obligation("obl_tuition_1").status == "pending"
    assert S.redteam_world.ledger is not S.world.ledger and S.redteam_world.audit is not S.world.audit


def test_redteam_rate_limit_and_size_limit(judge_client):
    c, S = judge_client
    now = [0.0]
    S.redteam_limiter = RateLimiter(20, 60.0, clock=lambda: now[0])
    codes = [c.post("/api/redteam", json={"text": "hello"}).status_code for _ in range(22)]
    assert codes[:20] == [200] * 20 and codes[20:] == [429, 429]
    now[0] += 61                                                              # the window slides
    assert c.post("/api/redteam", json={"text": "hello"}).status_code == 200
    assert c.post("/api/redteam", json={"text": "x" * 4001}).status_code == 413
    assert c.post("/api/redteam", json={"text": "hi", "tool_poison": {"account_ref": "9" * 500}}).status_code == 413
    assert c.post("/api/redteam", json={"text": "   "}).status_code == 400


def test_every_redteam_attempt_is_logged_to_the_attempts_store(judge_client, tmp_path):
    c, S = judge_client
    now = [0.0]
    S.redteam_limiter = RateLimiter(2, 60.0, clock=lambda: now[0])
    c.post("/api/redteam", json={"text": TUITION.replace("6228480000001234", "6228480000009999")})
    c.post("/api/redteam", json={"text": TUITION, "tool_poison": {"account_ref": "6666000000000002"}})
    c.post("/api/redteam", json={"text": "third attempt, rate limited"})
    c.post("/api/redteam", json={"text": "y" * 5000})
    lines = [json.loads(l) for l in (tmp_path / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["outcome"] for l in lines] == ["ran", "ran", "rate_limited", "rejected_too_large"]
    ran = lines[0]
    assert ran["status"] == "rejected" and ran["rule"] and ran["role"] == "judge" and ran["money_lost"] == 0
    assert "6228480000009999" in ran["text"] and len(ran["client"]) == 12 and ran["ts"]
    assert lines[1]["tool_poison"] == {"account_ref": "6666000000000002"} and lines[1]["status"] == "frozen"


def test_attempts_store_is_git_ignored():
    ig = (Path(__file__).resolve().parents[1] / ".gitignore").read_text()
    assert "redteam_attempts.jsonl" in ig and "data/keys/" in ig


# ======================================================================================= TCS message is data-driven
def test_tcs_warning_reads_the_rate_from_the_data_file(monkeypatch):
    from oasis.planning.scenarios import build_scenario_world
    from oasis.agent.planner import DeterministicPlanner, propose
    from oasis.trust import corridor
    w = build_scenario_world("parent_tcs")
    rec = propose(w, DeterministicPlanner())
    msg = next(x["message"] for x in rec["validation"]["warnings"] if x["code"] == "tcs")
    assert "2%" in msg and "INR 10 lakh" in msg
    rules = copy.deepcopy(corridor.load_rules())          # load_rules() is cached: never mutate the shared dict
    rules["rules"]["tcs_by_purpose"]["education"]["rate"] = 0.05
    rules["rules"]["tcs_by_purpose"]["threshold_inr"] = 700000
    monkeypatch.setattr(corridor, "load_rules", lambda *a, **k: rules)
    from oasis.planning.validator import validate_plan
    v = validate_plan(w, rec["steps"])
    msg2 = next(x["message"] for x in v.warnings if x["code"] == "tcs")
    assert "5%" in msg2 and "INR 7 lakh" in msg2 and "2%" not in msg2
    assert "UNCONFIRMED/secondary-sourced" in msg2                                   # secondary-sourced rows carry the tag
    rules["rules"]["tcs_by_purpose"]["education"]["status"] = "confirmed-primary"
    v = validate_plan(w, rec["steps"])
    assert "UNCONFIRMED" not in next(x["message"] for x in v.warnings if x["code"] == "tcs")   # a primary-confirmed row would not


def test_security_headers_on_api_and_static(api_client):
    for path in ("/api/health", "/"):
        h = api_client.get(path).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "script-src 'self'" in h["content-security-policy"]
        assert "unsafe-eval" not in h["content-security-policy"]
        assert "strict-transport-security" not in h      # plain http: HSTS would be wrong


def test_hsts_only_when_secure(api_client, monkeypatch):
    monkeypatch.setenv("OASIS_COOKIE_SECURE", "1")
    assert "max-age" in api_client.get("/api/health").headers["strict-transport-security"]
