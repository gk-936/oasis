"""Agentic planning: validator rules, the tool protocol, the offline planner, Live tool calling (fake client), plan
execution through the normal pipeline, and autonomous-recovery draft validation. No test uses the network."""
import copy
import json
from datetime import date
from types import SimpleNamespace

import pytest

from oasis.agent import plan_exec
from oasis.agent.llm import LiveLLM, OfflineLLM, QuotaExhausted
from oasis.agent.pipeline import OasisAgent, Request
from oasis.agent.planner import AgenticPlanner, DeterministicPlanner, build_record, propose
from oasis.agent.recovery import build_recovery, contact_tokens, validate_draft

from oasis.demo import FORGED, TUITION, new_demo_world
from oasis.planning.scenarios import SCENARIOS, build_scenario_world
from oasis.planning.tools import TOOL_SPECS, PlanningToolbox
from oasis.planning.validator import safe_quota_inr, validate_plan
from oasis.world import Features, World

R2, R3 = "route_inr_cny_2", "route_inr_cny_3"


def conv(day, inr, route=R3, rem="student"):
    return {"action": "convert", "date": day, "send_inr": inr, "route_id": route, "remitter": rem}


def pay(oid, day, payee, amt):
    return {"action": "pay", "date": day, "obligation_id": oid, "payee_id": payee, "amount_cny": amt}


def codes(v):
    return {e["code"] for e in v.errors}


# --------------------------------------------------------------------------------------------- validator rules
@pytest.fixture
def w():
    return build_scenario_world("urgent_deadline")      # INR 600k; deposit 6,000 due 2026-10-14; tuition 30,000 due 2026-11-15


GOOD = lambda: [conv("2026-10-12", 521046, R2), pay("obl_deposit_1", "2026-10-13", "payee_landlord_chen", 6000),
                pay("obl_tuition_1", "2026-11-13", "payee_univ_x", 30000)]


def test_valid_plan_has_metrics_and_no_errors(w):
    v = validate_plan(w, GOOD())
    assert v.ok and v.metrics["deadlines_met"] == 2 and v.metrics["saved_vs_bank_cny"] > 0
    assert any(x["code"] == "approval_expected" for x in v.warnings)       # plans never bypass approval


def test_every_obligation_must_be_funded_and_paid_once(w):
    v = validate_plan(w, GOOD()[:2])
    assert codes(v) == {"obligation_unfunded"}
    assert "duplicate_payment" in codes(validate_plan(w, GOOD() + [pay("obl_tuition_1", "2026-11-14", "payee_univ_x", 30000)]))


def test_unknown_payee_wrong_payee_and_amount_mismatch(w):
    g = GOOD()
    g[1] = pay("obl_deposit_1", "2026-10-13", "payee_attacker", 6000)
    assert "unknown_payee" in codes(validate_plan(w, g))
    g[1] = pay("obl_deposit_1", "2026-10-13", "payee_univ_x", 6000)          # a real payee, but not the one owed
    assert "payee_mismatch" in codes(validate_plan(w, g))
    g[1] = pay("obl_deposit_1", "2026-10-13", "payee_landlord_chen", 5000)
    assert "amount_mismatch" in codes(validate_plan(w, g))
    g[1] = pay("obl_nope", "2026-10-13", "payee_landlord_chen", 6000)
    assert "unknown_obligation" in codes(validate_plan(w, g))


def test_late_and_backdated_payments(w):
    g = GOOD()
    g[1] = pay("obl_deposit_1", "2026-10-20", "payee_landlord_chen", 6000)
    assert "late_payment" in codes(validate_plan(w, g))
    g[1] = pay("obl_deposit_1", "2026-10-01", "payee_landlord_chen", 6000)
    assert "date_in_past" in codes(validate_plan(w, g))


def test_route_must_arrive_before_the_payment(w):
    g = GOOD()
    g[0] = conv("2026-10-12", 521046, R3)            # 3 days: arrives 10-15, the deposit is paid 10-13
    v = validate_plan(w, g)
    assert "route_too_slow" in codes(v)
    assert "unknown_route" in codes(validate_plan(w, [conv("2026-10-12", 1000, "route_nope")] + GOOD()[1:]))


