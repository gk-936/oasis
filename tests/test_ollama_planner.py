"""Local Ollama adapter + planner format v4 (constrained JSON) + the local evaluation runner. Hermetic: a fake Ollama HTTP
server on 127.0.0.1 (the conftest guard allows loopback only); no real model, no real Ollama, no internet."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from eval import planning_local
from oasis import config
from oasis.agent.llm import make_llm
from oasis.agent.ollama_llm import (OllamaError, OllamaLLM, OllamaModelMissing, OllamaRefused, OllamaUnavailable,
                                    OllamaUnsupported, is_cloud_model)
from oasis.agent.planner import AgenticPlanner, DeterministicPlanner, make_planner
from oasis.agent.planner_v4 import SIZED_BY_HARNESS, SYSTEM_V4, ConstrainedPlanner, build_schema, facts, route_table, user_message
from oasis.planning.scenarios import ALL_SCENARIOS, build_scenario_world
from oasis.planning.validator import validate_plan


class FakeOllama:
    """Scripted /api/chat server. `script` is a list of callables body -> (status, payload); the last one repeats."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                fn = outer.script[min(len(outer.requests) - 1, len(outer.script) - 1)]
                status, payload = fn(body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                data = json.dumps({"models": [{"name": "fake:1b"}]} if self.path == "/api/tags" else {"models": [
                    {"name": "fake:1b", "size": 2 * 2**30, "size_vram": 2**30, "context_length": 8192}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def serve():
    made = []

    def make(*script):
        f = FakeOllama(script)
        made.append(f)
        return f
    yield make
    for f in made:
        f.close()


def ok(message, **kw):
    base = {"model": "fake:1b", "message": message, "done": True, "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 20,
            "total_duration": 2_000_000_000, "load_duration": 500_000_000, "eval_duration": 1_000_000_000}
    return lambda body: (200, {**base, **kw})


def llm_for(f, tmp_path, **kw):
    kw.setdefault("sleep", lambda s: None)
    return OllamaLLM(model="fake:1b", url=f.url, cache_dir=tmp_path / "c", temperature=0.3, seed=7, **kw)


# ------------------------------------------------------------------------------------------------------- adapter
def test_chat_tools_round_trip_options_and_accounting(serve, tmp_path):
    f = serve(ok({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "facts_sheet", "arguments": {}}}]}))
    llm = llm_for(f, tmp_path)
    tools = [{"type": "function", "function": {"name": "facts_sheet", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_passport", "arguments": json.dumps({"a": 1})}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "{\"x\":1}"}]
    r = llm.chat_tools(msgs, tools)
    assert r["tool_calls"][0]["name"] == "facts_sheet" and r["tool_calls"][0]["arguments"] == {} and r["tool_calls"][0]["id"]
    assert r["tokens"] == 120 and r["cached"] is False and r["model"] == "fake:1b"
    path, body = f.requests[0]
    assert path == "/api/chat" and body["stream"] is False and body["tools"] == tools
    assert body["options"] == {"temperature": 0.3, "num_ctx": 8192, "num_predict": 900, "seed": 7}
    assert llm_for(f, tmp_path, use_mmap=False).use_mmap is False
    assert body["keep_alive"] == config.OLLAMA_KEEP_ALIVE and body["think"] is False
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"a": 1}          # arguments are objects natively
    assert body["messages"][3] == {"role": "tool", "tool_name": "read_passport", "content": "{\"x\":1}"}
    st = llm.call_log[0]
    assert (st["prompt_tokens"], st["output_tokens"], st["total_s"], st["load_s"], st["eval_s"]) == (100, 20, 2.0, 0.5, 1.0) and not st["truncated"]


def test_cache_hit_costs_nothing_and_key_depends_on_seed_and_salt(serve, tmp_path):
    f = serve(ok({"role": "assistant", "content": "{\"steps\": []}"}))
    llm = llm_for(f, tmp_path)
    a = llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    b = llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    assert not a["cached"] and b["cached"] and b["tokens"] == 0 and len(f.requests) == 1 and llm.cache_hits == 1
    llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"}, seed=8)
    llm2 = llm_for(f, tmp_path, salt="other")
    llm2.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    assert len(f.requests) == 3
    nocache = llm_for(f, tmp_path, use_cache=False)
    nocache.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    nocache.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    assert len(f.requests) == 5


def test_generate_json_sends_schema_and_parses_or_reports_truncation(serve, tmp_path):
    schema = {"type": "object", "properties": {"steps": {"type": "array"}}}
    f = serve(ok({"role": "assistant", "content": "{\"steps\": [1]}"}), ok({"role": "assistant", "content": "{\"steps\": [1,"}, done_reason="length"))
    llm = llm_for(f, tmp_path, use_cache=False)
    r1 = llm.generate_json([{"role": "user", "content": "q"}], schema)
    r2 = llm.generate_json([{"role": "user", "content": "q"}], schema)
    assert f.requests[0][1]["format"] == schema and r1["json"] == {"steps": [1]}
    assert r2["json"] is None and r2["stats"]["done_reason"] == "length"


def test_prompt_reaching_num_ctx_is_flagged(serve, tmp_path):
    f = serve(ok({"role": "assistant", "content": "{}"}, prompt_eval_count=8192))
    llm = llm_for(f, tmp_path, use_cache=False)
    llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    assert llm.call_log[0]["truncated"] is True


def test_not_running_is_a_clean_error(tmp_path):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                       # nothing listens on this port now
    llm = OllamaLLM(model="fake:1b", url=f"http://127.0.0.1:{port}", cache_dir=tmp_path / "c", sleep=lambda s: None)
    with pytest.raises(OllamaUnavailable, match="not running"):
        llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    with pytest.raises(OllamaUnavailable):
        llm.require_installed()
    assert llm.errors[0]["kind"] == "unavailable"


def test_model_not_installed_and_no_tool_support_errors(serve, tmp_path):
    f = serve(lambda b: (404, {"error": "model 'fake:1b' not found"}))
    with pytest.raises(OllamaModelMissing, match="ollama pull fake:1b"):
        llm_for(f, tmp_path).generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    g = serve(lambda b: (400, {"error": "registry.ollama.ai/library/x does not support tools"}))
    with pytest.raises(OllamaUnsupported, match="does not support tools"):
        llm_for(g, tmp_path).chat_tools([{"role": "user", "content": "q"}], [])
    h = serve(ok({"role": "assistant", "content": "{}"}))
    llm = llm_for(h, tmp_path)
    llm.require_installed("fake:1b")
    with pytest.raises(OllamaModelMissing, match="not installed"):
        llm.require_installed("other:7b")


def test_transient_5xx_is_retried_then_succeeds_and_gives_up(serve, tmp_path):
    f = serve(lambda b: (503, {"error": "busy"}), ok({"role": "assistant", "content": "{}"}))
    llm = llm_for(f, tmp_path, use_cache=False)
    assert llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})["json"] == {}
    assert len(f.requests) == 2 and llm.errors[0]["kind"] == "transient"
    g = serve(lambda b: (500, {"error": "boom"}))
    with pytest.raises(OllamaError):
        llm_for(g, tmp_path, use_cache=False, max_retries=1).generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    assert len(g.requests) == 2


