"""Tests for the external-review fixes: forged proof packs, live-replay demo, LLM risk scorer, per-extraction serving
model, parent wording, cumulative SAFE quota and per-purpose TCS. No test touches the network (fake clients only)."""
import copy
import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from eval import runner
from eval.approver import SimulatedHumans
from eval.scenarios import all_scenarios, tuition
from oasis import config
from oasis.agent import i18n
from oasis.agent.llm import GroqLLM, OfflineLLM, heuristic_risk, regex_fields
from oasis.agent.parent import parent_view
from oasis.agent.pipeline import OasisAgent, Request
from oasis.agent.replay import (FIXTURE_DIR, OFFLINE_LABEL, DemoLiveLLM, ai_summary, fixture_info)
from oasis.api import main as api
from oasis.demo import DemoRunner, new_demo_world, play
from oasis.passport.models import Level
from oasis.planning.validator import safe_quota_inr, validate_plan
from oasis.proof.pack import verify_proof_pack
from oasis.trust import corridor
from oasis.trust.crypto import HybridSigner, canonical, sha256_hex
from oasis.trust.intents import strip_sigs
from oasis.trust.keystore import fingerprint, load_or_create_signer
from oasis.world import Features, World
from tests.test_llm_groq import Err, FakeClient


# ============================================================================== 2. forged proof packs
def _paid_world():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    o = OasisAgent(w).handle(Request(tuition()), SimulatedHumans())
    assert o.status == "paid" and o.proof_id
    return w, w.proofs[o.proof_id]


def forge(pack: dict, **changes) -> dict:
    """The reviewer's attack: change the payment (amount / account), re-sign everything with FRESH keys and embed them."""
    evil = HybridSigner()
    p = copy.deepcopy(pack)
    p["intent"].update(changes)
    body = strip_sigs(p["intent"])
    p["intent"]["signatures"] = evil.sign(canonical(body))
    p["intent_hash"] = sha256_hex(canonical(body))
    if p.get("anchor"):
        p["anchor"] = {**p["anchor"], "digest": p["intent_hash"]}
    p["trust_public_keys"] = evil.public_keys()
    nobody = {k: v for k, v in p.items() if k not in ("pack_signatures", "pack_public_keys")}
    p["pack_signatures"], p["pack_public_keys"] = evil.sign(canonical(nobody)), evil.public_keys()
    return p


def test_genuine_pack_passes_with_pinned_fingerprint_and_chain():
    w, pack = _paid_world()
    res = verify_proof_pack(pack, {w.trust_fingerprint()}, w.anchor)
    assert res["ok"] and res["key_pinned"] is True and res["anchor_on_chain"] is True and res["consistent"]


def test_forged_pack_with_fresh_keys_is_self_consistent_but_fails_the_pin():
    w, pack = _paid_world()
    for changes in ({"amount": 1.0}, {"account_ref": "6666000000000002"}, {"amount": 99999.0, "account_ref": "6666000000000002"}):
        bad = forge(pack, **changes)
        res = verify_proof_pack(bad, {w.trust_fingerprint()}, w.anchor)
        assert res["pack_signature"] and res["intent_signature"] and res["intent_hash"]     # internally perfect ...
        assert res["key_pinned"] is False and not res["ok"]                                  # ... but not signed by a trusted key
        assert res["anchor_on_chain"] is False                                               # and the chain never saw that digest
    assert not verify_proof_pack(forge(pack, amount=1.0), {w.trust_fingerprint()})["ok"]      # even without a chain


def test_pack_with_only_trusted_trust_keys_but_foreign_pack_signer_fails():
    w, pack = _paid_world()
    evil = HybridSigner()
    p = copy.deepcopy(pack)
    body = {k: v for k, v in p.items() if k not in ("pack_signatures", "pack_public_keys")}
    p["pack_signatures"], p["pack_public_keys"] = evil.sign(canonical(body)), evil.public_keys()
    res = verify_proof_pack(p, {w.trust_fingerprint()}, w.anchor)
    assert res["pack_signature"] and res["key_pinned"] is False and not res["ok"]


