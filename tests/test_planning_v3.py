"""Planner format v3 (calculator tools + `fix` hints + shorter prompt). Hermetic: fake clients only, no network.

Covers: tool schemas, size_conversion arithmetic, facts_sheet totals for all 12 scenarios, every `fix` removing its own
validator error, v1/v2 byte-for-byte snapshots, prompt length, the tool-call round trip through GroqLLM.chat_tools with a
scripted "model" that uses the calculators, purity of the new tools, and the offline planner under every format."""
import copy
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from oasis.agent.llm import GroqLLM
from oasis.agent.planner import SYSTEM, SYSTEM_V3, AgenticPlanner, DeterministicPlanner, _tool_message, planner_format
from oasis.mock.rates import ROUTES, delivered_amount
from oasis.planning import calc
from oasis.planning.fixes import derive_fixes
from oasis.planning.scenarios import ALL_SCENARIOS, HELDOUT, SCENARIOS, build_scenario_world
from oasis.planning.tools import TOOL_SPECS, TOOL_SPECS_V3, PlanningToolbox
from oasis.planning.validator import required_obligations, safe_quota_inr, validate_plan

ALL = list(ALL_SCENARIOS)
SNAP = Path(__file__).parent / "snapshots" / "planner_v1_v2.json"


def codes(v):
    return [e["code"] for e in v.errors]


# ------------------------------------------------------------------------------------------------------ schemas
def test_v3_tool_schemas_are_valid_and_small():
    names = [t["function"]["name"] for t in TOOL_SPECS_V3]
    assert names == ["facts_sheet", "size_conversion", "propose_plan"]
    for t in TOOL_SPECS_V3:
        f = t["function"]
        assert t["type"] == "function" and f["description"] and f["parameters"]["type"] == "object"
        props, req = f["parameters"]["properties"], f["parameters"].get("required", [])
        assert set(req) <= set(props)
        for p in props.values():
            assert p["type"] in ("string", "number", "array", "object")
    sc = next(t for t in TOOL_SPECS_V3 if t["function"]["name"] == "size_conversion")["function"]["parameters"]
    assert set(sc["properties"]) == {"target_cny", "route_id", "convert_date", "remitter", "due"} and sc["required"] == ["target_cny", "route_id", "convert_date"]
    assert not next(t for t in TOOL_SPECS_V3 if t["function"]["name"] == "facts_sheet")["function"]["parameters"]["properties"]
    assert len(json.dumps(TOOL_SPECS_V3)) < 0.8 * len(json.dumps(TOOL_SPECS))
    assert [t["function"]["name"] for t in TOOL_SPECS][0] == "read_passport" and len(TOOL_SPECS) == 7       # v1/v2 tool list untouched


def test_v3_tools_exist_only_in_the_v3_toolbox():
    w = build_scenario_world("shortfall")
    assert "error" not in PlanningToolbox(w, fmt="v3").call("facts_sheet")
    assert PlanningToolbox(w).call("facts_sheet")["error"].startswith("unknown tool")
    assert PlanningToolbox(w, fmt="v1").call("size_conversion", {"target_cny": 1, "route_id": ROUTES[1].id, "convert_date": "2026-10-12"})["error"].startswith("unknown tool")


# ------------------------------------------------------------------------------------------------- size_conversion
@pytest.mark.parametrize("sid", ["shortfall", "safe_quota_tuition", "parent_tcs", "heldout_year_boundary"])
def test_size_conversion_matches_delivered_amount_and_never_falls_short(sid):
    w = build_scenario_world(sid)
    mid = w.rates.mid(w.day_index)
    for r in ROUTES:
        for rem in ("student", "parent"):
            for target in (1.0, 99.5, 6000.0, 30000.0, 123456.78, 350000.0):
                out = calc.size_conversion(w, target, r.id, w.today.isoformat(), rem)
                send = out["send_inr"]
                assert isinstance(send, int) and out["route_id"] == r.id and out["remitter"] == rem
                assert out["delivered_cny"] == round(delivered_amount(send, r, mid), 2)         # same formula as the validator
                assert out["delivered_cny"] >= target + calc.HEADROOM_CNY - 1e-9                # headroom is documented and real
                assert round(delivered_amount(send - 1, r, mid), 2) < target + calc.HEADROOM_CNY   # the smallest whole rupee that does
                assert out["arrives_on"] == (w.today + timedelta(days=r.days)).isoformat()
                assert out["effective_rate"] == pytest.approx(out["delivered_cny"] / send, abs=1e-6)