def test_insufficient_inr_and_cny(w):
    g = GOOD()
    g[0] = conv("2026-10-12", 700000, R2)            # student has 600,000
    v = validate_plan(w, g)
    assert "insufficient_inr" in codes(v)
    g[0] = conv("2026-10-12", 100000, R2)
    assert "insufficient_cny" in codes(validate_plan(w, g))


def test_safe_quota_is_per_calendar_year_and_staging_fixes_it():
    w = build_scenario_world("safe_quota_tuition")
    quota = safe_quota_inr()
    one = [conv("2026-10-12", 4_800_000), pay("obl_tuition_1", "2027-01-15", "payee_univ_x", 400000)]
    v = validate_plan(w, one)
    err = next(e for e in v.errors if e["code"] == "safe_quota_exceeded")
    assert err["data"]["max_send_inr"] == pytest.approx(quota) and "2027-01-01" in err["hint"]
    staged = [conv("2026-10-12", quota), conv("2027-01-01", 1450000), pay("obl_tuition_1", "2027-01-15", "payee_univ_x", 400000)]
    assert validate_plan(w, staged).ok
    # SAFE use already booked this year shrinks the room
    w.passport.safe_used_inr["2026"] = quota - 1000
    assert "safe_quota_exceeded" in codes(validate_plan(w, staged))


def test_lrs_tcs_warnings_and_rate_target_reserve():
    w = build_scenario_world("parent_tcs")
    v = validate_plan(w, [conv("2026-10-12", 50000, R2), conv("2026-10-12", 384000, R3, "parent"),
                          pay("obl_tuition_1", "2026-11-13", "payee_univ_x", 30000)])
    assert v.ok
    tcs = [x for x in v.warnings if x["code"] == "tcs"]
    assert tcs and v.metrics["tcs_inr"] == pytest.approx(0.02 * (950000 + 384000 - 1_000_000), abs=1)
    assert any(x["code"] == "parent_remitter" for x in v.warnings)
    w.passport.remitted_inr_fy["parent"] = 21_900_000                          # beyond LRS (USD 250k at 88)
    assert "lrs_exceeded" in codes(validate_plan(w, [conv("2026-10-12", 50000, R2), conv("2026-10-12", 384000, R3, "parent"),
                                                     pay("obl_tuition_1", "2026-11-13", "payee_univ_x", 30000)]))
    r = build_scenario_world("rate_target")
    v = validate_plan(r, [conv("2026-10-12", 615000), pay("obl_deposit_1", "2026-10-23", "payee_landlord_chen", 6000),
                          pay("obl_rent_1", "2026-10-30", "payee_landlord_chen", 6000),
                          pay("obl_tuition_1", "2026-11-13", "payee_univ_x", 30000)])
    assert codes(v) == {"rate_target_reserve"}


def test_frozen_obligation_cannot_be_planned(w):
    w.passport.obligation("obl_deposit_1").status = "frozen"
    assert "obligation_frozen" in codes(validate_plan(w, GOOD()))


def test_late_income_is_not_counted():
    w = build_scenario_world("late_scholarship")
    v = validate_plan(w, DeterministicPlanner().plan(w).steps)
    assert v.ok and any(x["code"] == "late_income_ignored" for x in v.warnings)


# ------------------------------------------------------------------------------------------------------ tools
def test_tools_are_read_only_or_proposal_only(w):
    before = (w.passport.model_dump(), len(w.audit.entries), w.ledger.money_lost())
    tb = PlanningToolbox(w)
    names = [t["function"]["name"] for t in TOOL_SPECS]
    assert names == ["read_passport", "list_obligations", "get_rates", "get_routes", "check_corridor", "forecast_runway", "propose_plan"]
    for n, a in (("read_passport", {}), ("list_obligations", {}), ("get_rates", {}), ("get_routes", {"send_inr": 100000, "due": "2026-10-20"}),
                 ("check_corridor", {"amount_inr": 5_000_000, "purpose": "tuition", "remitter": "student"}), ("forecast_runway", {})):
        assert "error" not in tb.call(n, a)
    assert tb.call("propose_plan", {"steps": GOOD(), "rationale": "x"})["valid"]
    assert tb.call("pay_everything", {})["error"].startswith("unknown tool")      # there is no money-moving tool
    assert (w.passport.model_dump(), len(w.audit.entries), w.ledger.money_lost()) == before
    cc = tb.call("check_corridor", {"amount_inr": 5_000_000, "purpose": "tuition"})
    assert any(f["rule"] == "safe_quota" for f in cc["findings"])
    assert "on_time" in tb.call("get_routes", {"send_inr": 100000, "due": "2026-10-13"})["routes"][0]