def test_standalone_verification_never_reports_ok_and_anchor_is_not_checked():
    w, pack = _paid_world()
    res = verify_proof_pack(pack)
    assert res["key_pinned"] is None and res["anchor_on_chain"] is None
    assert res["consistent"] and not res["ok"]


def test_anchor_must_exist_on_an_intact_chain():
    w, pack = _paid_world()
    fp = {w.trust_fingerprint()}
    assert verify_proof_pack(pack, fp, w.anchor)["anchor_on_chain"] is True
    w.anchor.blocks[0]["digest"] = "0" * 64                     # tamper with the chain
    assert verify_proof_pack(pack, fp, w.anchor)["anchor_on_chain"] is False
    w2, pack2 = _paid_world()
    w2.anchor.blocks.clear()                                     # block missing altogether
    assert verify_proof_pack(pack2, {w2.trust_fingerprint()}, w2.anchor)["anchor_on_chain"] is False


def test_malformed_pack_fails_instead_of_raising():
    res = verify_proof_pack({"intent": {}}, {"x"})
    assert not res["ok"] and res.get("malformed") is False


def test_keystore_is_stable_across_loads_and_distinct_per_file(tmp_path):
    a1 = load_or_create_signer(tmp_path / "k.json")
    a2 = load_or_create_signer(tmp_path / "k.json")
    b = load_or_create_signer(tmp_path / "other.json")
    assert fingerprint(a1.public_keys()) == fingerprint(a2.public_keys()) != fingerprint(b.public_keys())
    msg = canonical({"x": 1})
    assert a2.verify(msg, a1.sign(msg))                           # same private keys after reload
    d = json.loads((tmp_path / "k.json").read_text())
    d["fingerprint"] = "0" * 64
    (tmp_path / "bad.json").write_text(json.dumps(d))
    with pytest.raises(ValueError):
        load_or_create_signer(tmp_path / "bad.json")


def test_default_key_path_is_git_ignored_and_env_configurable(monkeypatch, tmp_path):
    from oasis.trust.keystore import default_key_path
    monkeypatch.delenv("OASIS_TRUST_KEY", raising=False)
    assert default_key_path() == config.DATA_DIR / "keys" / "trust_key.json"
    monkeypatch.setenv("OASIS_TRUST_KEY", str(tmp_path / "x.json"))
    assert default_key_path() == tmp_path / "x.json"
    ignore = (config.ROOT / ".gitignore").read_text()
    assert "data/keys/" in ignore


def _pay(client):
    o = client.post("/api/intake", json={"text": tuition()}).json()
    r = client.post("/api/approve", json={"pending_id": o["pending_id"], "role": "student"}).json()
    assert r["status"] == "paid"
    return r["proof_id"]


def test_api_pins_the_server_fingerprint_and_rejects_forgeries(api_client):
    c = api_client
    pid = _pay(c)
    fp = c.get("/api/trust/fingerprint").json()
    assert fp["fingerprint"] == api.S.world.trust_fingerprint() and len(fp["fingerprint"]) == 64 and fp["public_keys"]
    pack = c.get(f"/api/proof/{pid}").json()
    assert c.get(f"/api/proof/{pid}/verify").json()["ok"]
    up = c.post("/api/proof/verify", json=pack).json()
    assert up["ok"] and up["pinned_fingerprint"] == fp["fingerprint"]
    bad = c.post("/api/proof/verify", json=forge(pack, amount=1.0, account_ref="6666000000000002")).json()
    assert bad["key_pinned"] is False and not bad["ok"]
    assert not c.post("/api/proof/verify", json={"nonsense": 1}).json()["ok"]


def test_pack_verifies_after_a_server_restart_with_persistent_keys(tmp_path):
    db, keys = str(tmp_path / "o.db"), tmp_path / "trust_key.json"
    s1 = api.Session(db, key_path=keys)
    saved, api.S = api.S, s1
    try:
        c = TestClient(api.app)
        pid = _pay(c)
        fp1 = c.get("/api/trust/fingerprint").json()
        assert fp1["persistent"] and not fp1["demo_keys"]
        pack = c.get(f"/api/proof/{pid}").json()
        api.S = api.Session(db, key_path=keys)                                   # "restart": new process, same key file
        assert c.get("/api/trust/fingerprint").json()["fingerprint"] == fp1["fingerprint"]
        assert c.get(f"/api/proof/{pid}/verify").json()["ok"]
        assert c.post("/api/proof/verify", json=pack).json()["ok"]
        assert not c.post("/api/proof/verify", json=forge(pack, amount=1.0)).json()["ok"]
        api.S = api.Session(db, key_path=tmp_path / "different_keys.json")      # a different key file = a different server
        assert not c.post("/api/proof/verify", json=pack).json()["ok"]
    finally:
        api.S = saved