def test_size_conversion_on_time_safe_and_corridor_notes():
    w = build_scenario_world("safe_quota_tuition")
    r3 = "route_inr_cny_3"
    ok = calc.size_conversion(w, 1000, r3, "2026-10-12", due="2026-10-15")
    late = calc.size_conversion(w, 1000, r3, "2026-10-13", due="2026-10-15")
    assert ok["on_time"] and not late["on_time"] and ok["latest_convert_date"] == "2026-10-12"
    assert "on_time" not in calc.size_conversion(w, 1000, r3, "2026-10-12")
    big = calc.size_conversion(w, 400000, r3, "2026-10-12")                  # ~INR 5.7M against a 4.4M quota
    assert big["safe"]["fits"] is False and big["safe"]["stage_rest_on"] == "2027-01-01" and big["safe"]["room_inr"] == round(safe_quota_inr())
    assert calc.size_conversion(w, 1000, r3, "2027-01-02")["safe"]["year"] == "2027"
    p = build_scenario_world("parent_tcs")
    par = calc.size_conversion(p, 30000, "route_inr_cny_2", "2026-10-12", "parent")      # parent already at INR 9.5 lakh
    assert par["tcs_inr"] > 0 and par["lrs_ok"]
    assert calc.size_conversion(p, 30000, "route_inr_cny_2", "2026-10-12", "student")["tcs_inr"] == 0
    ok_args = dict(target_cny=100, route_id=r3, convert_date="2026-10-12")
    for bad in (dict(route_id="nope"), dict(target_cny=0), dict(remitter="uncle"), dict(convert_date="2020-01-01")):
        assert "error" in calc.size_conversion(p, **{**ok_args, **bad})
    tb = PlanningToolbox(p, fmt="v3")
    assert "error" in tb.call("size_conversion", {"target_cny": "abc", "route_id": r3, "convert_date": "2026-10-12"})
    assert "error" in tb.call("size_conversion", {"target_cny": 5})


# ---------------------------------------------------------------------------------------------------- facts_sheet
@pytest.mark.parametrize("sid", ALL)
def test_facts_sheet_totals_match_the_passport(sid):
    w = build_scenario_world(sid)
    p, f = w.passport, calc.facts_sheet(w)
    need = required_obligations(p)
    assert [(o["id"], o["payee_id"], o["amount_cny"], o["due"]) for o in f["obligations"]] == [(o.id, o.payee_id, o.remaining, o.due) for o in need]
    total = sum(o.remaining for o in need)
    assert f["cny_needed"]["total"] == pytest.approx(total)
    assert sum(f["cny_needed"]["by_month"].values()) == pytest.approx(total) and sum(f["cny_needed"]["by_year"].values()) == pytest.approx(total)
    for o in need:
        assert f["cny_needed"]["by_month"][o.due[:7]] == pytest.approx(sum(x.remaining for x in need if x.due[:7] == o.due[:7]))
        assert f["cny_needed"]["by_year"][o.due[:4]] == pytest.approx(sum(x.remaining for x in need if x.due[:4] == o.due[:4]))
    assert f["balances"] == {"INR": p.balance("INR"), "CNY": p.balance("CNY")}
    reserve = sum(t["convert_cny"] / t["rate"] for t in p.rules.rate_targets if t.get("status") in ("watching", "awaiting_approval"))
    assert f["rate_target_reserve_inr"] == pytest.approx(reserve, abs=0.01) and f["student_spendable_inr"] == pytest.approx(max(0, p.balance("INR") - reserve), abs=0.01)
    assert f["cny_shortfall"] == pytest.approx(max(0.0, total - p.balance("CNY")), abs=0.01)
    q = round(safe_quota_inr())
    assert f["safe"]["quota_inr"] == q and f["safe"]["left_by_year"][str(w.today.year)] == round(q - p.safe_used_inr.get(str(w.today.year), 0.0))
    assert max(int(o.due[:4]) for o in need) <= max(int(y) for y in f["safe"]["left_by_year"]) and f["safe"]["new_year_starts"] == f"{w.today.year + 1}-01-01"
    assert f["parent"]["remitted_inr_fy"] == round(p.remitted_inr_fy.get("parent", 0.0)) and f["parent"]["consent_needed"] is True
    assert {r["id"] for r in f["routes"]} == {r.id for r in ROUTES}
    if f["cny_shortfall"] > 0:                  # the INR estimate is the cheapest non-bank route, shortfall minus what the student can spend
        assert f["inr_needed_est"] > 0 and f["inr_short_est"] == max(0, f["inr_needed_est"] - f["student_spendable_inr"]) or abs(f["inr_short_est"] - max(0, f["inr_needed_est"] - f["student_spendable_inr"])) <= 1
    else:
        assert f["inr_needed_est"] is None and f["inr_short_est"] is None
    assert len(json.dumps(f, separators=(",", ":"))) < 4000          # about 1k tokens at 4 chars/token; the 12 scenarios measure 1.1k to 1.5k chars


