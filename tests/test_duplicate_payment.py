"""R17 duplicate-payment protection: re-submitting an invoice that was already paid must not be payable by the normal
approve button; a deliberate second payment goes through an explicit "pay again" step and is signed like any approval."""
import pytest
from auth_helpers import Approver, login

from eval.approver import SimulatedHumans
from oasis.agent.duplicates import doc_hash, invoice_ref
from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.passport.models import Level
from oasis.trust.corridor import CorridorResult
from oasis.trust.policy import PolicyInput, decide
from oasis.world import Features, World

UNI, UNI_ACCT = "payee_univ_x", "6228480000001234"


def invoice(amount="CNY 30,000", extra="", due="2026-11-15"):
    return (f"INVOICE\nPayee: University X Finance Office\nPayee ID: {UNI}\nAccount: {UNI_ACCT}\nAmount: {amount}\n"
            f"Purpose: tuition\nDue: {due}\n{extra}")


def world():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    return w, OasisAgent(w)


def n_transfers(w, amount=None):
    return sum(1 for t in w.ledger.transfers if t.to_ref == UNI_ACCT and (amount is None or t.amount == amount))


# ------------------------------------------------------------------------------------------------- pipeline
def test_paid_invoice_resubmitted_is_held_with_a_why_card_and_no_approver():
    w, a = world()
    first = a.handle(Request(invoice()), SimulatedHumans())
    assert first.status == "paid" and first.proof_id
    again = a.handle(Request(invoice()), SimulatedHumans())               # even a simulated approver cannot release it
    assert again.status == "held" and again.decision["rule"] == "R17_duplicate_payment"
    assert again.decision["required_approvals"] == ["duplicate_confirmation"]
    assert again.duplicate["proof_id"] == first.proof_id
    assert first.proof_id in again.card["text"] and w.today.isoformat() in again.card["text"]
    assert "You already paid this" in again.card["text"]
    assert n_transfers(w, 30000) == 1


def test_same_obligation_different_wording_is_still_a_duplicate_via_the_paid_obligation():
    w, a = world()
    assert a.handle(Request(invoice()), SimulatedHumans()).status == "paid"
    o = a.handle(Request(invoice(extra="Second copy, sent again by email.")), SimulatedHumans())
    assert o.status == "held" and o.decision["rule"] == "R17_duplicate_payment"
    assert o.duplicate["kind"] == "paid_obligation" and o.duplicate["obligation_id"] == "obl_tuition_1"


def test_paid_obligation_without_payment_history_is_detected():
    w, a = world()
    w.passport.obligation("obl_tuition_1").status = "paid"                # seeded as paid, no history entry
    o = a.handle(Request(invoice()), SimulatedHumans())
    assert o.status == "held" and o.decision["rule"] == "R17_duplicate_payment" and not w.ledger.transfers


def test_same_invoice_reference_is_a_duplicate_even_if_the_amount_changed():
    w, a = world()
    assert a.handle(Request(invoice(extra="Invoice No: INV-2026-0042")), SimulatedHumans()).status == "paid"
    o = a.handle(Request(invoice(amount="CNY 12,000", extra="Invoice No: inv-2026-0042")), SimulatedHumans())
    assert o.status == "held" and o.decision["rule"] == "R17_duplicate_payment" and o.duplicate["kind"] == "invoice_ref"
    assert "INV-2026-0042" in o.card["text"]


def test_instalments_still_work_even_when_the_same_document_is_sent_twice():
    w, a = world()
    ob = w.passport.obligation("obl_tuition_1")
    half = invoice(amount="CNY 10,000")
    assert a.handle(Request(half), SimulatedHumans()).status == "paid" and ob.status == "partially_paid"
    o = a.handle(Request(half), SimulatedHumans())                        # same text, same obligation, still owed
    assert o.status == "paid" and o.duplicate is None and ob.amount_paid == 20000
    o = a.handle(Request(invoice(amount="CNY 10,000", extra="Last part")), SimulatedHumans())
    assert o.status == "paid" and ob.status == "paid"
    assert n_transfers(w, 10000) == 3


def test_a_new_invoice_for_the_same_payee_is_not_a_duplicate():
    w, a = world()
    assert a.handle(Request(invoice()), SimulatedHumans()).status == "paid"
    other = invoice(amount="CNY 1,200", due="2026-12-01").replace("tuition", "living")
    o = a.handle(Request(other), SimulatedHumans())
    assert o.duplicate is None and (o.decision or {}).get("rule") != "R17_duplicate_payment"