def test_timeout_is_an_error_not_a_hang(tmp_path):
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)                                                   # accepts the connection but never answers
    try:
        llm = OllamaLLM(model="fake:1b", url=f"http://127.0.0.1:{srv.getsockname()[1]}", cache_dir=tmp_path / "c", timeout=0.3,
                        max_retries=0, sleep=lambda s: None)
        with pytest.raises(OllamaError, match="did not answer"):
            llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    finally:
        srv.close()


def test_privacy_guards():
    with pytest.raises(OllamaRefused, match="loopback"):
        OllamaLLM(model="x:1b", url="http://192.168.1.5:11434")
    with pytest.raises(OllamaRefused, match="loopback"):
        OllamaLLM(model="x:1b", url="https://example.com")
    for cloud in ("gpt-oss:20b-cloud", "glm-5:cloud", "minimax-m2.7:cloud", "gemini-3-flash-preview"):
        assert is_cloud_model(cloud)
        with pytest.raises(OllamaRefused, match="cloud"):
            OllamaLLM(model=cloud)
    for local in ("qwen3.5:4b", "qwen2.5:3b", "phi4-mini", "phi4-mini:latest"):
        assert not is_cloud_model(local)


def test_error_text_is_redacted(serve, tmp_path):
    f = serve(lambda b: (400, {"error": "bad Bearer abc123SECRET and gsk_deadbeef"}))
    llm = llm_for(f, tmp_path)
    with pytest.raises(OllamaError) as e:
        llm.generate_json([{"role": "user", "content": "q"}], {"type": "object"})
    assert "abc123SECRET" not in str(e.value) and "gsk_deadbeef" not in str(e.value)
    assert llm.errors and all("abc123SECRET" not in x["message"] and "gsk_deadbeef" not in x["message"] for x in llm.errors)


def test_ps_reports_gpu_share_and_make_llm_selects_ollama(serve, tmp_path):
    f = serve(ok({"role": "assistant", "content": "{}"}))
    llm = llm_for(f, tmp_path)
    assert llm.ps() == [{"name": "fake:1b", "size_mb": 2048, "vram_mb": 1024, "gpu_pct": 50, "context": 8192}]
    assert isinstance(make_llm("ollama", url=f.url, cache_dir=tmp_path / "m"), OllamaLLM)
    llm.unload()
    assert f.requests[-1][1]["keep_alive"] == 0
    assert make_llm("offline").name != "ollama"