# ------------------------------------------------------------------------------------------------------- the fixes
def apply_fixes(steps, errors):
    """Apply the `fix` of every error (what a careful model does). Sets first, then removals (descending), then additions."""
    steps = copy.deepcopy(steps)
    used = set()
    adds, removes = [], []
    for e in errors:
        fx = e.get("fix")
        if not fx:
            continue
        if "step" in fx and "set" in fx and fx["step"] not in used:
            steps[fx["step"]].update(fx["set"])
            used.add(fx["step"])
        elif "step" in fx and "set" in fx:
            continue
        if "remove_step" in fx:
            removes.append(fx["remove_step"])
        for k in ("add_convert", "add_pay"):
            if k in fx:
                adds.append({"action": "convert" if k == "add_convert" else "pay", **fx[k]})
    for i in sorted(set(removes), reverse=True):
        steps.pop(i)
    return steps + adds


def propose_v3(w, steps):
    res = PlanningToolbox(w, fmt="v3").call("propose_plan", {"steps": steps, "rationale": "x"})
    return res


def base(sid):
    w = build_scenario_world(sid)
    return w, [dict(s) for s in DeterministicPlanner().plan(build_scenario_world(sid)).steps]


def first(steps, action):
    return next(i for i, s in enumerate(steps) if s["action"] == action)


def assert_fix_removes(w, bad, code, expect_other_free=False):
    """The v3 error for `code` carries a fix; applying it makes that error code disappear from a fresh validation."""
    res = propose_v3(w, bad)
    errs = [e for e in res["errors"] if e["code"] == code]
    assert errs and all("fix" in e for e in errs), (code, res["errors"])
    fixed = apply_fixes(bad, errs)
    now = validate_plan(w, fixed)
    assert code not in codes(now), (code, now.errors)
    if expect_other_free:
        assert now.ok, now.errors
    return now


def test_fix_amount_mismatch_and_payee_and_dates_and_duplicates():
    w, st = base("urgent_deadline")
    p = first(st, "pay")
    m = copy.deepcopy(st); m[p]["amount_cny"] -= 1
    assert_fix_removes(w, m, "amount_mismatch", True)
    m = copy.deepcopy(st); m[p]["payee_id"] = "payee_univ_x" if m[p]["payee_id"] != "payee_univ_x" else "payee_landlord_chen"
    assert_fix_removes(w, m, "payee_mismatch", True)
    m = copy.deepcopy(st); m[p]["payee_id"] = "payee_attacker"
    assert_fix_removes(w, m, "unknown_payee", True)
    m = copy.deepcopy(st); m[p]["date"] = "2030-01-01"
    r = propose_v3(w, m)
    fx = next(e["fix"] for e in r["errors"] if e["code"] == "late_payment")
    assert fx["latest_date"] == w.passport.obligation(m[p]["obligation_id"]).due and fx["set"]["date"] == fx["latest_date"]
    assert "late_payment" not in codes(validate_plan(w, apply_fixes(m, r["errors"])))
    m = copy.deepcopy(st); m[p]["date"] = "2020-01-01"
    assert_fix_removes(w, m, "date_in_past")      # paying today may then be too early for the CNY; that is a different error
    m = copy.deepcopy(st) + [dict(st[p])]
    assert_fix_removes(w, m, "duplicate_payment", True)
    m = copy.deepcopy(st); m.pop(p)
    assert_fix_removes(w, m, "obligation_unfunded")
    m = copy.deepcopy(st); m[first(st, "convert")]["route_id"] = "route_nope"
    assert_fix_removes(w, m, "unknown_route", True)