def test_scheduled_recurring_bills_are_not_checked():
    w, a = world()
    text = invoice(amount="CNY 300")
    assert a.handle(Request(text, recurring=True), SimulatedHumans()).duplicate is None
    assert a.handle(Request(text, recurring=True), SimulatedHumans()).duplicate is None


def test_pay_again_needs_the_students_signature_then_pays_once_more():
    w, a = world()
    assert a.handle(Request(invoice()), SimulatedHumans()).status == "paid"
    w.ledger.accounts["acct_student_cny"].balance += 30000                # enough funds for a second payment
    req = Request(invoice(), pay_again=True)
    held = a.handle(req)                                                  # explicit pay-again, but no signature yet
    assert held.status == "held" and held.decision["required_approvals"] == ["student"]
    assert held.decision["rule"] == "R17_duplicate_payment" and "second payment" in " ".join(held.decision["reasons"])
    assert n_transfers(w, 30000) == 1
    req = a.sim_approve(req, held, ["student"])
    o = a.handle(req)
    assert o.status == "paid" and n_transfers(w, 30000) == 2
    assert o.proof_id != held.duplicate["proof_id"]


def test_pay_again_with_a_signature_for_another_draft_does_not_pay():
    w, a = world()
    assert a.handle(Request(invoice()), SimulatedHumans()).status == "paid"
    other = a.handle(Request(invoice(amount="CNY 29,999")))               # a different draft
    req = Request(invoice(), pay_again=True)
    held = a.handle(req)
    sig_for_other = a.sim_approve(Request(invoice(amount="CNY 29,999")), other, ["student"]).signed_approvals
    req.draft = {"nonce": held.draft["nonce"], "not_after": held.draft["not_after"]}
    req.signed_approvals = sig_for_other
    o = a.handle(req)
    assert o.status == "held" and n_transfers(w, 30000) == 1 and o.rejected_approvals


# ------------------------------------------------------------------------------------------------- policy unit
def _pi(w, **kw):
    rec = w.passport.recipients[UNI]
    rec.verification.level = Level.VERIFIED_FULL
    rec.verification.limit_cny = 1e6
    base = dict(passport=w.passport, recipient=rec, payee_id=UNI, purpose="tuition", amount_cny=30000, amount_inr=400000,
                corridor=CorridorResult())
    base.update(kw)
    return PolicyInput(**base)


def test_policy_duplicate_hold_precedes_everything_but_freezes_and_verification():
    w, _ = world()
    dup = {"why": "You already paid this on 2026-10-01, proof int_0001: it is the same document."}
    d = decide(_pi(w, duplicate=dup, approvals=("student", "parent")))
    assert d.action == "hold" and d.rule == "R17_duplicate_payment" and d.required_approvals == ["duplicate_confirmation"]
    assert "int_0001" in d.reasons[0]
    d = decide(_pi(w, duplicate=dup, pay_again=True))
    assert d.action == "hold" and d.required_approvals == ["student"]
    d = decide(_pi(w, duplicate=dup, pay_again=True, approvals=("student",)))
    assert d.action == "allow"
    d = decide(_pi(w, duplicate=dup, canary_hits=[type("H", (), {"kind": "k", "where": "w"})()]))
    assert d.action == "freeze"
    assert decide(_pi(w)).action == "hold" and decide(_pi(w)).rule == "R11_approval_required"     # no duplicate: unchanged


def test_invoice_reference_and_document_hash_helpers():
    assert invoice_ref("Invoice No: ab-123/9\nAmount: 5") == "AB-123/9"
    assert invoice_ref("Invoice #INV0042") == "INV0042" and invoice_ref("发票号码：FP2026001") == "FP2026001"
    assert invoice_ref("Payee: X\nAmount: 5") is None
    assert doc_hash("A  b\n c") == doc_hash("a b c") and doc_hash("a") != doc_hash("b")


# ------------------------------------------------------------------------------------------------- HTTP flow
def _pay_via_api(c, text=None):
    text = text or invoice()
    o = c.post("/api/intake", json={"text": text}).json()
    assert o["status"] == "held" and o["pending_id"]
    me = Approver(c, "student") if not hasattr(c, "_me") else c._me
    c._me = me
    r = me.approve(o["pending_id"])
    assert r.status_code == 200 and r.json()["status"] == "paid", r.text
    return r.json()