def test_proposal_iteration_limit(w):
    tb = PlanningToolbox(w, max_iterations=2)
    for _ in range(3):
        res = tb.call("propose_plan", {"steps": [], "rationale": ""})
    assert res["errors"][0]["code"] == "iteration_limit"


# ---------------------------------------------------------------------------------------- offline planner
@pytest.mark.parametrize("sid", list(SCENARIOS))
def test_deterministic_planner_solves_every_scenario(sid):
    w = build_scenario_world(sid)
    rec = propose(w, DeterministicPlanner(), SCENARIOS[sid].goal)
    assert rec["valid"] and rec["status"] == "proposed" and rec["iterations"] <= 4 and not rec["fell_back"]
    m = rec["validation"]["metrics"]
    assert m["deadlines_met"] == m["obligations"] and m["saved_vs_bank_cny"] > 0 and rec["why"]
    assert {t["tool"] for t in rec["trace"] if t["type"] == "tool_call"} >= {"read_passport", "list_obligations", "get_routes"}


def test_shortfall_plan_shows_a_revision_from_validator_feedback():
    rec = propose(build_scenario_world("shortfall"), DeterministicPlanner())
    props = [t for t in rec["trace"] if t["type"] == "proposal"]
    assert len(props) == 2 and not props[0]["validation"]["valid"] and props[1]["validation"]["valid"]
    assert props[0]["validation"]["errors"][0]["code"] == "insufficient_inr"
    assert any(s.get("remitter") == "parent" for s in rec["steps"])


def test_safe_scenario_splits_tuition_across_two_years():
    rec = propose(build_scenario_world("safe_quota_tuition"), DeterministicPlanner())
    convs = [s for s in rec["steps"] if s["action"] == "convert"]
    assert [c["date"][:4] for c in convs] == ["2026", "2027"] and rec["valid"]
    assert any("SAFE" in x for x in rec["why"])


def test_parent_tcs_warning_is_surfaced():
    rec = propose(build_scenario_world("parent_tcs"), DeterministicPlanner())
    assert rec["validation"]["metrics"]["tcs_inr"] > 0 and any("TCS" in x for x in rec["why"])


# ------------------------------------------------------------------------------- Live tool calling (fake client)
class FakeToolClient:
    """script items: ("tools", [(name, args)...]) | ("text", str) | Exception."""

    def __init__(self, script):
        self.script, self.calls, self.n = list(script), [], 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        kind, payload = item
        if kind == "text":
            msg = SimpleNamespace(content=payload, tool_calls=None)
        else:
            tcs = []
            for name, args in payload:
                self.n += 1
                tcs.append(SimpleNamespace(id=f"call_{self.n}", function=SimpleNamespace(name=name, arguments=json.dumps(args))))
            msg = SimpleNamespace(content="", tool_calls=tcs)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=500))


def live_world(tmp_path, script, scenario="urgent_deadline"):
    llm = LiveLLM(client=FakeToolClient(script), cache_dir=tmp_path, sleep=lambda s: None, rpm=0)
    return build_scenario_world(scenario, llm), llm


def test_live_tool_calling_with_revision_after_validator_feedback(tmp_path):
    bad = GOOD()
    bad[1] = pay("obl_deposit_1", "2026-10-13", "payee_landlord_chen", 5000)       # wrong amount -> validator error
    w, llm = live_world(tmp_path, [("tools", [("read_passport", {}), ("list_obligations", {})]),
                                   ("tools", [("propose_plan", {"steps": bad, "rationale": "first try"})]),
                                   ("tools", [("propose_plan", {"steps": GOOD(), "rationale": "fixed the deposit amount"})])])
    res = AgenticPlanner(llm).plan(w, "pay everything")
    assert res.valid and not res.fell_back and res.iterations == 2 and res.planner == "bedrock-tools" and res.tokens == 1500
    props = [t for t in res.trace if t["type"] == "proposal"]
    assert [p["validation"]["valid"] for p in props] == [False, True] and props[0]["validation"]["errors"][0]["code"] == "amount_mismatch"
    # the second request carried the tool results back to the model (native tool calling protocol)
    second = llm.client.calls[1]["messages"]
    assert any(m["role"] == "tool" for m in second) and llm.client.calls[0]["tool_choice"] == "auto"
    assert all(t["function"]["name"] for t in llm.client.calls[0]["tools"])
    assert w.passport.balance("INR") == 600000                                      # a proposal moves nothing