def test_fix_insufficient_cny_gives_shortfall_and_the_inr_size_conversion_needs():
    w, st = base("urgent_deadline")
    pays = [s for s in st if s["action"] == "pay"]
    res = propose_v3(w, pays)                                          # no conversion at all
    errs = [e for e in res["errors"] if e["code"] == "insufficient_cny"]
    assert errs
    for e in errs:
        fx = e["fix"]
        assert fx["short_cny"] > 0
        r = fx["add_convert"]
        assert r["send_inr"] == calc.size_conversion(w, fx["short_cny"], r["route_id"], r["date"])["send_inr"]     # same number size_conversion returns
    now = assert_fix_removes(w, pays, "insufficient_cny")
    # the cheapest on-time route for the early deposit (due in 2 days) must be a 1-day route
    first_fix = errs[0]["fix"]["add_convert"]
    assert next(r for r in ROUTES if r.id == first_fix["route_id"]).days <= 1
    # a pay date no route can reach: no add_convert, the earliest date is named
    w2 = build_scenario_world("urgent_deadline")
    r2 = propose_v3(w2, [{"action": "pay", "date": "2026-10-12", "obligation_id": "obl_deposit_1", "payee_id": "payee_landlord_chen", "amount_cny": 6000},
                         {"action": "pay", "date": "2026-11-13", "obligation_id": "obl_tuition_1", "payee_id": "payee_univ_x", "amount_cny": 30000}])
    fx = next(e["fix"] for e in r2["errors"] if e["code"] == "insufficient_cny")
    assert "add_convert" in fx and fx["add_convert"]["route_id"] == "route_inr_cny_2" or "earliest_pay_date" in fx


def test_fix_insufficient_inr_moves_the_excess_to_the_parent():
    w, st = base("urgent_deadline")
    c = first(st, "convert")
    m = copy.deepcopy(st); m[c]["send_inr"] = 700000                   # the student has 600,000
    res = propose_v3(w, m)
    e = next(e for e in res["errors"] if e["code"] == "insufficient_inr")
    assert e["fix"]["over_inr"] == pytest.approx(100000) and e["fix"]["add_convert"]["remitter"] == "parent" and e["fix"]["set"]["send_inr"] <= 600000
    now = assert_fix_removes(w, m, "insufficient_inr", True)
    assert any(x["code"] == "parent_remitter" for x in now.warnings)
    # delivered CNY is preserved by the parent conversion (at least what the original step would have delivered)
    assert now.metrics["delivered_cny"] >= validate_plan(w, m).metrics["delivered_cny"] - 1e-6


def test_fix_rate_target_reserve_moves_inr_to_the_parent():
    w, st = base("rate_target")
    m = [{"action": "convert", "date": "2026-10-12", "send_inr": 615000, "route_id": "route_inr_cny_3", "remitter": "student"}] + [s for s in st if s["action"] == "pay"]
    assert codes(validate_plan(w, m)) == ["rate_target_reserve"]
    e = next(e for e in propose_v3(w, m)["errors"] if e["code"] == "rate_target_reserve")
    assert e["fix"]["over_inr"] > 0 and e["fix"]["add_convert"]["remitter"] == "parent"
    assert_fix_removes(w, m, "rate_target_reserve", True)


def test_fix_safe_quota_exceeded_stages_the_rest_next_january():
    w = build_scenario_world("safe_quota_tuition")
    quota = safe_quota_inr()
    bad = [{"action": "convert", "date": "2026-10-12", "send_inr": 5_800_000, "route_id": "route_inr_cny_3", "remitter": "student"},
           {"action": "pay", "date": "2027-01-15", "obligation_id": "obl_tuition_1", "payee_id": "payee_univ_x", "amount_cny": 400000}]
    res = propose_v3(w, bad)
    fx = next(e["fix"] for e in res["errors"] if e["code"] == "safe_quota_exceeded")
    assert fx["max_send_inr"] == round(quota) and fx["stage_on"] == "2027-01-01" and fx["set"]["send_inr"] == int(quota)
    assert fx["add_convert"]["date"] == "2027-01-01"
    now = assert_fix_removes(w, bad, "safe_quota_exceeded", True)
    assert now.metrics["delivered_cny"] >= validate_plan(w, bad).metrics["delivered_cny"] - 1e-6
    w.passport.safe_used_inr["2026"] = quota - 100                       # no room left this year: move the whole step to January
    res = propose_v3(w, bad[:1] + bad[1:])
    fx = next(e["fix"] for e in res["errors"] if e["code"] == "safe_quota_exceeded")
    assert fx["set"] == {"date": "2027-01-01"}