def test_demo_keys_are_trusted_only_while_the_demo_world_is_active(api_client):
    c = api_client
    c.post("/api/demo/run", json={"run": "legit"})
    assert c.get("/api/trust/fingerprint").json()["demo_keys"] is True
    pid = c.get("/api/state").json()["proofs"][0]
    assert c.get(f"/api/proof/{pid}/verify").json()["ok"]
    c.post("/api/demo/reset")
    assert c.get("/api/trust/fingerprint").json()["demo_keys"] is False


# ============================================================================== 1. live-replay demo
class SmartFake:
    """A fake Groq client that behaves like a model that does NOT follow injections: extraction = the labelled lines,
    risk = 0.9 for pressure language else 0.1, planning = no tool call (the planner then falls back, and says so)."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        system, user = kw["messages"][0]["content"], kw["messages"][-1]["content"]
        content, tool_calls = "{}", None
        if kw.get("tools"):
            content = ""
        elif system.startswith("Extract payment fields"):
            f = regex_fields(user)
            content = json.dumps({**f, "translation": "(English source)", "instruction_like_text": "ignore previous" in user.lower()})
        elif system.startswith("You are a payment-fraud"):
            doc = json.loads(user)["document"]
            urgent = "urgent" in doc.lower() or "24 hours" in doc.lower()
            content = json.dumps({"score": 0.9 if urgent else 0.1, "evidence": ["pressure language"] if urgent else []})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
                               usage=SimpleNamespace(total_tokens=100))


def _record(tmp_path):
    fake = SmartFake()
    llm = DemoLiveLLM(fixture_dir=tmp_path, record=True, client=fake, sleep=lambda s: None, rpm=0)
    for run in DemoRunner.RUNS:
        DemoRunner(run, new_demo_world(mode="live", llm=llm)).run_all()
    assert fake.calls, "recording must have made (fake) model calls"
    return fake


def _replay(tmp_path, run):
    return DemoRunner(run, new_demo_world(mode="live", llm=DemoLiveLLM(fixture_dir=tmp_path))).run_all()


@pytest.mark.parametrize("run", ["legit", "attack"])
def test_live_replay_demo_is_repeatable_without_network(tmp_path, run):
    _record(tmp_path)
    a, b = _replay(tmp_path, run), _replay(tmp_path, run)
    assert a["audit_head"] == b["audit_head"] and a["audit_entries"] == b["audit_entries"]
    sig = lambda r: [(s["title"], (s.get("outcome") or {}).get("status"), s["headline"], s["ai"]["label"]) for s in r["steps"]]
    assert sig(a) == sig(b)
    assert a["mode"] == "live" and a["network_used"] is False and a["audit_ok"] and a["money_lost"] == 0
    assert a["ai"]["replay_misses"] == 0 and "replayed from recorded response" in a["ai"]["label"]
    assert fixture_info(tmp_path)["entries"] > 0


def test_replay_shows_mode_model_and_date_per_step(tmp_path):
    _record(tmp_path)
    r = _replay(tmp_path, "attack")
    forged = next(s for s in r["steps"] if "Forged invoice" in s["title"])
    assert forged["ai"]["mode"] == "live"
    lab = forged["ai"]["label"]
    assert f"qwen3.8-27b" in lab and "Qwen" in lab and "replayed from recorded response" in lab
    assert date.fromisoformat(forged["ai"]["items"][0]["recorded"])
    assert {i["kind"] for i in forged["ai"]["items"]} >= {"extract", "risk"}
    assert next(s for s in r["steps"] if "Receipts" in s["title"])["ai"]["items"] == []


def test_the_ai_risk_scorer_escalated_the_forged_invoice_in_replay(tmp_path):
    _record(tmp_path)
    forged = next(s for s in _replay(tmp_path, "attack")["steps"] if "Forged invoice" in s["title"])
    comp = forged["outcome"]["risk"]["components"]
    assert comp["raised"] and comp["llm"] == 0.9 and comp["final"] >= comp["heuristic"]
    assert any("AI risk scorer" in e for e in forged["outcome"]["risk"]["evidence"])


def test_missing_recordings_fall_back_to_offline_and_say_so(tmp_path):
    r = _replay(tmp_path, "legit")                  # empty fixture directory
    assert r["ai"]["replay_misses"] > 0 and "no recorded response" in r["ai"]["label"]
    assert "offline parser" in r["ai"]["label"] and "deterministic planner" in r["ai"]["label"]
    assert r["audit_ok"] and r["money_lost"] == 0 and r["network_used"] is False
    tuition_step = next(s for s in r["steps"] if "Tuition to the verified" in s["title"])
    assert tuition_step["outcome"]["status"] == "paid"
    assert next(s for s in r["steps"] if "arrives with" in s["title"])["agentic_plan"]["planner"] == "deterministic (fallback)"


def test_replay_mode_cannot_reach_the_network_even_with_a_real_client_missing(tmp_path):
    llm = DemoLiveLLM(fixture_dir=tmp_path)
    ext = llm.extract(tuition())
    assert ext.mode == "deterministic" and ext.fields["amount"] == 30000      # offline parser answered
    assert llm.events[-1]["source"] == "missing"
    assert llm.client.chat.completions.create.__name__ == "_create"


def test_offline_demo_is_unchanged_and_labelled():
    r = play("legit")
    assert r["mode"] == "offline" and r["ai"]["label"] == OFFLINE_LABEL and r["fixture"] is None
    assert all(s["ai"]["label"] == OFFLINE_LABEL for s in r["steps"])
    assert ai_summary("offline", [])["items"] == []


def test_demo_api_toggle_live_replay_and_offline(api_client):
    c = api_client
    off = c.post("/api/demo/start", json={"run": "attack"}).json()
    assert off["mode"] == "offline" and off["llm"] == "offline-deterministic"
    live = c.post("/api/demo/start", json={"run": "attack", "mode": "live"}).json()
    assert live["mode"] == "live" and live["model"] == config.AGENT_MODEL and live["fixture"] is not None
    step = c.post("/api/demo/next").json()
    assert step["ai"]["mode"] == "live" and step["ai"]["label"]
    assert c.get("/api/demo/state").json()["mode"] == "live"
    assert c.get("/api/state").json()["demo"]["mode"] == "live"
    assert c.post("/api/demo/start", json={"run": "attack", "mode": "bogus"}).status_code == 400
    d = c.post("/api/demo/run", json={"run": "legit", "mode": "live"}).json()
    assert d["mode"] == "live" and d["money_lost"] == 0 and d["audit_ok"] and d["network_used"] is False
    again = c.post("/api/demo/run", json={"run": "legit", "mode": "live"}).json()
    assert again["audit_head"] == d["audit_head"]                              # repeatable against the committed fixture


def test_committed_fixture_holds_no_secrets():
    for f in FIXTURE_DIR.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        assert "gsk_" not in text and "org_" not in text and "Bearer" not in text, f.name
        if f.name != "MANIFEST.json":
            assert set(json.loads(text)) <= {"model", "text", "recorded", "content", "tool_calls"}


def test_recording_script_refuses_when_the_budget_would_run_low(monkeypatch, capsys):
    from eval import record_demo_fixture as rec
    monkeypatch.setattr(config, "GROQ_API_KEY", "x")
    monkeypatch.setattr(rec, "tokens_used_today", lambda: 164_025)
    called = []
    monkeypatch.setattr(rec, "DemoLiveLLM", lambda **k: called.append(k))
    assert rec.main([]) == 2 and not called
    assert "Refusing to record" in capsys.readouterr().err
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    assert rec.main([]) == 1


# ============================================================================== 3. LLM risk scorer
DOC = tuition()


def risk_llm(tmp_path, script, **kw):
    return GroqLLM(client=FakeClient([json.dumps(x) if isinstance(x, dict) else x for x in script]), cache_dir=tmp_path,
                   sleep=lambda s: None, rpm=0, extract_mode="llm", llm_risk=True, **kw)


def _risk(llm, text=DOC, fields=None):
    f = fields or {"payee_name": "University X Finance Office", "payee_id": "payee_univ_x", "account_ref": "6228480000001234",
                   "amount": 30000.0}
    return llm.risk(f, text, ["University X Finance Office"], {"payee_univ_x": "6228480000001234"}, 30000.0,
                    {"registry_known": True, "registry_account": "6228480000001234"})


def test_llm_risk_is_live_mode_only(tmp_path):
    det = GroqLLM(client=FakeClient([]), cache_dir=tmp_path, rpm=0, extract_mode="deterministic", llm_risk=True)
    assert det.llm_risk is False and _risk(det).components is None
    assert risk_llm(tmp_path / "l", []).llm_risk is True
    assert GroqLLM(client=FakeClient([]), cache_dir=tmp_path / "d", rpm=0, extract_mode="llm").llm_risk is False   # off by default


def test_llm_can_only_escalate(tmp_path):
    llm = risk_llm(tmp_path, [{"score": 0.8, "evidence": ["new account on a known payee"]}])
    r = _risk(llm)
    assert r.score == 0.8 and r.components["raised"] and r.components["heuristic"] == 0.0
    assert any("AI risk scorer" in e and "new account" in e for e in r.evidence)
    assert llm.risk_stats == {"scored": 1, "raised": 1, "failed": 0, "threshold_crossed": 1}


def test_llm_never_lowers_the_heuristic_score(tmp_path):
    urgent = DOC + "\nURGENT: pay within 24 hours or your visa registration will be cancelled"
    h = heuristic_risk({"payee_name": "University X Finance Office", "payee_id": "payee_univ_x", "account_ref": "6228480000001234",
                        "amount": 30000.0}, urgent, ["University X Finance Office"], {"payee_univ_x": "6228480000001234"},
                       30000.0, {"registry_known": True, "registry_account": "6228480000001234"})
    assert h.score > 0
    r = _risk(risk_llm(tmp_path, [{"score": 0.0, "evidence": []}]), urgent)
    assert r.score == h.score and r.components["raised"] is False and r.components["llm"] == 0.0
    assert r.evidence == h.evidence


def test_llm_scorer_failure_uses_the_heuristic_and_records_it(tmp_path):
    for i, script in enumerate([[Err("boom", 500)] * 8, ["not json"], [{"score": "high"}], [{"score": True}], [{"nope": 1}], ["[1]"]]):
        llm = risk_llm(tmp_path / str(i), script, max_retries=0)
        r = _risk(llm)
        assert r.score == 0.0 and r.components["failed"] and not r.components["raised"], script
        assert "heuristic score was used" in r.evidence[-1]
        assert llm.risk_stats["failed"] == 1


def test_llm_score_is_clamped_and_cached(tmp_path):
    llm = risk_llm(tmp_path, [{"score": 7}])
    assert _risk(llm).score == 1.0
    calls = len(llm.client.calls)
    again = _risk(llm)
    assert again.score == 1.0 and again.components["cached"] is True and len(llm.client.calls) == calls


def test_pipeline_records_components_and_the_llm_can_hold_a_payment(tmp_path):
    llm = risk_llm(tmp_path, [dict(regex_fields(tuition()), translation="", instruction_like_text=False),
                              {"score": 0.7, "evidence": ["odd"]}])
    w = World(Features.full(), llm)
    o = OasisAgent(w).handle(Request(tuition()), SimulatedHumans())
    assert o.risk["components"]["raised"] and o.risk["score"] == 0.7
    assert o.extraction["served_model"] == config.AGENT_MODEL and o.extraction["from_cache"] is False


def _sc(sid):
    return next(s for s in all_scenarios() if s.id == sid)


def test_runner_reports_llm_risk_contribution(tmp_path):
    fake = SmartFake()
    llm = GroqLLM(client=fake, cache_dir=tmp_path, sleep=lambda s: None, rpm=0, extract_mode="llm", llm_risk=True)
    scs = [x for x in all_scenarios() if x.suite == "attack"][:5] + [x for x in all_scenarios() if x.suite == "legit"][:3]
    results = [runner.run_scenario(sc, cfg, llm) for cfg in runner.CONFIGS for sc in scs]
    assert all(r.risk_components for r in results if r.config == "full")
    lr = runner.summarize(results)["llm_risk"]
    assert lr["steps_scored"] >= 8 and lr["lowered_score"] == 0 and lr["llm_call_failed"] == 0
    assert lr["raised_score"] == sum(c["raised"] for r in results for c in r.risk_components if r.config == "full")
    md = runner.to_markdown(runner.summarize(results), {"run_at": "x", "llm": "groq", "agent_model": "m", "fallback_model": "f",
                                                        "ruleset": "r", "repeats": 1, "attacks": 1, "legit": 1, "redteam": 0,
                                                        "extract": "llm"}, None, None)
    assert "LLM risk scorer (live mode, escalate-only)" in md


def test_checkpoints_do_not_mix_with_and_without_the_llm_scorer():
    assert runner.checkpoint_path("groq", "llm") != runner.checkpoint_path("groq", "llm", True)
    assert runner.checkpoint_path("groq", "llm", True).name.endswith("-llm-llmrisk.jsonl")


def test_llm_risk_flag_needs_live_mode():
    with pytest.raises(SystemExit):
        runner.main(["--llm", "offline", "--llm-risk"])


# ============================================================================== 4. serving model per extraction
def test_extraction_records_serving_model_and_cache_flag(tmp_path):
    good = dict(regex_fields(DOC), translation="", instruction_like_text=False)
    llm = GroqLLM(client=FakeClient([json.dumps(good)]), cache_dir=tmp_path, sleep=lambda s: None, rpm=0, extract_mode="llm")
    e1, e2 = llm.extract(DOC), llm.extract(DOC)
    assert (e1.served_model, e1.from_cache) == (config.AGENT_MODEL, False)
    assert (e2.served_model, e2.from_cache) == (config.AGENT_MODEL, True)
    dead = GroqLLM(client=FakeClient([Err("down", 400)] * 4), cache_dir=tmp_path / "d", sleep=lambda s: None, rpm=0,
                   extract_mode="llm", max_retries=0)
    dead.last_model = "stale/model"
    e3 = dead.extract(DOC)
    assert e3.call_failed and e3.served_model is None and e3.from_cache is None


def test_fallback_model_is_reported_as_the_server(tmp_path):
    good = json.dumps(dict(regex_fields(DOC), translation="", instruction_like_text=False))
    llm = GroqLLM(client=FakeClient([Err("model not found", 404), good]), cache_dir=tmp_path, sleep=lambda s: None, rpm=0,
                  extract_mode="llm")
    assert llm.extract(DOC).served_model == config.FALLBACK_MODEL


def test_served_report_counts_per_model_and_labels_pre_fix_runs():
    steps = [{"served_model": "qwen/qwen3.8-27b", "from_cache": False, "call_failed": False},
             {"served_model": "qwen/qwen3.8-27b", "from_cache": True, "call_failed": False},
             {"served_model": "openai/gpt-oss-120b", "from_cache": True, "call_failed": False},
             {"served_model": None, "from_cache": None, "call_failed": True},
             {"call_failed": False, "sources": {}}]                        # an old checkpoint entry: no field at all
    rep = runner.served_report(steps)
    assert rep["by_model"] == {"qwen/qwen3.8-27b": 2, "openai/gpt-oss-120b": 1, runner.CALL_FAILED: 1, runner.NOT_RECORDED: 1}
    assert rep["from_cache"] == 2 and rep["fresh_calls"] == 1
    assert runner.NOT_RECORDED == "model not recorded (pre-fix run)"


def test_live_report_has_no_misleading_served_line():
    live = json.loads((runner.REPORTS / "benchmark_live.json").read_text(encoding="utf-8"))
    assert "served" not in live["meta"]
    md = (runner.REPORTS / "benchmark_live.md").read_text(encoding="utf-8")
    assert "served:" not in md and "Which model served the extractions" in md
    assert runner.NOT_RECORDED in md or "qwen/qwen3.8-27b" in md


def test_pre_fix_checkpoint_results_still_load():
    old = {"scenario": "s", "suite": "attack", "category": "c", "config": "full",
           "extraction": [{"sources": {}, "call_failed": False, "model_followed": False, "injection": False}]}
    assert runner.Result(**old).risk_components == []


# ============================================================================== 6. parent wording follows the real level
@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_parent_wording_depends_on_the_verification_level(lang):
    base = {"student": "Arjun", "amount_inr": 70000, "amount_cny": 6000, "purpose": "family_support", "payee": "Chen Wei",
            "threshold_inr": 50000}
    t = {lvl: i18n.parent_approval({**base, "verification_level": lvl, "verification_limit_cny": 4000}, lang)
         for lvl in ("verified_full", "verified_low", "registry_checked", None)}
    assert len(set(t.values())) == 4                                           # four different statements
    assert "4,000" in t["verified_low"] and "4,000" not in t["verified_full"]
    if lang == "en":
        assert "fully verified" in t["verified_full"]
        for lvl in ("verified_low", "registry_checked", None):
            assert "The recipient is verified through" not in t[lvl] and "fully verified through" not in t[lvl]
        assert "NOT been verified" in t[None] and "low limit" in t["verified_low"]
    for lvl, text in t.items():                                                # the amount survives in every variant
        assert "70,000" in text


def test_parent_view_reads_the_real_level_from_the_passport():
    w = World(Features.full(), OfflineLLM(), autonomy=True)
    fields = {"amount": 8000, "payee_id": "payee_student_self", "payee_name": "Arjun (own CNY account)", "purpose": "family_support"}
    full = parent_view(w, fields, "en")["explanation"]
    assert "fully verified" in full
    rec = w.passport.recipients["payee_student_self"]
    rec.verification.level, rec.verification.limit_cny = Level.VERIFIED_LOW, 500
    low = parent_view(w, fields, "en")["explanation"]
    assert "low limit (CNY 500)" in low and "fully verified through" not in low
    rec.verification.level = Level.UNVERIFIED
    assert "NOT been verified" in parent_view(w, fields, "en")["explanation"]
    assert "NOT been verified" in parent_view(w, {**fields, "payee_id": "unknown", "payee_name": "Stranger"}, "en")["explanation"]


# ============================================================================== 7. SAFE quota is cumulative per calendar year
def _passport():
    return World(Features.full(), OfflineLLM()).passport


def test_corridor_safe_quota_is_cumulative_per_calendar_year():
    p = _passport()
    quota = safe_quota_inr()
    kw = dict(payee_type="university", purpose="tuition", amount_cny=1, amount_inr=10000, year=2026)
    assert not [f for f in corridor.check(p, **kw).findings if f.rule == "safe_quota"]       # fine on its own
    p.safe_used_inr["2026"] = quota - 5000                                                    # 5,000 left this year
    f = [f for f in corridor.check(p, **kw).findings if f.rule == "safe_quota"]
    assert f and f[0].severity == "warn" and f[0].data["used_inr"] == pytest.approx(quota - 5000) and "2026" in f[0].message
    assert not [f for f in corridor.check(p, **{**kw, "year": 2027}).findings if f.rule == "safe_quota"]   # new calendar year


def test_corridor_and_plan_validator_agree_on_the_safe_quota():
    w = World(Features.full(), OfflineLLM())
    quota = safe_quota_inr()
    w.passport.safe_used_inr[str(w.today.year)] = quota - 5000
    step = {"action": "convert", "date": w.today.isoformat(), "send_inr": 10000.0, "route_id": "route_inr_cny_2", "remitter": "student"}
    v = validate_plan(w, [step])
    cor = corridor.check(w.passport, payee_type="university", purpose="tuition", amount_cny=1, amount_inr=10000, year=w.today.year)
    assert any(e["code"] == "safe_quota_exceeded" for e in v.errors)
    assert any(f.rule == "safe_quota" for f in cor.findings)
    w.passport.safe_used_inr[str(w.today.year)] = quota - 50000                               # now there is room: both agree
    assert not any(e["code"] == "safe_quota_exceeded" for e in validate_plan(w, [step]).errors)
    assert not any(f.rule == "safe_quota" for f in corridor.check(
        w.passport, payee_type="university", purpose="tuition", amount_cny=1, amount_inr=10000, year=w.today.year).findings)


def test_pipeline_corridor_check_uses_the_years_conversions_so_far():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    w.passport.safe_used_inr[str(w.today.year)] = safe_quota_inr() - 100        # almost used up
    o = OasisAgent(w).handle(Request(tuition()), SimulatedHumans())
    assert any(f["rule"] == "safe_quota" for f in o.corridor["findings"])
    w2 = World(Features.full(), OfflineLLM(susceptible=True))
    o2 = OasisAgent(w2).handle(Request(tuition()), SimulatedHumans())
    assert not any(f["rule"] == "safe_quota" for f in o2.corridor["findings"])


# ============================================================================== 8. TCS per purpose, data-driven
def test_tcs_rates_come_from_the_data_file():
    rules = corridor.load_rules()
    table = rules["rules"]["tcs_by_purpose"]
    assert table["education"]["rate"] == 0.02 and table["education"]["status"] == "researched"
    assert table["education_loan"]["rate"] == 0.0
    assert table["other"]["status"] == "unconfirmed"                           # a placeholder, never asserted as law
    assert rules["purpose_tcs_category"]["tuition"] == "education"
    p = _passport()
    assert corridor.tcs_rate(p, "tuition", rules)["status"] == "researched"
    for purpose in ("family_support", "living", "rent", "deposit", "something_new"):
        assert corridor.tcs_rate(p, purpose, rules)["status"] == "unconfirmed"
    p.funding_source = "education_loan"
    assert corridor.tcs_rate(p, "tuition", rules) | {} and corridor.tcs_rate(p, "tuition", rules)["rate"] == 0.0
    assert corridor.tcs_rate(p, "living", rules)["status"] == "unconfirmed"     # a loan only makes education nil-rated


def test_tcs_finding_says_unconfirmed_for_other_purposes_only():
    p = _passport()
    p.remitted_inr_fy["parent"] = 950000
    fam = corridor.check(p, payee_type="student", purpose="family_support", amount_cny=10000, amount_inr=118000, remitter="parent")
    f = next(x for x in fam.findings if x.rule == "tcs")
    assert f.data["rate_status"] == "unconfirmed" and "UNCONFIRMED" in f.message and f.data["tcs_inr"] > 0
    edu = corridor.check(p, payee_type="university", purpose="tuition", amount_cny=10000, amount_inr=118000, remitter="parent")
    g = next(x for x in edu.findings if x.rule == "tcs")
    assert g.data["rate_status"] == "researched" and "UNCONFIRMED" not in g.message
    assert g.data["tcs_inr"] == pytest.approx((950000 + 118000 - 1000000) * 0.02)


def test_changing_the_rate_in_the_data_changes_the_tcs(monkeypatch):
    rules = copy.deepcopy(corridor.load_rules())
    rules["rules"]["tcs_by_purpose"]["education"]["rate"] = 0.05
    p = _passport()
    p.remitted_inr_fy["student"] = 1_000_000
    assert corridor.tcs_amount(p, "student", 100000, "tuition", rules) == pytest.approx(5000)
    assert corridor.tcs_amount(p, "student", 100000, "family_support", rules) == pytest.approx(2000)


# ============================================================================== docs stay honest
def test_docs_carry_the_honest_limits_and_no_stale_counts():
    for name in ("README.md", "docs/security-self-assessment.md"):
        text = (config.ROOT / name).read_text(encoding="utf-8")
        assert "## Honest limits" in text and "partly by construction" in text
        assert "Approvals are not authenticated" in text and "Live planning is weak" in text
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert "a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate" in readme
    for name in ("README.md", "docs/execution-evidence.md"):
        assert "142 tests" not in (config.ROOT / name).read_text(encoding="utf-8")