def test_live_falls_back_to_deterministic_plan_and_records_it(tmp_path):
    bad = [{"action": "pay", "date": "2026-10-13", "obligation_id": "obl_deposit_1", "payee_id": "payee_attacker", "amount_cny": 6000}]
    script = [("tools", [("propose_plan", {"steps": bad, "rationale": "x"})]) for _ in range(4)]
    w, llm = live_world(tmp_path, script)
    res = AgenticPlanner(llm).plan(w)
    assert res.fell_back and res.valid and res.planner.startswith("deterministic") and "no valid plan after 4" in res.fallback_reason
    assert any(t["type"] == "fallback" for t in res.trace)
    rec = build_record(w, res)
    assert rec["fell_back"] and rec["status"] == "proposed" and rec["fallback_reason"]


def test_live_text_only_reply_and_quota_errors_fall_back(tmp_path):
    w, llm = live_world(tmp_path, [("text", "I cannot."), ("text", "Still no.")])
    res = AgenticPlanner(llm).plan(w)
    assert res.fell_back and res.valid
    e = Exception("Rate limit reached for model: tokens per day (TPD)")
    e.status_code = 429
    w2, llm2 = live_world(tmp_path / "b", [e, e])
    res2 = AgenticPlanner(llm2).plan(w2)
    assert res2.fell_back and "QuotaExhausted" in res2.fallback_reason and res2.valid


def test_live_tool_responses_are_cached_and_budget_capped(tmp_path):
    steps = {"steps": GOOD(), "rationale": "ok"}
    w, llm = live_world(tmp_path, [("tools", [("propose_plan", steps)])])
    AgenticPlanner(llm).plan(w)
    assert llm.calls == 1
    w2, llm2 = live_world(tmp_path, [])         # same cache dir, empty script: must be served from the cache
    res = AgenticPlanner(llm2).plan(w2)
    assert res.valid and llm2.cache_hits == 1 and res.tokens == 0
    w3, llm3 = live_world(tmp_path / "c", [("tools", [("read_passport", {})])])
    res3 = AgenticPlanner(llm3, token_cap=400).plan(w3)         # one 500-token round exceeds the cap -> stop, fall back
    assert res3.fell_back and "token cap" in res3.fallback_reason


# ----------------------------------------------------------------------------- execution through the pipeline
def test_plan_needs_acceptance_and_payments_still_need_approval():
    w = new_demo_world()
    a = OasisAgent(w)
    rec = propose(w, DeterministicPlanner())
    assert "error" in plan_exec.execute_due(a, rec["id"])                          # a proposal executes nothing
    assert plan_exec.accept_plan(a, rec["id"])["status"] == "accepted"
    res = plan_exec.execute_due(a, rec["id"])                                      # parent conversion lacks consent
    st = {r["step"]: r["status"] for r in res["ran"]}
    assert "awaiting_parent_consent" in st.values() and w.ledger.money_lost() == 0
    assert plan_exec.sim_parent_consent(a, rec["id"]) >= 1                         # the (simulated) parent signs their consent
    res = plan_exec.execute_due(a, rec["id"])
    assert all(r["status"] != "blocked" for r in res["ran"])
    assert any(r["status"] == "done" and "->" in r["note"] for r in res["ran"])         # conversions ran
    assert w.passport.obligation("obl_deposit_1").status != "paid"                       # payments are not due yet


def test_executed_plan_payments_go_through_signed_intents_and_wait_for_approval():
    w = new_demo_world()
    a = OasisAgent(w)
    rec = propose(w, DeterministicPlanner())
    plan_exec.accept_plan(a, rec["id"])
    plan_exec.sim_parent_consent(a, rec["id"])
    plan_exec.execute_due(a, rec["id"])                                              # conversions due today
    w.advance(days=11)                                                                # 2026-10-23: the deposit step is due
    res = plan_exec.execute_due(a, rec["id"])
    held = res["held"]
    assert held and held[0][1].status == "held" and w.passport.obligation("obl_deposit_1").status != "paid"
    req = held[0][0]
    a.sim_approve(req, held[0][1], ["student"])                                      # the simulated student's device signs the draft
    out = a.handle(req)                                                              # the student approves; full pipeline
    assert out.status == "paid" and out.intent and out.proof_id and out.verification
    assert plan_exec.step_statuses(w, rec)[2]["status"] == "done"