def test_fix_route_too_slow_names_a_convert_by_date_and_faster_routes():
    w, st = base("urgent_deadline")
    m = copy.deepcopy(st)
    c = first(m, "convert")
    m[c]["route_id"] = "route_inr_cny_3"                                 # 3 days, the deposit is paid before it arrives
    res = propose_v3(w, m)
    fx = next(e["fix"] for e in res["errors"] if e["code"] == "route_too_slow")
    assert fx["faster_route_ids"] and "route_inr_cny_3" not in fx["faster_route_ids"] and fx["step"] == c
    assert_fix_removes(w, m, "route_too_slow", True)
    pay_d = date.fromisoformat(fx["pay_date"])
    if "convert_by" in fx:
        assert date.fromisoformat(fx["convert_by"]) + timedelta(days=3) <= pay_d
    # when converting earlier is impossible (the pay date is today+2 and the route takes 3), only the faster route is offered
    m2 = copy.deepcopy(m)
    p = first(m2, "pay")
    m2[p]["date"] = "2026-10-14"
    fx2 = next(e["fix"] for e in propose_v3(w, m2)["errors"] if e["code"] == "route_too_slow")
    assert "convert_by" not in fx2 and fx2["set"]["route_id"] == fx2["faster_route_ids"][0]


def test_fixes_are_additive_and_only_in_v3():
    w, st = base("urgent_deadline")
    bad = copy.deepcopy(st)
    bad[first(bad, "pay")]["amount_cny"] -= 1
    r1, r2, r3 = (PlanningToolbox(w, fmt=f).call("propose_plan", {"steps": bad, "rationale": "x"}) for f in ("v1", "v2", "v3"))
    assert r1 == r2 and all("fix" not in e for e in r1["errors"])
    assert [{k: v for k, v in e.items() if k != "fix"} for e in r3["errors"]] == r1["errors"]      # same code, message, hint, step
    assert any("fix" in e for e in r3["errors"])
    for f in ("v1", "v2"):
        assert all("fix" not in e for e in json.loads(_tool_message("x", r3, "propose_plan", f)["content"])["errors"]) or f == "v1"
    assert "fix" in json.loads(_tool_message("x", r3, "propose_plan", "v3")["content"])["errors"][0]
    # the validator itself is untouched: its errors carry no fix key
    assert all("fix" not in e for e in validate_plan(w, bad).errors)
    # codes without a derivable correction get no fix and no crash
    assert derive_fixes(w, bad, [{"code": "bad_step", "message": "m"}, {"code": "lrs_exceeded", "step": 99}, {"code": "amount_mismatch", "step": "x"}]) == [None, None, None]
    assert derive_fixes(w, None, [{"code": "amount_mismatch", "step": 0}]) == [None]


# ----------------------------------------------------------------------------------------------- v1/v2 unchanged
def _stable(txt: str) -> str:
    """v1 passes the full get_rates result through, which carries a wall-clock fetch timestamp; mask it for the comparison."""
    import re
    return re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "T", txt)


def test_v1_and_v2_prompts_tools_and_outputs_are_byte_for_byte_unchanged():
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    assert SYSTEM == snap["system"] and TOOL_SPECS == snap["tool_specs"]
    for sid, d in snap["scenarios"].items():
        w = build_scenario_world(sid)
        tb = PlanningToolbox(w)
        for n, a in [("read_passport", {}), ("list_obligations", {}), ("get_rates", {}), ("forecast_runway", {}),
                     ("get_routes", {"send_inr": 200000, "due": "2026-11-15"}), ("check_corridor", {"amount_inr": 200000, "purpose": "tuition"})]:
            res = tb.call(n, a)
            for f in ("v1", "v2"):
                assert _stable(_tool_message("x", res, n, f)["content"]) == _stable(d[n][f]), (sid, n, f)
        steps = DeterministicPlanner().plan(build_scenario_world(sid)).steps
        assert json.loads(json.dumps(steps)) == d["det_steps"]
        bad = copy.deepcopy(steps)
        for s in bad:
            if s["action"] == "pay":
                s["amount_cny"] -= 1
        for key, plan in (("propose_bad", bad), ("propose_ok", steps)):
            res = PlanningToolbox(build_scenario_world(sid)).call("propose_plan", {"steps": plan, "rationale": "x"})
            for f in ("v1", "v2"):
                assert _tool_message("x", res, "propose_plan", f)["content"] == d[key][f], (sid, key, f)


def test_agentic_planner_default_is_still_v2_and_v3_is_opt_in(monkeypatch):
    monkeypatch.delenv("OASIS_PLANNER_FORMAT", raising=False)
    assert planner_format() == "v2"
    llm = SimpleNamespace(name="groq", errors=[])
    p = AgenticPlanner(llm)
    assert p.fmt == "v2" and p.system is SYSTEM and p.tool_specs is TOOL_SPECS
    monkeypatch.setenv("OASIS_PLANNER_FORMAT", "v3")
    p3 = AgenticPlanner(llm)
    assert p3.fmt == "v3" and p3.system is SYSTEM_V3 and p3.tool_specs is TOOL_SPECS_V3
    assert AgenticPlanner(llm, fmt="v1").system is SYSTEM


