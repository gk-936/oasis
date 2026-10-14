"""Approval tampering at the API: a signature must be valid, for this draft, from this role's device, once, and only while the draft is alive."""
import pytest

from tests.auth_helpers import Approver, new_client


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    c.post("/api/fx/convert", json={"amount": 450000, "from": "INR", "to": "CNY"})
    return c


def draft(c, msg="Pay my rent"):
    j = c.post("/api/chat", json={"message": msg}).json()
    assert j["status"] == "held" and j["pending_id"], j
    return j["pending_id"]


def n_proofs():
    from oasis.api import main as api
    return len(api.S.world.proofs)


def test_a_cancelled_draft_cannot_be_signed_afterwards(st):
    ap = Approver(st, "student")
    pid = draft(st)
    sig = ap.signature(pid)
    st.post("/api/chat", json={"message": "cancel"})
    r = st.post("/api/approve", json={"pending_id": pid, "signature": sig, "key_id": ap.key_id})
    assert r.status_code >= 400 and n_proofs() == 0


def test_a_signature_cannot_be_used_twice(st):
    ap = Approver(st, "student")
    pid = draft(st)
    sig = ap.signature(pid)
    assert st.post("/api/approve", json={"pending_id": pid, "signature": sig, "key_id": ap.key_id}).status_code == 200
    first = n_proofs()
    again = st.post("/api/approve", json={"pending_id": pid, "signature": sig, "key_id": ap.key_id})
    assert again.status_code >= 400 and n_proofs() == first == 1


def test_a_parent_device_signature_does_not_satisfy_a_student_draft(st):
    pid = draft(st)
    dh = st.get("/api/state").json()["pending"][0]["draft"]["draft_hash"]
    pap = Approver(new_client("parent"), "parent")
    r = st.post("/api/approve", json={"pending_id": pid, "signature": pap.device.sign(dh), "key_id": pap.key_id})
    assert r.status_code >= 400 and n_proofs() == 0


@pytest.mark.parametrize("bad", ["", "00", "A" * 400, "not-base64!!", "‮" + "ab" * 32, None])
def test_junk_signatures_are_refused(st, bad):
    ap = Approver(st, "student")
    pid = draft(st)
    r = st.post("/api/approve", json={"pending_id": pid, "signature": bad, "key_id": ap.key_id})
    assert r.status_code >= 400 and r.status_code < 500 and n_proofs() == 0


@pytest.mark.parametrize("key_id", ["nope", "../x", "A" * 300])
def test_junk_key_ids_are_refused(st, key_id):
    ap = Approver(st, "student")
    pid = draft(st)
    r = st.post("/api/approve", json={"pending_id": pid, "signature": ap.signature(pid), "key_id": key_id})
    assert 400 <= r.status_code < 500 and n_proofs() == 0


def test_an_unknown_pending_id_is_refused_without_a_server_error(st):
    ap = Approver(st, "student")
    r = st.post("/api/approve", json={"pending_id": "pend_doesnotexist", "signature": "ab" * 32, "key_id": ap.key_id})
    assert 400 <= r.status_code < 500


def test_extra_fields_in_the_approval_body_cannot_change_the_payment(st):
    ap = Approver(st, "student")
    pid = draft(st)
    r = ap.approve(pid, amount=1, payee_id="payee_attacker", account_ref="6666000000000002", draft_hash="0" * 64)
    assert r.status_code >= 400 or n_proofs() == 1
    from oasis.api import main as api
    assert api.S.world.ledger.money_lost() == 0
