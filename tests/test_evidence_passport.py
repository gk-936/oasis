"""Payment Evidence Passport: issue, offline verification of every signature, and tampered-field rejection. Hermetic."""
import copy

import pytest
from fastapi.testclient import TestClient

from auth_helpers import Approver
from eval.approver import SimulatedHumans
from eval.scenarios import tuition
from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.proof import evidence_passport as evp
from oasis.trust.crypto import HybridSigner
from oasis.trust.keystore import fingerprint
from oasis.world import Features, World


def _world():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    w.ledger.accounts["acct_student_cny"].balance += 100000
    w.sync_balances()
    r = OasisAgent(w).handle(Request(tuition()), SimulatedHumans())
    assert r.status == "paid"
    return w, r.proof_id


def _v(w, p, **kw):
    return evp.verify(p, {w.trust_fingerprint()}, {fingerprint(w.registry.issuer_public_keys())},
                      w.approvers.pinned_key_ids(), None, **kw)


def test_credited_passport_verifies_every_check():
    w, pid = _world()
    r = _v(w, evp.issue(w, pid))
    assert r["ok"] and r["status"] == "credited" and r["payee"]["payee_id"]
    assert r["audit_chain_linked"] and r["payment_in_chain"] and r["reconciliation_recomputed"] and r["payee_credential"]


@pytest.mark.parametrize("outcome,status", [("short", "short"), ("delayed", "delayed")])
def test_short_and_delayed_are_reported_honestly(outcome, status):
    w, pid = _world()
    r = _v(w, evp.issue(w, pid, outcome, today_day=10 if outcome == "delayed" else None))
    assert r["ok"] and r["status"] == status


def test_unknown_payment_and_bad_outcome():
    w, pid = _world()
    with pytest.raises(KeyError):
        evp.issue(w, "int_9999")
    with pytest.raises(ValueError):
        evp.issue(w, pid, "teleported")


def _mutations(p):
    def m(f):
        q = copy.deepcopy(p)
        f(q)
        return q
    return {
        "amount": m(lambda q: q["claim"].__setitem__("amount", 1)),
        "status": m(lambda q: q["claim"].__setitem__("status", "credited")),
        "payee": m(lambda q: q["claim"].__setitem__("payee_id", "evil")),
        "credited_cny": m(lambda q: q["reconciliation"]["journey"].__setitem__("credited_cny", 99999.0)),
        "finding": m(lambda q: q["reconciliation"]["finding"].__setitem__("code", "ok")),
        "account": m(lambda q: q["payee_credential"].__setitem__("account_ref", "ACCT-EVIL")),
        "intent": m(lambda q: q["proof_pack"]["intent"].__setitem__("amount", 1.0)),
        "audit_entry": m(lambda q: q["audit_inclusion"]["segment"][0]["data"].__setitem__("amount", 1)),
        "audit_head": m(lambda q: q["audit_inclusion"].__setitem__("head", "0" * 64)),
        "caveats": m(lambda q: q["caveats"].append("trust me")),
    }


def test_every_tampered_field_is_rejected():
    w, pid = _world()
    p = evp.issue(w, pid, "short")
    assert _v(w, p)["ok"]
    for name, q in _mutations(p).items():
        assert not _v(w, q)["ok"], name


def test_forger_resigning_fails_pins():
    w, pid = _world()
    forged = evp.issue(w, pid, signer=HybridSigner(key_id="forger"))
    r = _v(w, forged)
    assert r["signature"] and r["key_pinned"] is False and not r["ok"]
    assert evp.verify(evp.issue(w, pid))["ok"] is False        # no pins supplied: never "ok"


def test_unpinned_registry_issuer_fails():
    w, pid = _world()
    r = evp.verify(evp.issue(w, pid), {w.trust_fingerprint()}, {"deadbeef"}, w.approvers.pinned_key_ids())
    assert r["registry_pinned"] is False and not r["ok"]


def test_malformed_never_raises():
    for bad in (None, {}, {"type": evp.TYPE}, [], {"type": evp.TYPE, "public_keys": 1}):
        assert evp.verify(bad, set())["ok"] is False


def test_head_must_be_on_server_chain():
    w, pid = _world()
    p = evp.issue(w, pid)
    assert _v(w, p, head_known=lambda i, h: w.audit.entries[i]["hash"] == h)["ok"]
    assert not _v(w, p, head_known=lambda i, h: False)["ok"]


def test_api_flow_share_and_public_check(api_client):
    from oasis.api import main
    c = api_client
    o = c.post("/api/intake", json={"text": "Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
                                            "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15"}).json()
    pid = Approver(c, "student").approve(o["pending_id"]).json()["proof_id"]
    assert pid in [x["intent_id"] for x in c.get("/api/evidence-passport/payments").json()["payments"]]
    p = c.post("/api/evidence-passport/issue", json={"intent_id": pid, "outcome": "short"}).json()
    public = TestClient(main.app)
    assert public.post("/api/evidence-passport/verify", json=p).json()["ok"]
    code = c.post("/api/evidence-passport/share", json={"passport": p}).json()["code"]
    r = public.get(f"/api/evidence-passport/check/{code}").json()
    assert r["ok"] and r["status"] == "short" and r["head_on_server_chain"]
    bad = copy.deepcopy(p)
    bad["claim"]["amount"] = 1
    assert not public.post("/api/evidence-passport/verify", json=bad).json()["ok"]
    assert c.post("/api/evidence-passport/share", json={"passport": bad}).status_code == 400
    assert public.get("/api/evidence-passport/check/enope").status_code == 404
    assert public.post("/api/evidence-passport/issue", json={"intent_id": pid}).status_code in (401, 403)