def test_v3_prompt_is_at_most_60_percent_of_v2_and_says_what_it_must():
    assert len(SYSTEM_V3) <= 0.6 * len(SYSTEM), (len(SYSTEM_V3), len(SYSTEM))
    for needle in ("facts_sheet", "size_conversion", "exactly", "fix", "parent", "SAFE", "January", "propose_plan", "once"):
        assert needle in SYSTEM_V3, needle


@pytest.mark.parametrize("fmt", ["v1", "v2", "v3"])
def test_offline_planner_is_deterministic_and_identical_under_every_format(fmt):
    for sid in ALL:
        a = DeterministicPlanner(fmt).plan(build_scenario_world(sid))
        b = DeterministicPlanner("v2").plan(build_scenario_world(sid))
        assert a.valid and a.steps == b.steps and a.iterations == b.iterations, sid
        assert a.steps == DeterministicPlanner(fmt).plan(build_scenario_world(sid)).steps


# --------------------------------------------------- end to end: a scripted "model" that uses the calculators
class ScriptedCalcModel:
    """Behaves like a careful model under the v3 protocol: facts_sheet, then size_conversion for the conversion, then one
    propose_plan, then applies the `fix` of every error. Deterministic. Sees only what the messages carry."""

    def __init__(self):
        self.phase, self.steps, self.pending = 0, None, None

    def __call__(self, messages, tools):
        tool_results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if self.phase == 0:
            self.phase = 1
            return [("facts_sheet", {})]
        if self.phase == 1:
            f = tool_results[-1]
            today = date.fromisoformat(f["today"])
            obs = f["obligations"]
            routes = [r for r in f["routes"] if not r.get("bank")]
            first_due = date.fromisoformat(min(o["due"] for o in obs))
            budget = (first_due - today).days - 3
            pool = [r for r in routes if r["days"] <= budget] or [min(routes, key=lambda r: r["days"])]
            route = min(pool, key=lambda r: r["spread"] + r["pct_fee"])
            self.pending = {"f": f, "route": route, "obs": obs, "today": today}
            if f["cny_shortfall"] <= 0:
                self.phase = 3
                return self._propose(None)
            self.phase = 2
            return [("size_conversion", {"target_cny": f["cny_shortfall"], "route_id": route["id"], "convert_date": f["today"],
                                         "remitter": "student", "due": first_due.isoformat()})]
        if self.phase == 2:
            self.phase = 3
            return self._propose(tool_results[-1])
        res = tool_results[-1]
        if res["valid"]:
            return []
        self.steps = apply_fixes(self.steps, res["errors"])
        return [("propose_plan", {"steps": self.steps, "rationale": "applied the fixes"})]

    def _propose(self, sized):
        p = self.pending
        steps, arrive = [], p["today"]
        if sized is not None:
            steps.append({"action": "convert", "date": p["f"]["today"], "send_inr": sized["send_inr"], "route_id": sized["route_id"], "remitter": "student"})
            arrive = date.fromisoformat(sized["arrives_on"])
        for o in p["obs"]:
            d = max(p["today"], date.fromisoformat(o["due"]) - timedelta(days=2))
            d = min(max(d, arrive), date.fromisoformat(o["due"]))
            steps.append({"action": "pay", "date": d.isoformat(), "obligation_id": o["id"], "payee_id": o["payee_id"], "amount_cny": o["amount_cny"]})
        self.steps = steps
        return [("propose_plan", {"steps": steps, "rationale": "sized with size_conversion"})]


class ModelClient:
    """An OpenAI-style client whose completions come from a policy function over the request messages."""

    def __init__(self, policy):
        self.policy, self.calls, self.n = policy, [], 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        tcs = []
        for name, args in self.policy(kw["messages"], kw["tools"]):
            self.n += 1
            tcs.append(SimpleNamespace(id=f"call_{self.n}", function=SimpleNamespace(name=name, arguments=json.dumps(args))))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=tcs or None))],
                               usage=SimpleNamespace(total_tokens=1000))


def run_scripted(tmp_path, sid, fmt="v3"):
    client = ModelClient(ScriptedCalcModel())
    llm = GroqLLM(client=client, cache_dir=tmp_path / sid, sleep=lambda s: None, rpm=0)
    w = build_scenario_world(sid, llm)
    return w, client, AgenticPlanner(llm, fmt=fmt).plan(w, ALL_SCENARIOS[sid].goal)