# --------------------------------------------------------------------------------------------------- v4 planner
def good_plan(sid):
    return DeterministicPlanner().plan(build_scenario_world(sid)).steps


def answer(steps, calc="work", rationale="why"):
    return {"role": "assistant", "content": json.dumps({"calculation": calc, "steps": steps, "rationale": rationale})}


@pytest.mark.parametrize("sid", list(ALL_SCENARIOS))
def test_v4_schema_and_prompt_are_deterministic_and_honest(sid):
    w = build_scenario_world(sid)
    schema = build_schema(w)
    assert schema["required"] == ["calculation", "steps", "rationale"] and list(schema["properties"]) == ["calculation", "steps", "rationale"]
    kinds = schema["properties"]["steps"]["items"]["anyOf"]
    assert {k["properties"]["action"]["enum"][0] for k in kinds} == {"convert", "pay"}
    json.dumps(schema)
    msg = user_message(w, "goal")
    for banned in SIZED_BY_HARNESS:                    # the harness must not hand the model an INR amount it sized
        assert banned not in msg and banned not in facts(w)
    assert "obligations" in facts(w) and "student_spendable_inr" in facts(w) and "cny_shortfall" in facts(w)
    table = route_table(w)
    assert [r["id"] for r in table][0] == "route_bank_swift" and all(r["cny_per_inr"] > 0 and "send_inr" not in r for r in table)
    assert "size_conversion" not in SYSTEM_V4 and "size_conversion" not in msg


def test_v4_valid_first_proposal_is_taken_verbatim(serve, tmp_path):
    steps = good_plan("tight_runway")
    f = serve(ok(answer(steps)))
    llm = llm_for(f, tmp_path, use_cache=False)
    w = build_scenario_world("tight_runway")
    res = AgenticPlanner(llm, fmt="v4").plan(w, "g")
    assert res.valid and not res.fell_back and res.planner == "ollama-constrained" and res.steps == steps and res.iterations == 1
    assert res.tokens == 120 and res.model_calls == 1
    body = f.requests[0][1]
    assert body["format"]["required"] == ["calculation", "steps", "rationale"] and "tools" not in body
    assert body["messages"][0]["content"] == SYSTEM_V4 and "FACTS:" in body["messages"][1]["content"] and "ROUTES:" in body["messages"][1]["content"]


def test_v4_revision_gets_errors_and_fix_hints_and_the_harness_applies_nothing(serve, tmp_path):
    steps = copy.deepcopy(good_plan("tight_runway"))
    bad = copy.deepcopy(steps)
    pay = next(s for s in bad if s["action"] == "pay")
    pay["amount_cny"] = pay["amount_cny"] - 7           # an arithmetic/copy error the validator reports as amount_mismatch
    f = serve(ok(answer(bad)), ok(answer(steps)))
    llm = llm_for(f, tmp_path, use_cache=False)
    res = ConstrainedPlanner(llm, seed=3).plan(build_scenario_world("tight_runway"))
    assert res.valid and not res.fell_back and res.iterations == 2 and res.steps == steps
    second = f.requests[1][1]["messages"]
    assert second[-2]["role"] == "assistant" and json.loads(second[-2]["content"])["steps"] == bad       # the model's own words are replayed unchanged
    fb = second[-1]["content"]
    assert "amount_mismatch" in fb and '"fix"' in fb and "set" in fb
    assert [r[1]["options"]["seed"] for r in f.requests] == [3, 4]
    proposals = [t for t in res.trace if t["type"] == "proposal"]
    assert proposals[0]["steps"] == bad and not proposals[0]["validation"]["valid"]     # scored exactly as sent, not repaired


def test_v4_stops_after_three_revisions_and_falls_back_with_the_reason(serve, tmp_path):
    bad = copy.deepcopy(good_plan("tight_runway"))
    bad = [s for s in bad if s["action"] != "pay"]
    f = serve(ok(answer(bad)))
    llm = llm_for(f, tmp_path, use_cache=False)
    res = ConstrainedPlanner(llm).plan(build_scenario_world("tight_runway"))
    assert len(f.requests) == 4 and res.fell_back and res.valid and res.planner == "deterministic (fallback)"
    assert res.fallback_reason.startswith("no valid plan after 4 proposal")


def test_v4_truncated_json_is_not_scored_as_a_proposal(serve, tmp_path):
    steps = good_plan("tight_runway")
    f = serve(ok({"role": "assistant", "content": "{\"calculation\": \"x"}, done_reason="length"), ok(answer(steps)))
    res = ConstrainedPlanner(llm_for(f, tmp_path, use_cache=False)).plan(build_scenario_world("tight_runway"))
    assert res.valid and not res.fell_back and res.iterations == 1 and res.model_calls == 2
    assert "cut off" in f.requests[1][1]["messages"][-1]["content"]


