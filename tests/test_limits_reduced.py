"""Tests for the known-limitation reductions: exact fen arithmetic, scientific-notation amounts, strict key mode, a login lockout that
survives a restart, cumulative China outbound use, and stale route prices. Hermetic."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from oasis.agent.llm import OfflineLLM, has_exponent
from oasis.mock import money
from oasis.world import Features, World


# ----------------------------------------------------------------------------------------------- exact fen arithmetic
def test_money_is_exact_on_whole_fen():
    assert money.add(0.1, 0.2) == 0.3 and 0.1 + 0.2 != 0.3
    acc = 0.0
    for _ in range(1000):
        acc = money.add(acc, 0.01)
    assert acc == 10.0                                       # a thousand fen, no drift (a float sum gives 9.999999999999831)
    assert money.sub(10.0, 0.01) == 9.99 and money.fen(2.675) == 2.68      # half-even on the decimal form


def test_ledger_transfers_do_not_drift():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    w.credit_fx("USD", 1000.0)
    a, b = w.ledger.accounts["acct_student_usd"], w.ledger.open("x_usd", "x", currency="USD")
    tok = lambda amt: w.ledger.mint_tool_token(w.ledger.executor_credential(), intent_id=None, from_ref=a.ref, to_ref=b.ref, amount=amt, currency="USD")
    for _ in range(100):
        w.ledger.transfer(tok(0.07), a.ref, b.ref, 0.07, "USD")
    assert b.balance == 7.0 and a.balance == 993.0


# ----------------------------------------------------------------------------------------------- scientific notation
def test_scientific_notation_is_never_read_as_a_small_amount():
    assert has_exponent("1e5") and has_exponent("2.5E3 CNY") and has_exponent("1,0e2") and not has_exponent("30,000.00") and not has_exponent("300 e")
    from oasis.agent.pipeline import OasisAgent, Request
    w = World(Features.full(), OfflineLLM(susceptible=True))
    out = OasisAgent(w).handle(Request("Payee: University X Finance Office\nAccount: 6228480000000001\nAmount: 1e5\n"))
    assert out.status == "held" and out.card["rule"] == "extract_low_confidence"      # asked to confirm; nothing guessed
    assert w.ledger.transfers == []


# ----------------------------------------------------------------------------------------------- key passphrase strict mode
def test_strict_mode_refuses_plaintext_key_files(tmp_path, monkeypatch):
    from oasis.trust import keyfile
    monkeypatch.delenv("OASIS_KEY_PASSPHRASE", raising=False)
    p = tmp_path / "k.json"
    keyfile.write_secret_json(p, {"key": "abc"})                       # default: allowed (plaintext, the documented demo mode)
    monkeypatch.setenv("OASIS_REQUIRE_KEY_PASSPHRASE", "1")
    with pytest.raises(keyfile.KeyFileError, match="plaintext"):
        keyfile.write_secret_json(tmp_path / "k2.json", {"key": "abc"})
    with pytest.raises(keyfile.KeyFileError, match="plaintext"):
        keyfile.read_secret_json(p)
    monkeypatch.setenv("OASIS_KEY_PASSPHRASE", "correct horse battery staple")
    keyfile.write_secret_json(tmp_path / "k3.json", {"key": "abc"})
    assert keyfile.read_secret_json(tmp_path / "k3.json") == {"key": "abc"}


def test_fingerprint_endpoint_reports_key_encryption(api_client):
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    r = TestClient(api.app).get("/api/trust/fingerprint").json()
    assert r["keys_encrypted"] is False


# ----------------------------------------------------------------------------------------------- login lockout survives a restart
def test_lockout_survives_a_restart(tmp_path):
    from oasis.api.ratelimit import RateLimiter
    from oasis.storage import SqliteStore
    db = tmp_path / "t.db"
    s1 = SqliteStore(db, key_path=tmp_path / "k.json")
    rl = RateLimiter(3, 60.0, store=s1, name="throttle:login")
    for _ in range(3):
        rl.record("login:1.2.3.4")
    assert rl.blocked("login:1.2.3.4")
    s1.close()
    s2 = SqliteStore(db, key_path=tmp_path / "k.json")                  # a new process opens the same database
    rl2 = RateLimiter(3, 60.0, store=s2, name="throttle:login")
    assert rl2.blocked("login:1.2.3.4") and not rl2.blocked("login:9.9.9.9")
    now = [rl2._clock() + 120]                                          # the window passes
    rl3 = RateLimiter(3, 60.0, store=s2, name="throttle:login")
    rl3._clock = lambda: now[0]
    assert not rl3.blocked("login:1.2.3.4")


def test_in_memory_limiter_is_unchanged():
    from oasis.api.ratelimit import RateLimiter
    t = [0.0]
    rl = RateLimiter(2, 60.0, clock=lambda: t[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    t[0] = 61
    assert rl.allow("a")


# ----------------------------------------------------------------------------------------------- cumulative China outbound use
def _cn_world(cny=500_000.0, usd=40_000.0, kind="living"):
    """`kind` 'living' uses the SAFE USD 50,000 quota; 'tuition' may be bought outside it (SAFE Tianjin bureau, 2025-07-14)."""
    from oasis.agent import fx_exec
    w = World(Features.full(), OfflineLLM(susceptible=True), seed=7, deterministic=True)
    w.ledger.accounts["acct_student_cny"].balance = cny
    w.sync_balances()
    w.passport.set_balance("INR", 0.0)
    fx_exec.add_demo_obligation(w, "us", usd, 38)
    w.passport.obligations[-1].type = kind
    return w


def test_safe_quota_counts_earlier_conversions():
    from oasis.planning import fxplan
    from oasis.agent.planner import DeterministicFxPlanner
    w = _cn_world()
    assert DeterministicFxPlanner().plan(w).valid                       # USD 40,000 is inside the USD 50,000 quota
    w.passport.cn_outbound_usd[str(w.today.year)] = 30_000.0           # USD 30,000 already sent out of CNY this year
    v = DeterministicFxPlanner().plan(w).validation
    assert "annual_limit_exceeded" in {e["code"] for e in v["errors"]}
    w.passport.cn_outbound_usd[str(w.today.year)] = 0.0
    assert fxplan.validate_fx_plan(w, DeterministicFxPlanner().plan(w).steps).ok


def test_conversion_records_cumulative_use_and_blocks_at_execution():
    from oasis.agent.pipeline import OasisAgent
    from oasis.agent.plan_exec import accept_plan, execute_due
    from oasis.agent.planner import DeterministicFxPlanner, build_fx_record
    from eval.approver import SimulatedHumans
    w = _cn_world(usd=25_000.0)               # about CNY 167k: under the CNY 200k hard limit, so only the quota can block it
    agent = OasisAgent(w)
    rec = build_fx_record(w, DeterministicFxPlanner().plan(w))
    accept_plan(agent, rec["id"])
    w.passport.cn_outbound_usd[str(w.today.year)] = 30_000.0           # use after acceptance: re-checked at execution
    r = execute_due(agent, rec["id"], SimulatedHumans())
    assert r["ran"][0]["status"] == "blocked" and "annual_limit_exceeded" in r["ran"][0]["note"]
    w.passport.cn_outbound_usd[str(w.today.year)] = 0.0
    execute_due(agent, rec["id"], SimulatedHumans())
    assert 20_000 < w.passport.cn_outbound_usd[str(w.today.year)] < 30_000


# ----------------------------------------------------------------------------------------------- stale route prices
def test_old_sourced_and_estimated_prices_are_flagged_stale():
    from datetime import date
    from oasis.corridors import core as cor
    from oasis.mock import fx
    from oasis.mock.rates import MockRates
    table = fx.per_usd(MockRates().mid(0))
    fresh = cor.compare("INR-USD", 1000, table, today=date(2026, 10, 20))
    assert not any(o["stale"] for o in fresh["options"])
    old = cor.compare("INR-USD", 1000, table, today=date(2026, 12, 1))
    by = {o["route"]: o for o in old["options"]}
    assert by["Digital remitter"]["stale"] and by["Typical bank SWIFT transfer"]["stale"] and by["Digital remitter"]["price_age_days"] == 49
    assert not by["Education payment specialist"]["stale"]                # an assumed price has no date to go stale
    assert all(o["stale"] is False and o["price_age_days"] is None for o in cor.compare("INR-USD", 1000, table)["options"])
    assert cor.compare("INR-CNY", 1000, table, today=date(2026, 12, 1))["options"][0]["stale"] is False        # legacy prices are mock


def test_validator_warns_on_a_stale_price():
    from oasis.agent.planner import DeterministicFxPlanner
    from oasis.agent import fx_exec
    w = World(Features.full(), OfflineLLM(susceptible=True), seed=7, deterministic=True)
    w.passport.set_balance("INR", 700000.0)
    fx_exec.add_demo_obligation(w, "us", 5000.0, 90)
    steps = DeterministicFxPlanner().plan(w).steps
    w.advance(days=45)
    from oasis.planning.fxplan import validate_fx_plan
    steps = [{**s, "date": w.today.isoformat()} if s["action"] == "convert" else s for s in steps]
    assert any(x["code"] == "price_stale" for x in validate_fx_plan(w, steps).warnings)


def test_tuition_does_not_use_the_safe_quota():
    from oasis.agent.pipeline import OasisAgent
    from oasis.agent.plan_exec import accept_plan, execute_due
    from oasis.agent.planner import DeterministicFxPlanner, build_fx_record
    from eval.approver import SimulatedHumans
    w = _cn_world(usd=25_000.0, kind="tuition")
    w.passport.cn_outbound_usd[str(w.today.year)] = 45_000.0           # the quota is almost used up by other spending
    res = DeterministicFxPlanner().plan(w)
    assert res.valid and any(x["code"] == "safe_tuition_documents" for x in res.validation["warnings"])
    agent = OasisAgent(w)
    rec = build_fx_record(w, res)
    accept_plan(agent, rec["id"])
    r = execute_due(agent, rec["id"], SimulatedHumans())
    assert r["ran"][0]["status"] == "done"                              # not blocked by the quota
    assert w.passport.cn_outbound_usd[str(w.today.year)] == 45_000.0   # and it did not count against it


def test_corridor_check_shows_the_tuition_exemption_with_its_source():
    from oasis.corridors import core as cor
    from oasis.mock import fx
    from oasis.mock.rates import MockRates
    t = fx.per_usd(MockRates().mid(0))
    tu = {f["rule"]: f for f in cor.check("CNY-USD", 500_000, "tuition", t)["findings"]}
    assert tu["safe_annual_quota"]["severity"] == "info" and tu["safe_annual_quota"]["status"] == "confirmed-primary" and "safe.gov.cn" in tu["safe_annual_quota"]["source"]
    liv = {f["rule"]: f for f in cor.check("CNY-USD", 500_000, "living", t)["findings"]}
    assert liv["safe_annual_quota"]["severity"] == "warn"                # other purposes still hit the quota


def test_sanctions_screening_covers_four_public_lists():
    from oasis.screening import Sanctions, screen_payee
    s = Sanctions()
    assert {"OFAC", "UN", "UK", "EU"} <= set(s.meta["lists"]) and all(v["count"] > 500 for v in s.meta["lists"].values())
    hits = s.screen("ERIC BADEGE", limit=10)
    assert {"UN", "UK", "EU"} <= {h["list"] for h in hits} and all(h["score"] >= 0.9 for h in hits)
    assert s.screen("University X Finance Office") == [] and s.screen("Chen Wei") == []             # the demo identities stay clean
    assert "OFAC" in screen_payee("Bank Melli Iran")["sanctions"]["caveat"] and "EU" in screen_payee("Bank Melli Iran")["sanctions"]["caveat"]


def test_an_explicit_sanctions_file_still_loads_alone():
    from oasis.screening import DATA, Sanctions
    only = Sanctions(DATA)
    assert set(only.meta.get("lists", {"OFAC": 1})) == {"OFAC"}