@pytest.mark.parametrize("sid", ALL)
def test_scripted_model_uses_the_calculators_end_to_end_through_groqllm(tmp_path, sid):
    w, client, res = run_scripted(tmp_path, sid)
    tools_called = [t["tool"] for t in res.trace if t["type"] == "tool_call"]
    assert tools_called[0] == "facts_sheet"                                   # facts first
    assert res.planner == "groq-tools" and res.valid and not res.fell_back, (sid, res.fallback_reason, [e["code"] for t in res.trace if t["type"] == "proposal" for e in t["validation"]["errors"]])
    assert res.iterations <= 4
    sent = client.calls[0]
    assert sent["messages"][0]["content"] == SYSTEM_V3 and [t["function"]["name"] for t in sent["tools"]] == ["facts_sheet", "size_conversion", "propose_plan"]
    if any(s["action"] == "convert" for s in res.steps):
        assert "size_conversion" in tools_called
    # the validator, not the script, decided: re-validate the final steps independently
    assert validate_plan(build_scenario_world(sid), res.steps).ok
    assert any(m["role"] == "tool" for m in client.calls[-1]["messages"])


def test_scripted_protocol_shows_fix_driven_revision(tmp_path):
    w, client, res = run_scripted(tmp_path, "shortfall")                    # needs the parent: first proposal is insufficient_inr
    props = [t for t in res.trace if t["type"] == "proposal"]
    assert len(props) == 2 and not props[0]["validation"]["valid"] and props[1]["validation"]["valid"]
    tool_msgs = [json.loads(m["content"]) for m in client.calls[-1]["messages"] if m["role"] == "tool"]
    assert any("fix" in e for r in tool_msgs for e in r.get("errors", []))   # the model saw the fix in the v3 view
    assert any(s.get("remitter") == "parent" for s in res.steps)


def test_v2_prompt_and_tools_are_what_a_v2_run_sends(tmp_path):
    client = ModelClient(lambda m, t: [])
    llm = GroqLLM(client=client, cache_dir=tmp_path, sleep=lambda s: None, rpm=0)
    AgenticPlanner(llm, fmt="v2").plan(build_scenario_world("shortfall", llm))
    assert client.calls[0]["messages"][0]["content"] == SYSTEM and client.calls[0]["tools"] == TOOL_SPECS


