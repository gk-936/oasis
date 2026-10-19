"""C1: a standing instruction for a recurring bill is a held draft; only the student's device-key signature creates it, and every automatic
run afterwards still goes through the pipeline (registry account, policy R10, executor) and is audited."""
import pytest

from tests.auth_helpers import Approver, new_client


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    return c


def _mandates(c):
    return c.get("/api/state").json()["passport"]["rules"]["mandates"]


def test_asking_for_a_recurring_payment_creates_only_a_draft(st):
    j = st.post("/api/chat", json={"message": "Set up a recurring payment for my phone bill"}).json()
    assert j["status"] == "held" and j["pending_id"] and j["money_moved"] == 0 and "moves no money" in j["reply"]
    assert _mandates(st) == []


def test_signing_creates_the_mandate_and_the_agent_then_pays_within_it(st):
    j = st.post("/api/chat", json={"message": "Set up a recurring payment for my phone bill"}).json()
    ap = Approver(st, "student")
    assert ap.approve(j["pending_id"]).json()["status"] == "paid"
    m = _mandates(st)
    assert len(m) == 1 and m[0]["cap_cny"] <= 500 and m[0]["payee_id"] == "payee_telecom"
    st.post("/api/autonomy/tick", json={"days": 40})
    acts = st.get("/api/activity").json()["acted_alone"]
    assert any(a["kind"] == "recurring_bill_paid" for a in acts)
    assert st.get("/api/state").json()["ledger_money_lost"] == 0


def test_a_wrong_signature_creates_no_mandate(st):
    j = st.post("/api/chat", json={"message": "Set up a recurring payment for my phone bill"}).json()
    ap = Approver(st, "student")
    forged = st.post("/api/approve", json={"pending_id": j["pending_id"], "signature": ap.device.sign("0" * 64), "key_id": ap.key_id})
    assert forged.status_code == 403 and _mandates(st) == []


def test_large_bills_are_not_eligible_for_a_mandate(st):
    j = st.post("/api/chat", json={"message": "pay my rent every month"}).json()
    assert j["status"] == "info" and not j["pending_id"] and "can't set" in j["reply"]


def test_a_bill_above_the_signed_cap_is_held_not_paid(st):
    import oasis.api.main as api
    j = st.post("/api/chat", json={"message": "Set up a recurring payment for my phone bill"}).json()
    Approver(st, "student").approve(j["pending_id"])
    ob = next(o for o in api.S.world.passport.obligations if o.id.startswith("obl_phone_1") and o.status == "pending")
    ob.amount = 400.0                                    # rises above the signed cap of 150
    st.post("/api/autonomy/tick", json={"days": 40})
    assert ob.status == "planned" and ob.amount_paid == 0


def test_a_rate_target_from_chat_is_a_draft_until_signed_then_converts_within_the_limit(st):
    j = st.post("/api/chat", json={"message": "convert 1500 when the rate reaches 0.0700"}).json()
    assert j["status"] == "held" and j["pending_id"] and j["money_moved"] == 0
    assert st.get("/api/state").json()["autonomy"]["targets"] == []
    ap = Approver(st, "student")
    forged = st.post("/api/approve", json={"pending_id": j["pending_id"], "signature": ap.device.sign("0" * 64), "key_id": ap.key_id})
    assert forged.status_code == 403 and st.get("/api/state").json()["autonomy"]["targets"] == []
    assert ap.approve(j["pending_id"]).json()["status"] == "paid"
    assert [t["rate"] for t in st.get("/api/state").json()["autonomy"]["targets"]] == [0.07]
    assert any(m["kind"] == "rate_target" for m in _mandates(st))
    st.post("/api/autonomy/tick", json={"days": 6})
    assert st.get("/api/state").json()["ledger_money_lost"] == 0