def test_api_plan_flow(api_client):
    c = api_client
    sc = c.get("/api/plan/scenarios").json()
    assert len(sc) == 8
    r = c.post("/api/plan", json={"scenario": "safe_quota_tuition"}).json()
    assert r["valid"] and r["scenario"] and c.get("/api/plans").json() == []         # scenario worlds are not stored
    p = c.post("/api/plan", json={"goal": "pay everything"}).json()
    assert p["valid"] and p["status"] == "proposed" and p["trace"] and p["why"] and p["step_status"]
    assert c.post("/api/plan/plan_001/execute", json={}).status_code == 409             # not accepted yet
    assert c.post(f"/api/plan/{p['id']}/accept").json()["status"] == "accepted"
    ex = c.post(f"/api/plan/{p['id']}/execute").json()
    assert ex["ran"] and ex["plan_status"] == "executing"
    assert any(r["status"] == "awaiting_parent_consent" for r in ex["ran"])           # a "parent" string cannot stand in for the parent
    assert c.get("/api/audit/verify").json()["ok"]
    assert c.post("/api/plan", json={"scenario": "nope"}).status_code == 400


def test_demo_run_one_includes_a_deterministic_agentic_plan():
    from oasis.demo import play
    a, b = play("legit"), play("legit")
    ap = a["steps"][0]["agentic_plan"]
    assert ap["valid"] and ap["planner"] == "deterministic" and ap["iterations"] == 2 and a["network_used"] is False
    assert a["audit_head"] == b["audit_head"]


# ------------------------------------------------------------------------------------------ recovery drafts
def test_contact_tokens_and_draft_validation():
    sus = "Pay to account 6228 4800 0000 9999 now. Contact pay@evil.example or +86 138 0000 1111. https://evil.example/x"
    toks = contact_tokens(sus)
    assert "6228480000009999" in toks and "pay@evil.example" in toks and "8613800001111" in toks
    assert validate_draft("Please confirm via the portal.", sus) == []
    assert validate_draft("Send it to 6228480000009999 please", sus)
    assert validate_draft("Send it to 6228 4800 0000 9999 please", sus)
    assert validate_draft("Email pay@evil.example", sus)
    assert validate_draft("Call +86 138 0000 1111", sus)
    assert validate_draft("Details at https://evil.example/x", sus)
    assert validate_draft("Use account 1234567890123456", "nothing here")                 # any account-like number is refused
    assert validate_draft("Write to finance@univ-x.example.edu", sus, ["finance@univ-x.example.edu"]) == []   # the registry's own contact is fine
    assert validate_draft("Due 2026-11-15, CNY 30,000", sus) == []


class DraftLLM(OfflineLLM):
    def __init__(self, draft):
        super().__init__()
        self.draft, self.ctxs = draft, []

    def draft_recovery(self, ctx):
        self.ctxs.append(ctx)
        return self.draft


def freeze_with(llm):
    w = World(Features.full(), llm, seed=7, deterministic=True)
    a = OasisAgent(w)
    out = a.handle(Request(FORGED + "\nContact our new desk: pay@evil.example"))
    return w, out


def test_recovery_uses_registry_channel_and_never_shows_the_model_the_request():
    llm = DraftLLM("Hello University X Finance Office, please confirm your current account via your official portal inbox. Nothing was paid.")
    w, out = freeze_with(llm)
    rec = out.recovery
    assert out.status == "rejected" and rec["draft_source"].startswith("llm") and rec["draft_checks"]["ok"]
    assert rec["channel"]["address"] == "finance@univ-x.example.edu" and rec["channel"]["source"] == "verified-payee registry"
    blob = json.dumps(llm.ctxs)
    assert "6228480000009999" not in blob and "evil" not in blob and "URGENT" not in blob


@pytest.mark.parametrize("bad", ["Please send the funds to 6228480000009999 and confirm.", "Reply to pay@evil.example to confirm.",
                                 "Please wire to account 1111222233334444."])
