"""Foreign-currency plans over the extra corridors: validator, deterministic planner, API, and no change to the CNY planner. Hermetic."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from oasis.agent.llm import OfflineLLM
from oasis.agent.planner import DeterministicFxPlanner, DeterministicPlanner
from oasis.agent.plan_exec import accept_plan, execute_due
from oasis.passport.models import Obligation, Recipient
from oasis.planning import fxplan
from oasis.planning.validator import validate_plan
from oasis.world import Features, World


def _world(usd=5000.0, inr=700000.0, cny=0.0, due="2026-11-20", cur="USD"):
    w = World(Features.full(), OfflineLLM(susceptible=True))
    p = w.passport
    p.set_balance("INR", inr)
    p.set_balance("CNY", cny)
    p.recipients["payee_us_univ"] = Recipient(id="payee_us_univ", name="US University", payee_type="university", account_ref="US-0001")
    p.obligations.append(Obligation(id="obl_us_tuition", type="tuition", payee_id="payee_us_univ", amount=usd, currency=cur, due=due))
    return w


def test_deterministic_plan_is_valid_and_funds_the_obligation():
    w = _world()
    res = DeterministicFxPlanner().plan(w)
    assert res.valid, res.validation["errors"]
    conv = [s for s in res.steps if s["action"] == "convert"]
    pay = [s for s in res.steps if s["action"] == "pay"]
    assert len(conv) == 1 and conv[0]["corridor"] == "INR-USD" and len(pay) == 1 and pay[0]["amount"] == 5000
    m = res.validation["metrics"]
    assert m["deadlines_met"] == 1 and m["saved_vs_bank_usd_equivalent"] > 0
    assert any(x["code"] == "price_estimate" or x["code"] == "rule_note" for x in res.validation["warnings"])


def test_eur_obligation_uses_an_eur_corridor():
    w = _world(usd=3000.0, cur="EUR")
    res = DeterministicFxPlanner().plan(w)
    assert res.valid and [s["corridor"] for s in res.steps if s["action"] == "convert"] == ["INR-EUR"]


def test_no_conversion_when_balance_covers_it():
    w = _world()
    w.credit_fx("USD", 6000.0)
    res = DeterministicFxPlanner().plan(w)
    assert res.valid and not [s for s in res.steps if s["action"] == "convert"]


def test_validator_catches_errors():
    w = _world()
    ok = DeterministicFxPlanner().plan(w).steps
    def codes(steps):
        return {e["code"] for e in fxplan.validate_fx_plan(w, steps).errors}
    pay = next(s for s in ok if s["action"] == "pay")
    conv = next(s for s in ok if s["action"] == "convert")
    assert "obligation_unfunded" in codes([conv])
    assert "insufficient_dst" in codes([{**conv, "send": 1000.0}, pay])
    assert "amount_mismatch" in codes([conv, {**pay, "amount": 4000}])
    assert "unknown_corridor" in codes([{**conv, "corridor": "INR-JPY"}, pay])
    assert "unknown_corridor" in codes([{**conv, "corridor": "INR-CNY"}, pay])
    assert "insufficient_funds" in codes([{**conv, "send": 9_000_000.0}, pay])
    assert "late_payment" in codes([conv, {**pay, "date": "2026-12-30"}])
    slow = {**conv, "date": pay["date"]}
    assert codes([slow, {**pay, "date": pay["date"]}]) <= {"route_too_slow", "insufficient_dst"} and codes([slow, pay])


def test_parent_remitter_when_student_inr_is_short():
    w = _world(inr=100000.0)
    res = DeterministicFxPlanner().plan(w)
    assert res.valid and any(s.get("remitter") == "parent" for s in res.steps if s["action"] == "convert")
    assert any(x["code"] == "parent_remitter" for x in res.validation["warnings"])


def test_lrs_limit_is_enforced():
    w = _world(usd=300000.0, inr=40_000_000.0, due="2026-12-20")
    v = DeterministicFxPlanner().plan(w).validation
    assert not v["valid"] and "lrs_exceeded" in {e["code"] for e in v["errors"]}


def test_cny_planner_ignores_foreign_obligations_and_is_unchanged():
    w = _world()
    res = DeterministicPlanner().plan(w)
    assert res.valid and all("obl_us_tuition" not in str(s) for s in res.steps)
    assert fxplan.has_foreign(w) and not fxplan.has_foreign(World(Features.full(), OfflineLLM(susceptible=True)))


def test_toolbox_protocol():
    w = _world()
    tb = fxplan.FxToolbox(w)
    facts = tb.call("fx_facts")
    assert facts["shortfall"] == {"USD": 5000.0} and any(c["corridor"] == "INR-USD" for c in facts["corridors"])
    r = facts["corridors"][0]["routes"][0]["route_id"]
    s = tb.call("fx_size_conversion", {"target": 5000, "corridor": "INR-USD", "route_id": r, "convert_date": "2026-10-14", "due": "2026-11-20"})
    assert s["delivered_worst_case"] >= 5000 and s["on_time"]
    assert "error" in tb.call("not_a_tool")
    assert "error" in tb.call("fx_size_conversion", {"target": 5, "corridor": "INR-USD", "route_id": "zzz", "convert_date": "2026-10-14"})


class _ScriptedLLM:
    """A fake tool-calling model: reads the facts, sizes the conversion with the calculator, proposes, then stops."""
    name = "bedrock"

    def __init__(self, bad_first=False):
        self.n, self.bad_first, self.errors = 0, bad_first, []
        self.facts = None

    def chat_tools(self, msgs, specs):
        self.n += 1
        assert [t["function"]["name"] for t in specs] == ["fx_facts", "fx_size_conversion", "propose_plan"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        if self.n == 1:
            return {"content": "", "tool_calls": [{"id": "1", "name": "fx_facts", "arguments": {}}], "tokens": 10, "model": "fake"}
        import json
        if self.n == 2:
            self.facts = json.loads(tool_msgs[-1]["content"])
            c = self.facts["corridors"][0]
            return {"content": "", "tool_calls": [{"id": "2", "name": "fx_size_conversion", "arguments": {
                "target": self.facts["shortfall"]["USD"], "corridor": c["corridor"], "route_id": c["routes"][-1]["route_id"],
                "convert_date": self.facts["today"], "due": self.facts["obligations"][0]["due"]}}], "tokens": 10, "model": "fake"}
        sized = json.loads(tool_msgs[-1]["content"])
        ob = self.facts["obligations"][0]
        conv = {"action": "convert", "date": self.facts["today"], "corridor": sized["corridor"], "route_id": sized["route_id"],
                "send": sized["send"] - (5000 if self.bad_first and self.n == 3 else 0), "remitter": "student"}
        pay = {"action": "pay", "date": ob["due"], "obligation_id": ob["id"], "payee_id": ob["payee_id"], "amount": ob["amount"]}
        return {"content": "", "tool_calls": [{"id": str(self.n), "name": "propose_plan", "arguments": {"steps": [conv, pay], "rationale": "sized with the calculator"}}],
                "tokens": 10, "model": "fake"}


def test_live_planner_loop_with_a_scripted_model():
    from oasis.agent.planner import AgenticFxPlanner
    res = AgenticFxPlanner(_ScriptedLLM()).plan(_world())
    assert res.valid and not res.fell_back and res.planner == "bedrock-fx-tools" and res.model_calls == 3


def test_live_planner_falls_back_when_the_model_proposes_garbage():
    from oasis.agent.planner import AgenticFxPlanner

    class Bad(_ScriptedLLM):
        def chat_tools(self, msgs, specs):
            return {"content": "I cannot help", "tool_calls": [], "tokens": 5, "model": "fake"}
    res = AgenticFxPlanner(Bad()).plan(_world())
    assert res.fell_back and res.valid and res.planner == "deterministic (fallback)"


# ----------------------------------------------------------------------------------------------------- execution
from eval.approver import SimulatedHumans            # noqa: E402
from oasis.agent.pipeline import OasisAgent, Request    # noqa: E402
from oasis.agent.planner import build_fx_record      # noqa: E402
from oasis.agent.plan_exec import get_plan, sim_parent_consent, step_statuses     # noqa: E402
from oasis.agent import fx_exec                      # noqa: E402
from oasis.proof.pack import verify_proof_pack       # noqa: E402


def _funded(**kw):
    """A world with a registry-issued US university and a USD 5,000 bill (the same path the demo endpoint uses)."""
    w = World(Features.full(), OfflineLLM(susceptible=True), seed=7, deterministic=True)
    w.passport.set_balance("INR", kw.get("inr", 700000.0))
    fx_exec.add_demo_obligation(w, "us", kw.get("usd", 5000.0), 38)
    return w, OasisAgent(w)


def _run_to_paid(w, agent, rec, approver):
    assert "error" not in accept_plan(agent, rec["id"])
    r1 = execute_due(agent, rec["id"], approver)
    w.advance(days=40)                              # the pay step is dated shortly before the due date
    r2 = execute_due(agent, rec["id"], approver)
    return r1, r2


def test_fx_plan_executes_end_to_end_with_a_verifiable_proof():
    w, agent = _funded()
    rec = build_fx_record(w, DeterministicFxPlanner().plan(w))
    assert rec["kind"] == "fx" and rec["status"] == "proposed"
    _run_to_paid(w, agent, rec, SimulatedHumans())
    ob = w.passport.obligation("obl_fx_1")
    assert ob.status == "paid" and get_plan(w, rec["id"])["status"] == "done"
    assert w.ledger.accounts["US-UNIV-USD-0001"].balance == 5000.0 and w.ledger.accounts["acct_student_usd"].balance < 5.0
    assert w.ledger.accounts["US-UNIV-USD-0001"].currency == "USD"
    tr = w.ledger.transfers[-1]
    assert tr.currency == "USD" and tr.to_ref == "US-UNIV-USD-0001"
    pack = w.proofs[tr.intent_id]
    assert pack["intent"]["currency"] == "USD" and pack["decision"]["rule"] == "R19_fx_approved"
    assert verify_proof_pack(pack, {w.trust_fingerprint()}, w.anchor, w.approvers.pinned_key_ids())["ok"]
    assert [x["status"] for x in step_statuses(w, get_plan(w, rec["id"]))] == ["done", "done"]
    assert w.passport.remitted_inr_fy["student"] > 0                     # the INR remittance counts against the student's LRS


def test_without_the_students_signature_nothing_is_paid():
    w, agent = _funded()
    rec = build_fx_record(w, DeterministicFxPlanner().plan(w))
    accept_plan(agent, rec["id"])
    execute_due(agent, rec["id"], None)
    w.advance(days=40)
    res = execute_due(agent, rec["id"], None)            # no approver, no signature
    assert w.passport.obligation("obl_fx_1").status == "pending" and w.ledger.accounts["US-UNIV-USD-0001"].balance == 0
    assert res["ran"][-1]["status"] == "awaiting_approval" and len(res["held"]) == 1
    req, held = res["held"][0]
    assert held.decision["rule"] == "R18_fx_approval_required"
    req.approvals = ("student",)                          # a bare role string is not an approval
    again = agent.handle(req)
    assert again.status == "held" and w.ledger.accounts["US-UNIV-USD-0001"].balance == 0
    req = agent.sim_approve(req, held, ["student"])       # a device signature over the exact draft is
    done = agent.handle(req)
    assert done.status == "paid" and w.ledger.accounts["US-UNIV-USD-0001"].balance == 5000.0


def test_payee_account_always_comes_from_the_registry():
    w, agent = _funded()
    w.passport.recipients["payee_us_univ"].account_ref = "6666000000000001"      # a tampered Passport record (an attacker account)
    out = agent.handle(Request("", fx={"obligation_id": "obl_fx_1"}), SimulatedHumans())
    assert out.status == "rejected" and w.ledger.accounts["6666000000000001"].balance == 0


def test_executor_and_ledger_enforce_the_currency():
    from oasis.trust.policy import Decision
    w, _ = _funded()
    w.credit_fx("USD", 100)
    payload = {"payee_id": "payee_us_univ", "account_ref": "US-UNIV-USD-0001", "amount": 100.0, "currency": "USD", "route_id": "route_fx_settlement"}
    decide = lambda roles: Decision("allow", 2, "test", [])
    na = w.now.replace(hour=23, minute=59).isoformat()
    intent = w.builder.build(student_id="stu_001", purpose="tuition", tier=2, not_after=na, approvals=[], **payload)
    swapped = dict(payload, currency="CNY")                               # the payload no longer matches the signed intent
    assert w.executor.execute(intent, swapped, decide, "acct_student_usd").status == "frozen"
    i2 = w.builder.build(student_id="stu_001", purpose="tuition", tier=2, not_after=na, approvals=[], **payload)
    with pytest.raises(ValueError, match="currency mismatch"):            # the ledger refuses USD out of a CNY account
        w.executor.execute(i2, payload, decide, "acct_student_cny")


def test_decide_fx_is_never_automatic():
    from oasis.passport.models import Level
    from oasis.trust.policy import FxPolicyInput, decide_fx
    w, _ = _funded()
    p = w.passport
    rec = p.recipients["payee_us_univ"]

    def mk(**k):
        return decide_fx(FxPolicyInput(p, k.pop("rec", rec), "payee_us_univ", "tuition", k.pop("amount", 5000.0), "USD",
                                       k.pop("cny", 33000.0), k.pop("hits", []), k.pop("appr", ()), k.pop("paid", 0.0)))
    assert mk().action == "hold" and mk().rule == "R18_fx_approval_required"
    assert mk(appr=("parent",)).action == "hold"                           # the parent cannot approve the student's payment
    assert mk(appr=("student",)).action == "allow"
    assert mk(cny=1e9, appr=("student",)).action == "freeze"               # hard limit
    assert mk(rec=None, appr=("student",)).rule == "R05_unverified"
    assert mk(hits=[type("H", (), {"kind": "x", "where": "y"})()]).rule == "R01_canary"
    rec.verification.level = Level.REJECTED
    assert mk(appr=("student",)).rule == "R03_rejected_recipient"


def test_parent_remitted_conversion_needs_a_signed_consent():
    w, agent = _funded(inr=100000.0)
    rec = build_fx_record(w, DeterministicFxPlanner().plan(w))
    assert any(s.get("remitter") == "parent" for s in rec["steps"])
    accept_plan(agent, rec["id"])
    r1 = execute_due(agent, rec["id"], SimulatedHumans())
    assert r1["ran"][0]["status"] == "awaiting_parent_consent" and w.ledger.accounts["acct_student_usd"].balance == 0
    assert sim_parent_consent(agent, rec["id"]) == 1
    execute_due(agent, rec["id"], SimulatedHumans())
    assert w.ledger.accounts["acct_student_usd"].balance > 4900 and w.passport.remitted_inr_fy.get("parent", 0) > 0


def test_invalid_demo_bills_are_refused():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    for kind, amt, days in (("jp", 100, 5), ("us", 0, 5), ("us", 1e9, 5), ("us", 100, 9999)):
        with pytest.raises(ValueError):
            fx_exec.add_demo_obligation(w, kind, amt, days)


def test_api_end_to_end_with_device_signature(api_client, as_role):
    from auth_helpers import Approver
    assert api_client.post("/api/plan/fx", json={}).status_code == 400       # nothing owed in a foreign currency yet
    assert api_client.post("/api/fx/demo-obligation", json={"kind": "jp", "amount": 100}).status_code == 400
    assert as_role("parent").post("/api/fx/demo-obligation", json={"kind": "us", "amount": 100}).status_code == 403
    ob = api_client.post("/api/fx/demo-obligation", json={"kind": "us", "amount": 2000, "days": 3}).json()
    assert ob["currency"] == "USD" and ob["payee_id"] == "payee_us_univ"
    plan = api_client.post("/api/plan/fx", json={}).json()
    assert plan["kind"] == "fx" and plan["valid"] and plan["status"] == "proposed"
    pid = plan["id"]
    assert as_role("parent").post(f"/api/plan/{pid}/accept").status_code == 403
    assert api_client.post(f"/api/plan/{pid}/accept").json()["status"] == "accepted"
    ex = api_client.post(f"/api/plan/{pid}/execute").json()
    assert ex["steps"][0]["status"] == "done"
    from oasis.api import main as api
    if not ex["pending_ids"]:                                                # the pay step is dated later: move the clock
        api.S.world.advance(days=3)
        ex = api_client.post(f"/api/plan/{pid}/execute").json()
    assert len(ex["pending_ids"]) == 1
    pend = ex["pending_ids"][0]
    student = Approver(api_client, "student")
    bad = api_client.post("/api/approve", json={"pending_id": pend, "signature": "00" * 64, "key_id": student.key_id})
    assert bad.status_code == 403                                            # a forged signature pays nothing
    ok = student.approve(pend)
    assert ok.status_code == 200 and ok.json()["status"] == "paid"
    assert api.S.world.passport.obligation(ob["id"]).status == "paid" and api.S.world.ledger.accounts["US-UNIV-USD-0001"].balance == 2000.0


def test_live_runner_row_and_report_offline(tmp_path, monkeypatch):
    """The live evaluation's plumbing, exercised with a scripted model (no network, no tokens)."""
    from eval import fxplan_live as fl
    from oasis.agent.planner import AgenticFxPlanner
    monkeypatch.setattr(fl, "REPORTS", tmp_path)
    monkeypatch.setattr(fl, "ROWS", tmp_path / "fxplan_live.json")
    row = fl.run_scenario("usd_from_inr", AgenticFxPlanner(_ScriptedLLM()))
    assert row["model_valid_without_fallback"] and row["tokens"] == 30 and row["tools_called"][:2] == ["fx_facts", "fx_size_conversion"]
    assert not fl.is_budget_artifact(row)
    fl.save([{**row, "run_date": "2026-10-13"}])
    fl.report()
    assert "usd_from_inr" in (tmp_path / "fxplan_live.md").read_text(encoding="utf-8") or "USD 5,000" in (tmp_path / "fxplan_live.md").read_text(encoding="utf-8")