# -------------------------------------------------------------------------------------------- no side effects
def _state(w):
    return hashlib.sha256(json.dumps([w.passport.model_dump(), len(w.audit.entries), w.ledger.money_lost(), len(w.plans), w.day_index],
                                     sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.parametrize("sid", ["shortfall", "safe_quota_tuition", "heldout_year_boundary", "rate_target"])
def test_v3_tools_move_no_money_and_change_no_state(sid):
    w = build_scenario_world(sid)
    before = _state(w)
    tb = PlanningToolbox(w, fmt="v3")
    f = tb.call("facts_sheet")
    for r in ROUTES:
        for rem in ("student", "parent"):
            assert "error" not in tb.call("size_conversion", {"target_cny": 5000, "route_id": r.id, "convert_date": w.today.isoformat(), "remitter": rem, "due": "2027-03-01"})
    assert tb.call("facts_sheet") == f                                        # pure: same answer twice
    bad = [{"action": "pay", "date": w.today.isoformat(), "obligation_id": "x", "payee_id": "y", "amount_cny": 1}]
    assert not tb.call("propose_plan", {"steps": bad, "rationale": "x"})["valid"]
    assert _state(w) == before
    assert "facts_sheet" not in [n for n in ("pay_everything", "execute_plan", "convert_now")]
    for n in ("pay_everything", "execute_plan", "convert_now"):
        assert tb.call(n, {})["error"].startswith("unknown tool")


# ------------------------------------------------------------------------------------------- eval plumbing (offline)
def _row(fmt, model, rep, sid, ok, codes_=None, fb=None, tokens=12000):
    return {"scenario": sid, "format": fmt, "model_requested": model, "model": model, "rep": rep, "valid": True, "fell_back": not ok,
            "fallback_reason": None if ok else (fb or "no valid plan after 2 proposal(s)"), "model_valid_without_fallback": ok,
            "iterations_to_valid": 1 if ok else None, "error_counts": codes_ or {}, "tokens": tokens, "model_calls": 5, "seconds": 30, "model_proposals": 1}


def test_fisher_exact_reproduces_the_documented_p_values():
    from eval.planning_v3 import fisher_exact
    assert fisher_exact(5, 2, 6, 15) == pytest.approx(0.076, abs=0.002)       # docs: new 5/7 vs old 6/21
    assert fisher_exact(8, 3, 9, 16) == pytest.approx(0.070, abs=0.002)       # docs: pooled 8/11 vs 9/25
    assert fisher_exact(3, 1, 3, 1) == pytest.approx(1.0)
    assert fisher_exact(10, 0, 0, 10) < 1e-4


def test_report_applies_the_pre_registered_rule(tmp_path, monkeypatch):
    import eval.planning_v3 as pv
    monkeypatch.setattr(pv, "MD", tmp_path / "r.md"); monkeypatch.setattr(pv, "SUMMARY", tmp_path / "r.json")
    M = "m1"

    def cell(fmt, valid_per_rep):
        out = []
        for rep, nvalid in enumerate(valid_per_rep):
            for k, sid in enumerate(pv.SCENARIO_IDS):
                out.append(_row(fmt, M, rep, sid, k < nvalid, {"amount_mismatch": 2, "unknown_route": 1} if k >= nvalid else {}))
        return out
    s = pv.summarize(cell("v2", [4, 5]) + cell("v3", [10, 11]))
    d = s["decision"]
    assert d["verdict"] == "v3 becomes default" and d["v2_spread_pp"] == pytest.approx(100 / 12) and d["condition_b_heldout_no_regression"]
    assert s["cells"][f"v3 | {M}"]["arithmetic_share"] == pytest.approx(2 / 3)
    assert pv.summarize(cell("v2", [4, 8]) + cell("v3", [10, 11]))["decision"]["verdict"] == "v2 stays default"      # gain not beyond spread
    assert pv.summarize(cell("v2", [4]) + cell("v3", [10]))["decision"]["verdict"] == "INCOMPLETE"
    md = pv.render(cell("v2", [4, 5]) + cell("v3", [10, 11]))
    assert "Pre-registered decision rule" in md and "Fisher exact" in md and "Verdict: v3 becomes default" in md
    assert "not been run" in pv.render([])
    monkeypatch.setattr(pv, "ROWS", tmp_path / "rows.json")
    pv.save(cell("v2", [4]))
    assert "Model-only valid" in pv.report() and pv.main(["--report"]) == 0


def test_eval_run_is_resumable_keyed_and_never_records_budget_artifacts(tmp_path, monkeypatch):
    import eval.planning_v3 as pv
    import oasis.agent.llm as llm_mod
    monkeypatch.setattr(pv, "ROWS", tmp_path / "rows.json"); monkeypatch.setattr(pv, "MD", tmp_path / "r.md"); monkeypatch.setattr(pv, "SUMMARY", tmp_path / "r.json")
    monkeypatch.setattr(pv.config, "GROQ_API_KEY", "x")
    made = []

    class FakeLLM:
        def __init__(self, **kw): made.append(kw)
    monkeypatch.setattr(llm_mod, "GroqLLM", FakeLLM)
    seen, quota_ok = [], False

    def fake_run(sid, planner):
        seen.append((sid, planner.fmt, planner.token_cap))
        r = _row("?", "?", 0, sid, True)
        if sid == "tight_runway" and not quota_ok:
            r.update(model_valid_without_fallback=False, valid=True, fell_back=True, fallback_reason="QuotaExhausted: daily")
        return r
    monkeypatch.setattr(pv, "run_scenario", fake_run)
    assert pv.main(["--format", "v3", "--model", "m1", "--repeats", "1", "--cap", "100000", "--per-plan-cap", "20000"]) == 3      # quota stop
    assert [r["scenario"] for r in pv.load()] == ["shortfall"] and made[0]["model"] == made[0]["fallback_model"] == "m1"
    seen.clear()
    quota_ok = True
    assert pv.main(["--format", "v3", "--model", "m1", "--repeats", "1", "--cap", "1000000", "--per-plan-cap", "20000"]) == 0     # resumes
    assert seen[0][0] == "tight_runway" and len(pv.load()) == 12 and all(s[1] == "v3" and s[2] == 20000 for s in seen)
    seen.clear()
    assert pv.main(["--format", "v2", "--model", "m1", "--repeats", "1", "--cap", "30000", "--per-plan-cap", "20000"]) == 2        # cap leaves room for 1 plan only
    assert len(seen) == 1 and {(r["format"], r["model_requested"]) for r in pv.load()} == {("v3", "m1"), ("v2", "m1")}
    assert len(pv.load()) == 13