def test_recovery_rejects_drafts_with_details_from_the_suspicious_request(bad):
    w, out = freeze_with(DraftLLM(bad))
    rec = out.recovery
    assert rec["draft_source"] == "template" and rec["llm_draft_rejected"] and rec["draft_checks"]["ok"]
    assert "6228480000009999" not in rec["draft_message"] and "evil" not in rec["draft_message"]


def test_offline_recovery_uses_the_template():
    w = new_demo_world()
    ob = w.passport.obligation("obl_tuition_1")
    rec = build_recovery(w, ob, FORGED)
    assert rec["draft_source"] == "template" and "official portal inbox" in rec["draft_message"] and rec["draft_checks"]["ok"]
    assert rec["draft_checks"]["ok"] and "6228480000009999" not in rec["draft_message"]


def test_plan_written_as_text_is_still_only_a_validated_proposal(tmp_path):
    text = "Here is the plan: " + json.dumps({"steps": GOOD(), "rationale": "text reply"})
    w, llm = live_world(tmp_path, [("text", text)])
    res = AgenticPlanner(llm).plan(w)
    assert res.valid and not res.fell_back
    assert any(t["type"] == "model_note" and "parsed as a propose_plan" in t["text"] for t in res.trace)
    w2, llm2 = live_world(tmp_path / "b", [("text", '{"steps": [{"action": "pay", "date": "2026-10-13"}]}'), ("text", "no")])
    assert AgenticPlanner(llm2).plan(w2).fell_back          # a malformed text plan fails validation like any other


def test_model_errors_are_traced_without_keys_or_org_ids(tmp_path):
    fake_key = "AKIA" + "FAKETESTKEY00001"          # made up, assembled at run time so a secret scanner has nothing to flag
    e = Exception(f"Error 400 for {fake_key} Bearer abc.def")
    e.status_code = 400
    w, llm = live_world(tmp_path, [e, e])
    res = AgenticPlanner(llm).plan(w)
    errs = [t for t in res.trace if t["type"] == "model_error"]
    assert errs and all(fake_key not in json.dumps(t) and "abc.def" not in json.dumps(t) for t in errs)
    assert res.fell_back


def test_planner_prompt_carries_validator_guidance_and_cap_is_raised():
    from oasis.agent.planner import SYSTEM
    from eval.planning import PER_PLAN_CAP
    for needle in ("get_routes", "headroom", "rounding", "calendar year", "January", "rate_target_reserve", "exactly ONCE",
                   "insufficient_cny", "insufficient_inr", "safe_quota_exceeded", "parent"):
        assert needle in SYSTEM, needle
    assert PER_PLAN_CAP >= 22_000


def test_only_repeat_runs_one_repeat_and_replaces_its_row(tmp_path, monkeypatch):
    import eval.planning as ep
    import oasis.agent.llm as llm_mod

    class FakeUsage:
        path = tmp_path / "usage.json"
        def day(self): return {"tokens": 0, "keys": {}}

    class FakeLLM:
        model = "fake"
        fingerprints = ["aaaa"]
        calls = cache_hits = fallbacks = key_rotations = 0
        def __init__(self, salt="", temperature=0): self.salt, self.usage = salt, FakeUsage()

    class FakeLedger:
        def __init__(self, path): pass
        def day(self): return {"tokens": 0, "keys": {}}

    seen = []
    def fake_run(sid, planner):
        seen.append(sid)
        return {"scenario": sid, "title": sid, "valid": True, "fell_back": False, "model_valid_without_fallback": True, "iterations_to_valid": 1,
                "deadlines_met": 1, "obligations": 1, "fees_cny": 1, "bank_fees_cny": 2, "tokens": 10, "model_calls": 1, "first_errors": [], "proposals": 1}

    old = {"scenario": "tight_runway", "rep": 2, "title": "Tight runway", "valid": True, "fell_back": True, "model_valid_without_fallback": False,
           "iterations_to_valid": None, "deadlines_met": 1, "obligations": 1, "fees_cny": 1, "bank_fees_cny": 2, "tokens": 5, "model_calls": 1,
           "first_errors": [], "run_date": "2026-10-10"}
    keep = dict(old, scenario="urgent_deadline", rep=0, tokens=7)
    (tmp_path / "planning.json").write_text(json.dumps({"live": {"repeats": 3, "results": [keep, old], "notes": []}}), encoding="utf-8")
    monkeypatch.setattr(ep, "REPORTS", tmp_path)
    monkeypatch.setattr(ep, "run_scenario", fake_run)
    monkeypatch.setattr(llm_mod, "LiveLLM", FakeLLM)
    monkeypatch.setattr(llm_mod, "UsageLedger", FakeLedger)
    data = ep.main(["--llm", "bedrock", "--repeats", "3", "--repeat-index", "3", "--token-cap", "1000"])
    rows = data["live"]["results"]
    assert len(seen) == len(SCENARIOS)
    r3 = [r for r in rows if r["rep"] == 2]
    assert len(r3) == len(SCENARIOS) and all(r["tokens"] == 10 for r in r3)       # old repeat-3 row replaced
    assert any(r["rep"] == 0 and r["tokens"] == 7 for r in rows)                   # other repeats untouched
    assert not any(r["rep"] == 1 for r in rows)