def test_v4_ollama_down_falls_back_without_crashing(tmp_path):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    llm = OllamaLLM(model="fake:1b", url=f"http://127.0.0.1:{port}", cache_dir=tmp_path / "c", sleep=lambda s: None)
    res = AgenticPlanner(llm, fmt="v4").plan(build_scenario_world("tight_runway"))
    assert res.fell_back and res.valid and res.fallback_reason.startswith("OllamaUnavailable")


def test_v4_sample_scores_one_independent_first_proposal(serve, tmp_path):
    steps = good_plan("tight_runway")
    bad = [s for s in steps if s["action"] != "pay"]
    f = serve(ok(answer(bad)), ok(answer(steps)))
    p = ConstrainedPlanner(llm_for(f, tmp_path, use_cache=False))
    a = p.sample(build_scenario_world("tight_runway"), "", 1001)
    b = p.sample(build_scenario_world("tight_runway"), "", 2001)
    assert not a["valid"] and a["errors"].get("obligation_unfunded") and b["valid"] and b["errors"] == {}
    assert [r[1]["options"]["seed"] for r in f.requests] == [1001, 2001] and all(len(r[1]["messages"]) == 2 for r in f.requests)   # no revision context


# -------------------------------------------------------------------------------------- v2 over the adapter
def test_tool_calling_planner_runs_over_the_ollama_adapter(serve, tmp_path):
    w = build_scenario_world("tight_runway")
    steps = good_plan("tight_runway")
    f = serve(ok({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "list_obligations", "arguments": {}}}]}),
              ok({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "propose_plan", "arguments": {"steps": steps, "rationale": "r"}}}]}))
    llm = llm_for(f, tmp_path, use_cache=False)
    assert isinstance(make_planner(llm), AgenticPlanner)
    res = make_planner(llm).plan(w, "g")
    assert res.valid and not res.fell_back and res.planner == "ollama-tools" and res.model_calls == 2
    assert f.requests[1][1]["messages"][-1]["role"] == "tool" and f.requests[1][1]["messages"][-1]["tool_name"] == "list_obligations"


def test_tool_calling_on_a_model_without_tools_is_reported_not_hidden(serve, tmp_path):
    f = serve(lambda b: (400, {"error": "registry.ollama.ai/library/x does not support tools"}))
    res = AgenticPlanner(llm_for(f, tmp_path, use_cache=False), fmt="v2").plan(build_scenario_world("tight_runway"))
    assert res.fell_back and "OllamaUnsupported" in res.fallback_reason
    assert planning_local.fallback_class(res.fallback_reason) == "no tool support"


# ------------------------------------------------------------------------------------------- evaluation runner
def test_runner_classification_ram_and_report_render(tmp_path):
    fc = planning_local.fallback_class
    assert fc("token cap reached (23000)") == "token cap" and fc("no valid plan after 4 proposal(s)") == "no valid plan after proposals"
    assert fc("OllamaUnavailable: x") == "Ollama error" and planning_local.is_infrastructure_failure({"fallback_reason": "OllamaError: timeout"})
    assert not planning_local.is_infrastructure_failure({"fallback_reason": "no valid plan after 4 proposal(s)"})
    assert planning_local.free_ram_mb() > 100
    row = {"scenario": "shortfall", "model_requested": "m:1b", "format": "v4", "rep": 0, "model_valid_without_fallback": True, "pass1": False,
           "valid": True, "fell_back": False, "fallback_reason": None, "iterations_to_valid": 2, "error_counts": {"amount_mismatch": 1, "late_payment": 1},
           "tokens": 3000, "seconds": 40.0, "model_calls": 2, "gv_valid": True, "gv_samples": 2, "gv_seconds": 5.0, "ps": [{"gpu_pct": 100}]}
    row2 = {**row, "scenario": "heldout_year_boundary", "model_valid_without_fallback": False, "valid": True, "fell_back": True,
            "fallback_reason": "no valid plan after 4 proposal(s)", "iterations_to_valid": None, "gv_valid": False, "gv_samples": 3}
    data = {"rows": [row, row2], "no_tools": ["x:1b"]}
    path = tmp_path / "rows.json"
    planning_local.save(data, path)
    assert planning_local.load(path)["rows"][0]["scenario"] == "shortfall"
    md = planning_local.render(data)
    assert "v4, exploratory" in md and "Generate-and-verify" in md and "no tool support" in md and "1/2 (50%)" in md
    c = planning_local.cell_stats([row, row2])
    assert c["model_only_valid"] == 1 and c["heldout"] == [0, 1] and c["original"] == [1, 1] and c["gv"] == [1, 2] and c["arithmetic_errors"] == 2
    assert planning_local.render({"rows": [], "no_tools": []}).strip().endswith("_No rows yet._")
