"""A6: conversions chat cannot confirm on its own (another pair, above the Tier-1 limit, 'convert all') become held drafts that only the
student's device-key signature releases. They touch the student's own wallets only and can never pay anyone."""
import pytest

from tests.auth_helpers import Approver, new_client


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    return c


def _bal(c):
    return {b["currency"]: b["amount"] for b in c.get("/api/state").json()["passport"]["balances"]}


def test_large_conversion_is_a_held_draft_and_moves_nothing_until_signed(st):
    before = _bal(st)
    j = st.post("/api/chat", json={"message": "Convert 90000 INR to CNY"}).json()
    assert j["status"] == "held" and j["pending_id"] and j["money_moved"] == 0 and "nobody is paid" in j["reply"]
    assert _bal(st) == before
    ap = Approver(st, "student")
    r = ap.approve(j["pending_id"])
    assert r.status_code == 200 and r.json()["status"] == "paid"
    after = _bal(st)
    assert after["INR"] == before["INR"] - 90000 and after["CNY"] > before["CNY"]
    assert st.get("/api/state").json()["ledger_money_lost"] == 0
    assert st.post("/api/approve", json={"pending_id": j["pending_id"], "signature": "x", "key_id": ap.key_id}).status_code == 404     # single use


def test_a_wrong_signature_does_not_convert(st):
    j = st.post("/api/chat", json={"message": "Convert 90000 INR to CNY"}).json()
    ap = Approver(st, "student")
    other = Approver(new_client("student"), "student")
    bad = st.post("/api/approve", json={"pending_id": j["pending_id"], "signature": other.device.sign(j["draft_hash"]), "key_id": ap.key_id})
    assert bad.status_code == 403 and _bal(st)["INR"] == 500000
    forged = st.post("/api/approve", json={"pending_id": j["pending_id"], "signature": ap.device.sign("0" * 64), "key_id": ap.key_id})
    assert forged.status_code == 403 and _bal(st)["INR"] == 500000


def test_the_parent_cannot_release_a_student_conversion(st):
    j = st.post("/api/chat", json={"message": "Convert 90000 INR to CNY"}).json()
    parent = new_client("parent")
    pa = Approver(parent, "parent")
    assert parent.post("/api/approve", json={"pending_id": j["pending_id"], "signature": pa.device.sign(j["draft_hash"]), "key_id": pa.key_id}).status_code == 403


def test_convert_all_states_the_real_balance_and_other_pairs_are_drafts(st):
    j = st.post("/api/chat", json={"message": "Convert all my INR to CNY"}).json()
    assert j["status"] == "held" and "500,000.00 INR" in j["reply"]
    st.post("/api/fx/convert", json={"amount": 20000, "from": "INR", "to": "USD"})
    k = st.post("/api/chat", json={"message": "Convert 100 USD to EUR"}).json()
    assert k["status"] == "held" and "USD to EUR" in k["reply"]


def test_converting_money_you_do_not_have_makes_no_draft(st):
    j = st.post("/api/chat", json={"message": "Convert 100 USD to EUR"}).json()
    assert j["status"] == "rejected" and not j["pending_id"] and "not enough USD" in j["reply"]


def test_small_inr_to_cny_stays_tier_one(st):
    j = st.post("/api/chat", json={"message": "convert 20000 INR to CNY"}).json()
    assert j["status"] == "needs_confirmation" and not j["pending_id"]