# ------------------------------------------------------------------ compact tool results for the live model (format v2)
def _valid_steps(sid):
    from oasis.planning.scenarios import build_scenario_world
    w = build_scenario_world(sid)
    return w, [dict(s) for s in DeterministicPlanner().plan(w).steps]


def test_compact_results_are_smaller_but_keep_every_fact_the_model_acts_on():
    import json as _json
    from oasis.planning.scenarios import build_scenario_world
    from oasis.planning.tools import PlanningToolbox, present
    for sid in ("rate_target", "late_scholarship", "shortfall"):
        w = build_scenario_world(sid)
        tb = PlanningToolbox(w)
        full = {n: tb.call(n, a) for n, a in [("read_passport", {}), ("list_obligations", {}), ("get_rates", {}), ("forecast_runway", {}),
                                               ("get_routes", {"send_inr": 200000, "due": "2026-11-15"}),
                                               ("check_corridor", {"amount_inr": 200000, "purpose": "tuition"})]}
        size = lambda x: len(_json.dumps(x, separators=(",", ":")))
        small = {n: present(n, r, "v2") for n, r in full.items()}
        assert sum(map(size, small.values())) < 0.7 * sum(map(size, full.values()))
        assert all(present(n, r, "v1") is r for n, r in full.items())               # v1 is the untouched full result
        p, o, rt, rn = small["read_passport"], small["list_obligations"], small["get_rates"], small["get_routes"]
        fp = full["read_passport"]
        for k in ("today", "balances", "safe_used_inr_by_year", "safe_quota_inr_per_year", "lrs_limit_inr_per_remitter", "remitted_inr_fy"):
            assert p[k] == fp[k]
        assert [(t["rate"], t["convert_cny"]) for t in p["rate_targets"]] == [(t["rate"], t["convert_cny"]) for t in fp["rate_targets"]]
        assert [(i["amount_cny"], i["expected"]) for i in p["income_not_arrived"]] == [(i["amount_cny"], i["expected"]) for i in fp["income_not_arrived"]]
        need = [x for x in full["list_obligations"]["obligations"] if x["plan_must_fund"]]
        assert [(x["id"], x["payee_id"], x["amount_cny"], x["due"]) for x in o["must_fund"]] == [(x["id"], x["payee_id"], x["amount_cny"], x["due"]) for x in need]
        assert set(o["not_in_plan"]) == {x["id"] for x in full["list_obligations"]["obligations"]} - {x["id"] for x in need}
        assert {(r["id"], r["days"], r["fixed_fee_inr"], r["pct_fee"], r["spread"]) for r in rt["routes"]} == \
               {(r["id"], r["days"], r["fixed_fee_inr"], r["pct_fee"], r["spread"]) for r in full["get_rates"]["routes"]}
        assert rt["mid_cny_per_inr"] == full["get_rates"]["mid_cny_per_inr"]
        assert {(r["route_id"], r["delivered_cny"], r["days"], r["on_time"]) for r in rn["routes"]} == \
               {(r["route_id"], r["delivered_cny"], r["days"], r["on_time"]) for r in full["get_routes"]["routes"]}
        assert sum(1 for r in rt["routes"] if r.get("bank")) == 1
        assert small["check_corridor"]["safe_remaining_inr_this_calendar_year"] == full["check_corridor"]["safe_remaining_inr_this_calendar_year"]