def test_api_duplicate_cannot_be_approved_pay_again_is_signed_and_pays_once_more(api_client, api_session):
    c = api_client
    first = _pay_via_api(c)
    dup = c.post("/api/intake", json={"text": invoice()}).json()
    assert dup["status"] == "held" and dup["decision"]["rule"] == "R17_duplicate_payment"
    assert dup["pending_id"] and first["proof_id"] in dup["card"]["text"]
    me = c._me
    # the normal approve button cannot release it, with or without a signature
    assert c.post("/api/approve", json={"pending_id": dup["pending_id"]}).status_code == 403
    r = c.post("/api/approve", json={"pending_id": dup["pending_id"], "signature": me.device.sign("0" * 64), "key_id": me.key_id})
    assert r.status_code == 403 and "Pay again" in r.json()["detail"]
    assert n_transfers(api_session.S.world, 30000) == 1
    view = {p["id"]: p for p in c.get("/api/state").json()["pending"]}[dup["pending_id"]]
    assert view["required"] == ["duplicate_confirmation"] and view["duplicate"]["proof_id"] == first["proof_id"]
    # explicit pay-again -> a new signable draft that carries the duplicate warning
    pa = c.post("/api/pay-again", json={"pending_id": dup["pending_id"]}).json()
    assert pa["status"] == "held" and pa["decision"]["required_approvals"] == ["student"] and pa["pending_id"] != dup["pending_id"]
    assert dup["pending_id"] not in {p["id"] for p in c.get("/api/state").json()["pending"]}
    view = {p["id"]: p for p in c.get("/api/state").json()["pending"]}[pa["pending_id"]]
    assert view["duplicate"]["proof_id"] == first["proof_id"] and view["pay_again"] is True
    bad = c.post("/api/approve", json={"pending_id": pa["pending_id"], "signature": me.device.sign("1" * 64), "key_id": me.key_id})
    assert bad.status_code == 403 and n_transfers(api_session.S.world, 30000) == 1
    api_session.S.world.ledger.accounts["acct_student_cny"].balance += 30000
    ok = me.approve(pa["pending_id"])
    assert ok.status_code == 200 and ok.json()["status"] == "paid" and ok.json()["proof_id"] != first["proof_id"]
    assert n_transfers(api_session.S.world, 30000) == 2
    assert [e for e in api_session.S.world.audit.entries if e["kind"] == "pay_again_requested"]


def test_api_pay_again_is_student_only_and_only_for_duplicate_holds(api_client, as_role):
    _pay_via_api(api_client)
    dup = api_client.post("/api/intake", json={"text": invoice()}).json()
    assert as_role("parent").post("/api/pay-again", json={"pending_id": dup["pending_id"]}).status_code == 403
    assert as_role("judge").post("/api/pay-again", json={"pending_id": dup["pending_id"]}).status_code == 403
    assert api_client.post("/api/pay-again", json={"pending_id": "pend_nope"}).status_code == 404
    other = api_client.post("/api/intake", json={"text": invoice(amount="CNY 12,000")}).json()
    assert other["pending_id"] and api_client.post("/api/pay-again", json={"pending_id": other["pending_id"]}).status_code == 409


def test_api_duplicate_hold_can_be_dismissed(api_client, api_session):
    _pay_via_api(api_client)
    dup = api_client.post("/api/intake", json={"text": invoice()}).json()
    r = api_client.post("/api/approve", json={"pending_id": dup["pending_id"], "approve": False})
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert dup["pending_id"] not in api_session.S.pending and n_transfers(api_session.S.world, 30000) == 1


def test_api_pay_again_survives_a_save_and_restore(api_client, api_session, tmp_path):
    _pay_via_api(api_client)
    dup = api_client.post("/api/intake", json={"text": invoice()}).json()
    pa = api_client.post("/api/pay-again", json={"pending_id": dup["pending_id"]}).json()
    from oasis.api.main import _request_from, _request_to
    item = api_session.S.pending[pa["pending_id"]]
    assert _request_from(_request_to(item["request"])).pay_again is True


def test_auth_me_is_a_200_probe_when_logged_out(api_session):
    from fastapi.testclient import TestClient
    c = TestClient(api_session.app)
    r = c.get("/api/auth/me")
    assert r.status_code == 200 and r.json() == {"role": None}
    login(c, "judge")
    assert c.get("/api/auth/me").json()["role"] == "judge"
