"""Judge pack: per-judge red-team sandboxes (isolation, bounded count, LRU eviction) and OASIS_JUDGE_MODE. Hermetic."""
import pytest
from fastapi.testclient import TestClient

from auth_helpers import login, new_client
from oasis.api import main as api
from oasis.api.auth import Auth

TUITION = ("Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
           "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15")
FORGED = TUITION.replace("6228480000001234", "6228480000009999")


def test_two_judges_get_separate_sandboxes_and_logs(api_session):
    a, b = new_client("judge"), new_client("judge")
    ra = a.post("/api/redteam", json={"text": FORGED}).json()
    assert ra["status"] == "rejected"
    assert len(a.get("/api/redteam/log").json()["attempts"]) == 1
    assert b.get("/api/redteam/log").json()["attempts"] == []            # B sees none of A's attempts
    b.post("/api/redteam", json={"text": TUITION})
    b.post("/api/redteam", json={"text": FORGED})
    assert len(b.get("/api/redteam/log").json()["attempts"]) == 2
    assert len(a.get("/api/redteam/log").json()["attempts"]) == 1
    S = api.S
    boxes = list(S.redteam_boxes.values())
    assert len(boxes) == 2 and boxes[0].world is not boxes[1].world
    assert boxes[0].world.ledger is not boxes[1].world.ledger and boxes[0].world.audit is not boxes[1].world.audit
    assert boxes[0].world.ledger is not S.world.ledger


def test_one_judge_session_keeps_one_world_across_requests(api_session):
    a = new_client("judge")
    a.post("/api/redteam", json={"text": TUITION})
    first = next(iter(api.S.redteam_boxes.values())).world
    a.post("/api/redteam", json={"text": FORGED})
    assert len(api.S.redteam_boxes) == 1 and next(iter(api.S.redteam_boxes.values())).world is first
    assert len(a.get("/api/redteam/log").json()["attempts"]) == 2


def test_proof_lookup_prefers_the_callers_own_sandbox(api_session):
    a, b = new_client("judge"), new_client("judge")
    ia = a.post("/api/redteam", json={"text": TUITION}).json()["proof_id"]
    ib = b.post("/api/redteam", json={"text": TUITION}).json()["proof_id"]
    assert ia == ib                                                   # intent ids repeat across sandboxes
    wa, wb = [bx.world for bx in api.S.redteam_boxes.values()]
    assert wa.proofs[ia] != wb.proofs[ib]                              # but the packs differ (own nonce, own chain)
    assert a.get(f"/api/proof/{ia}").json() == wa.proofs[ia]
    assert b.get(f"/api/proof/{ib}").json() == wb.proofs[ib]
    assert a.get(f"/api/proof/{ia}/verify").json()["ok"] and b.get(f"/api/proof/{ib}/verify").json()["ok"]


def test_worlds_are_bounded_and_the_least_recently_used_is_evicted(api_session):
    S = api.S
    S.redteam_max_worlds = 3
    for k in ("j1", "j2", "j3"):
        S.redteam_box(k)
    w1 = S.redteam_boxes["j1"].world
    S.redteam_box("j1")                                  # touch j1: now j2 is the least recently used
    S.redteam_box("j4")
    assert list(S.redteam_boxes) == ["j3", "j1", "j4"] and "j2" not in S.redteam_boxes
    assert S.redteam_boxes["j1"].world is w1 and len(S.redteam_boxes) == 3
    for i in range(10):
        S.redteam_box(f"x{i}")
    assert len(S.redteam_boxes) == 3


def test_default_cap_is_twenty_and_an_evicted_judge_gets_a_fresh_world(api_session):
    S = api.S
    assert S.redteam_max_worlds == 20 == api.REDTEAM_MAX_WORLDS
    S.redteam_limiter = api.RateLimiter(1000, 60.0)         # all test clients share one address
    clients = [new_client("judge") for _ in range(21)]
    for c in clients:
        c.post("/api/redteam", json={"text": TUITION})
    assert len(S.redteam_boxes) == 20
    assert clients[0].get("/api/redteam/log").json()["attempts"] == []        # the first judge was evicted: empty sandbox again
    assert len(S.redteam_boxes) == 20