def test_compact_validator_errors_keep_code_message_hint_and_step_for_every_error_code():
    from oasis.planning.tools import PlanningToolbox, present
    seen = set()

    def check(w, steps):
        tb = PlanningToolbox(w)
        res = tb.call("propose_plan", {"steps": steps, "rationale": "x"})
        out = present("propose_plan", res, "v2")
        assert out["valid"] == res["valid"]
        assert out["errors"] == [{k: e[k] for k in ("code", "message", "hint", "step") if k in e} for e in res["errors"]]
        for e, c in zip(out["errors"], res["errors"]):
            assert e["code"] == c["code"] and e["message"] == c["message"] and e.get("hint") == c.get("hint") and e.get("step") == c.get("step")
            seen.add(e["code"])

    w, st = _valid_steps("shortfall")
    pay = next(i for i, s in enumerate(st) if s["action"] == "pay")
    conv = next(i for i, s in enumerate(st) if s["action"] == "convert")
    mut = lambda f: (lambda c: (f(c), c)[1])(copy.deepcopy(st))
    check(w, mut(lambda c: c[pay].update(amount_cny=c[pay]["amount_cny"] - 1)))                    # amount_mismatch
    check(w, mut(lambda c: c[conv].update(route_id="nope")))                                       # unknown_route
    check(w, mut(lambda c: c[pay].update(payee_id="payee_landlord_chen" if c[pay]["payee_id"] != "payee_landlord_chen" else "payee_univ_x")))   # payee_mismatch
    check(w, mut(lambda c: c.pop(pay)))                                                            # obligation_unfunded
    check(w, mut(lambda c: c.append(dict(c[pay]))))                                                # duplicate_payment
    check(w, mut(lambda c: c[pay].update(date="2030-01-01")))                                      # late_payment
    check(w, mut(lambda c: c[pay].update(date="2020-01-01")))                                      # date_in_past
    check(w, mut(lambda c: c[conv].update(send_inr=c[conv]["send_inr"] * 20)))                     # insufficient_inr
    check(w, [s for s in st if s["action"] == "pay"])                                              # insufficient_cny
    check(w, [])                                                                                   # bad_step
    w2, st2 = _valid_steps("safe_quota_tuition")
    check(w2, [{**s, "date": "2026-10-13"} if s["action"] == "convert" else s for s in st2] +
          [{"action": "convert", "date": "2026-10-13", "send_inr": 3_000_000, "route_id": next(s for s in st2 if s["action"] == "convert")["route_id"],
            "remitter": "student"}])                                                                # safe_quota_exceeded
    w3, st3 = _valid_steps("rate_target")
    check(w3, [{**s, "send_inr": s["send_inr"] * 1.12} if s["action"] == "convert" else s for s in st3])      # rate_target_reserve or insufficient_inr
    assert {"amount_mismatch", "unknown_route", "payee_mismatch", "obligation_unfunded", "duplicate_payment", "late_payment", "date_in_past",
            "insufficient_inr", "insufficient_cny", "bad_step", "safe_quota_exceeded"} <= seen, seen


def test_agentic_planner_sends_the_compact_results_by_default_and_the_full_ones_for_v1():
    from oasis.planning.scenarios import build_scenario_world
    import json as _json

    class Spy:
        name = "bedrock"
        errors: list = []

        def __init__(self):
            self.seen = []

        def chat_tools(self, msgs, tools):
            self.seen.append([m for m in msgs if m["role"] == "tool"])
            if len(self.seen) == 1:
                return {"tool_calls": [{"id": "a", "name": "list_obligations", "arguments": {}}], "tokens": 10, "model": "m"}
            return {"content": "", "tool_calls": [], "tokens": 10, "model": "m"}

    for fmt, key in (("v2", "must_fund"), ("v1", "obligations")):
        spy = Spy()
        AgenticPlanner(spy, fmt=fmt).plan(build_scenario_world("shortfall"))
        assert key in _json.loads(spy.seen[1][0]["content"])


def test_heldout_scenarios_are_separate_from_the_original_eight_and_feasible():
    from oasis.planning.scenarios import ALL_SCENARIOS, HELDOUT, SCENARIOS, build_scenario_world
    assert len(SCENARIOS) == 8 and len(HELDOUT) == 4 and all(k.startswith("heldout_") for k in HELDOUT)
    assert set(ALL_SCENARIOS) == set(SCENARIOS) | set(HELDOUT)
    for sid in HELDOUT:
        r = DeterministicPlanner().plan(build_scenario_world(sid))
        assert r.valid, sid