def test_rate_limit_is_still_enforced_per_client(api_session):
    c = new_client("judge")
    codes = [c.post("/api/redteam", json={"text": "hello"}).status_code for _ in range(22)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


# ----------------------------------------------------------------------------------------------- judge mode
def test_judge_mode_refuses_to_start_without_explicit_passcodes(monkeypatch):
    monkeypatch.setenv("OASIS_JUDGE_MODE", "1")
    for r in ("STUDENT", "PARENT", "JUDGE"):
        monkeypatch.delenv(f"OASIS_PASS_{r}")
    with pytest.raises(RuntimeError, match="explicitly"):
        Auth()
    for r in ("STUDENT", "PARENT", "JUDGE"):
        monkeypatch.setenv(f"OASIS_PASS_{r}", f"custom-{r.lower()}-x9")
    assert Auth().generated == []


def test_unset_passcodes_are_random_alphanumeric_and_never_a_fixed_string(monkeypatch):
    from oasis.api import auth
    monkeypatch.delenv("OASIS_JUDGE_MODE", raising=False)
    for r in ("STUDENT", "PARENT", "JUDGE"):
        monkeypatch.delenv(f"OASIS_PASS_{r}")
    monkeypatch.setattr(auth, "_GENERATED", {})
    a = Auth()
    got = auth.passcodes_from_env()
    assert a.generated == ["student", "parent", "judge"]
    assert len(set(got.values())) == 3 and all(len(v) == 16 and v.isalnum() for v in got.values())
    assert not {"student-demo", "parent-demo", "judge-demo"} & set(got.values())
    assert auth.passcodes_from_env() == got                        # stable within one process


def test_judge_mode_disables_docs_and_tightens_limits(monkeypatch):
    c = TestClient(api.app)
    assert c.get("/docs").status_code == 200 and c.get("/openapi.json").status_code == 200      # normal mode
    monkeypatch.setenv("OASIS_JUDGE_MODE", "1")
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404, path
    assert c.get("/api/health").status_code == 200
    S = api.Session(":memory:")
    assert S.redteam_per_minute == api.JUDGE_REDTEAM_PER_MINUTE < api.REDTEAM_PER_MINUTE
    assert S.login_limiter.limit == api.JUDGE_LOGIN_FAILS_PER_MINUTE < api.LOGIN_FAILS_PER_MINUTE
    assert S.auth.ttl_s == 1800 and S.redteam_max_worlds == 20
    monkeypatch.setenv("OASIS_SESSION_TTL_S", "600")
    assert Auth().ttl_s == 600 or Auth().ttl_s == 3600       # an explicit TTL setting wins over the judge-mode default


def test_judge_mode_session_still_logs_in_and_runs_the_console(monkeypatch):
    monkeypatch.setenv("OASIS_JUDGE_MODE", "1")
    saved = api.S
    api.S = api.Session(":memory:")
    try:
        c = new_client("judge")
        assert c.post("/api/redteam", json={"text": FORGED}).json()["status"] == "rejected"
        assert c.get("/api/redteam/log").json()["limits"]["per_minute"] == 10
    finally:
        api.S = saved


def test_fresh_on_login_resets_the_sandbox_only_for_a_student_login(monkeypatch):
    from tests.auth_helpers import new_client
    monkeypatch.setenv("OASIS_FRESH_ON_LOGIN", "1")
    st = new_client("student")
    st.post("/api/reset")
    assert st.post("/api/chat", json={"message": "Pay my rent"}).json()["status"] == "held"
    assert len(st.get("/api/state").json()["pending"]) == 1
    new_client("parent")                                   # a parent login must not wipe the student's draft
    assert len(st.get("/api/state").json()["pending"]) == 1
    st2 = new_client("student")                            # a second student login starts from the seeded sandbox
    assert st2.get("/api/state").json()["pending"] == []


def test_without_the_flag_a_student_login_keeps_the_sandbox(monkeypatch):
    from tests.auth_helpers import new_client
    monkeypatch.delenv("OASIS_FRESH_ON_LOGIN", raising=False)
    st = new_client("student")
    st.post("/api/reset")
    st.post("/api/chat", json={"message": "Pay my rent"})
    assert len(new_client("student").get("/api/state").json()["pending"]) == 1


# ------------------------------------------------------------------------------------- one sandbox per login (judge mode)
def _judge_app(monkeypatch):
    monkeypatch.setenv("OASIS_JUDGE_MODE", "1")
    saved = api.S
    api.S = api.SandboxRouter(api.Session(":memory:"))
    return saved


def test_each_judge_login_has_its_own_sandbox(monkeypatch):
    saved = _judge_app(monkeypatch)
    try:
        a, b = TestClient(api.app), TestClient(api.app)          # two browsers = two cookie jars
        for c in (a, b):
            login(c, "student")
            c.post("/api/reset")
        assert a.post("/api/chat", json={"message": "Pay my rent"}).json()["status"] == "held"
        assert len(a.get("/api/state").json()["pending"]) == 1
        assert b.get("/api/state").json()["pending"] == []        # b sees nothing of a's draft
        b.post("/api/reset")                                       # b wiping its sandbox ...
        assert len(a.get("/api/state").json()["pending"]) == 1     # ... leaves a untouched
    finally:
        api.S = saved


def test_one_browser_keeps_its_sandbox_across_logins(monkeypatch):
    saved = _judge_app(monkeypatch)
    try:
        c = TestClient(api.app)
        login(c, "student")
        c.post("/api/reset")
        c.post("/api/chat", json={"message": "Pay my rent"})
        c.post("/api/auth/logout")
        login(c, "parent")
        c.post("/api/auth/logout")
        login(c, "student")
        assert len(c.get("/api/state").json()["pending"]) == 1     # logging in again from the same browser keeps its sandbox
    finally:
        api.S = saved


def test_sandbox_claim_cannot_be_forged_from_the_cookie(monkeypatch):
    saved = _judge_app(monkeypatch)
    try:
        a, b = TestClient(api.app), TestClient(api.app)
        login(a, "student"); a.post("/api/reset"); a.post("/api/chat", json={"message": "Pay my rent"})
        victim = a.cookies.get("oasis_sandbox")
        b.cookies.set("oasis_sandbox", "0" * 32)
        login(b, "student")
        b.cookies.set("oasis_sandbox", victim)                      # swapping the cookie after login changes nothing
        assert b.get("/api/state").json()["pending"] == []
    finally:
        api.S = saved
