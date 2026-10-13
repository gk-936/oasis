"""Groq adapter behaviour with a fake client. No test makes a network call."""
import json
from types import SimpleNamespace

import pytest

from oasis import config
from oasis.agent.llm import GroqLLM, QuotaExhausted, RateLimiter, VisionExtractor, VisionUnavailable, classify_error


class Err(Exception):
    def __init__(self, msg, status_code=None, retry_after=None):
        super().__init__(msg)
        self.status_code = status_code
        self.response = SimpleNamespace(headers={"retry-after": str(retry_after)} if retry_after else {})


class FakeClient:
    """script: list of exceptions or text; one entry consumed per call."""

    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0) if self.script else "{}"
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=item))],
                               usage=SimpleNamespace(total_tokens=100))


def make(tmp_path, script, **kw):
    sleeps = []
    llm = GroqLLM(client=FakeClient(script), cache_dir=tmp_path, sleep=sleeps.append, rpm=0, **kw)
    return llm, sleeps


def test_classify_error():
    assert classify_error(Err("x", 404)) == "model_gone"
    assert classify_error(Err("model_decommissioned", 400)) == "model_gone"
    assert classify_error(Err("x", 429)) == "rate_limit"
    assert classify_error(Err("Rate limit reached ... tokens per day (TPD)", 429)) == "daily_limit"
    assert classify_error(Err("x", 401)) == "auth"
    assert classify_error(Err("x", 503)) == "transient"


def test_fallback_when_primary_model_is_gone(tmp_path):
    llm, _ = make(tmp_path, [Err("model not found", 404), "hello"])
    assert llm._chat("s", "u") == "hello"
    assert [c["model"] for c in llm.client.calls] == [config.AGENT_MODEL, config.FALLBACK_MODEL]
    assert llm.fallbacks == 1 and llm.last_model == config.FALLBACK_MODEL
    # the retired model is skipped from now on
    llm.client.script = ["again"]
    assert llm._chat("s", "u2") == "again"
    assert llm.client.calls[-1]["model"] == config.FALLBACK_MODEL and len(llm.client.calls) == 3


def test_backoff_on_429_uses_retry_after_then_succeeds(tmp_path):
    llm, sleeps = make(tmp_path, [Err("rate", 429, retry_after=7), Err("rate", 429), "ok"])
    assert llm._chat("s", "u") == "ok"
    assert sleeps[0] == 7 and len(sleeps) == 2 and sleeps[1] > 0
    assert llm.last_model == config.AGENT_MODEL        # backoff, not fallback


def test_cache_hit_costs_no_call_and_think_tags_are_stripped(tmp_path):
    llm, _ = make(tmp_path, ["<think>plan</think>answer"])
    assert llm._chat("s", "u") == "answer"
    assert llm._chat("s", "u") == "answer"
    assert len(llm.client.calls) == 1 and llm.cache_hits == 1


def test_daily_limit_on_all_models_is_quota_exhausted(tmp_path):
    e = Err("Rate limit reached for model: tokens per day (TPD)", 429)
    llm, _ = make(tmp_path, [e, e])
    with pytest.raises(QuotaExhausted):
        llm._chat("s", "u")


def test_strict_raises_quota_but_default_degrades_to_offline_parser(tmp_path):
    e = Err("requests per day (RPD)", 429)
    text = "Payee: A\nAccount: 123456789\nAmount: CNY 10\nPurpose: rent"
    soft, _ = make(tmp_path / "a", [e, e])
    assert soft.extract(text).fields["amount"] == 10.0
    strict, _ = make(tmp_path / "b", [e, e], strict=True)
    with pytest.raises(QuotaExhausted):
        strict.extract(text)


def test_daily_budget_persisted_on_disk(tmp_path, monkeypatch):
    llm, _ = make(tmp_path, ["a"])
    llm._chat("s", "u")
    assert llm.usage.day()["tokens"] == 100 and llm.usage.day()["requests"] == 1
    monkeypatch.setattr(config, "GROQ_DAILY_REQUEST_BUDGET", 1)
    llm2, _ = make(tmp_path, ["b"])           # new process, same cache dir: budget already used
    with pytest.raises(QuotaExhausted):
        llm2._chat("s", "different")


def test_auth_failure_fails_fast(tmp_path):
    llm, _ = make(tmp_path, [Err("bad key", 401)])
    with pytest.raises(RuntimeError):
        llm._chat("s", "u")
    with pytest.raises(RuntimeError):
        llm._chat("s", "u2")
    assert len(llm.client.calls) == 1


def test_rate_limiter_spaces_calls():
    t = [0.0]
    slept = []
    rl = RateLimiter(30, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    rl.wait(); rl.wait(); rl.wait()
    assert slept == [2.0, 2.0]


def test_llm_rewrite_must_keep_numbers(tmp_path):
    ctx = {"student": "Arjun", "amount_inr": 71000, "amount_cny": 6000, "purpose": "family_support", "payee": "P"}
    good, _ = make(tmp_path / "g", ["Arjun asks to send 71,000 rupees (6,000 yuan)."])
    bad, _ = make(tmp_path / "b", ["Arjun asks to send a lot of money."])
    from oasis.agent.llm import explain_template
    assert "71,000" in good.explain("parent_approval", ctx, "en")
    assert bad.explain("parent_approval", ctx, "en") == explain_template("parent_approval", ctx, "en")


def test_vision_uses_groq_agent_model_only_and_never_guesses(tmp_path, monkeypatch):
    llm, _ = make(tmp_path, ["Payee: X\nAmount: CNY 5"])
    assert VisionExtractor(llm).to_text(b"\x89PNGfake") .startswith("Payee: X")
    call = llm.client.calls[0]
    assert call["model"] == config.AGENT_MODEL
    assert call["messages"][1]["content"][0]["type"] == "image_url"
    # primary fails -> the fallback model has no vision -> clear error, no fallback call
    bad, _ = make(tmp_path / "x", [Err("model not found", 404)])
    with pytest.raises(VisionUnavailable):
        VisionExtractor(bad).to_text(b"img")
    assert len(bad.client.calls) == 1
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    with pytest.raises(VisionUnavailable):
        VisionExtractor()
    with pytest.raises(VisionUnavailable):
        VisionExtractor(llm).to_text(b"0" * (20 * 1024 * 1024 + 1))


def test_redteam_variants_are_filtered_and_fall_back_to_templates(tmp_path):
    from oasis.agent.llm import TEMPLATE_ATTACKS
    ok = json.dumps({"variants": ["Payee: A\nAccount: 6228480000001111\nAmount: CNY 30,000", "just prose"]})
    llm, _ = make(tmp_path / "a", [ok])
    assert llm.attack_variants("lookalike", 3) == ["Payee: A\nAccount: 6228480000001111\nAmount: CNY 30,000"]
    assert "lookalike" in llm.client.calls[0]["messages"][1]["content"]
    llm2, _ = make(tmp_path / "b", [json.dumps({"variants": ["no fields at all"]})])
    assert llm2.attack_variants("lookalike", 1) == TEMPLATE_ATTACKS["lookalike"][:1]


# ------------------------------------------------------------------------------------------- multiple API keys
from oasis.agent.llm import key_fingerprint  # noqa: E402

KEYS = ["gsk_AAAA1111secretkeyone", "plainsecret-two-2222", "gsk_CCCC3333secretkeythree"]
DAILY = Err("Rate limit reached for model: tokens per day (TPD) key gsk_AAAA1111secretkeyone", 429)


def multi(tmp_path, scripts, keys=KEYS, **kw):
    clients = [FakeClient(s) for s in scripts]
    sleeps = []
    llm = GroqLLM(client=clients, api_keys=keys[:len(clients)], cache_dir=tmp_path, sleep=sleeps.append, rpm=0, **kw)
    return llm, clients, sleeps


def test_parse_keys():
    assert config.parse_keys("a, b ,, c ,") == ["a", "b", "c"]
    assert config.parse_keys("  solo  ") == ["solo"]
    assert config.parse_keys("a,a,b") == ["a", "b"]
    assert config.parse_keys("") == [] and config.parse_keys(" , ") == []


def test_config_exposes_first_key_and_list(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "k1, k2")
    assert config.groq_keys() == ["k1", "k2"]          # an overridden single attribute is still parsed


def test_daily_limit_fails_over_to_next_key_same_model(tmp_path):
    llm, (c0, c1, c2), _ = multi(tmp_path, [[DAILY], ["from-key-1"], []])
    assert llm._chat("s", "u") == "from-key-1"
    assert [c["model"] for c in c0.calls] == [config.AGENT_MODEL] and [c["model"] for c in c1.calls] == [config.AGENT_MODEL]
    assert llm.last_model == config.AGENT_MODEL and llm.fallbacks == 0 and llm.key_rotations == 1
    assert llm.last_key == key_fingerprint(KEYS[1])
    # sticky: the next call goes straight to key 1, key 0 is not retried for that model
    c1.script = ["again"]
    assert llm._chat("s", "u2") == "again" and len(c0.calls) == 1 and len(c1.calls) == 2


def test_per_minute_429_backs_off_on_same_key_without_rotating(tmp_path):
    llm, (c0, c1), sleeps = multi(tmp_path, [[Err("slow down", 429, retry_after=3), "ok"], ["unused"]])
    assert llm._chat("s", "u") == "ok"
    assert len(c0.calls) == 2 and len(c1.calls) == 0 and sleeps == [3.0] and llm.key_rotations == 0


def test_model_fallback_still_applies_per_key(tmp_path):
    # key 0: qwen retired -> gpt-oss on the SAME key (no rotation)
    llm, (c0, c1), _ = multi(tmp_path, [[Err("model not found", 404), "fb"], []])
    assert llm._chat("s", "u") == "fb"
    assert [c["model"] for c in c0.calls] == [config.AGENT_MODEL, config.FALLBACK_MODEL] and not c1.calls


def test_daily_limit_on_primary_model_only_uses_fallback_model_on_other_keys_too(tmp_path):
    # both keys are out of qwen for today; gpt-oss still works (on the key now in use)
    llm, (c0, c1), _ = multi(tmp_path, [[DAILY], [DAILY, "gpt-oss-answer"]])
    assert llm._chat("s", "u") == "gpt-oss-answer"
    assert [c["model"] for c in c0.calls] == [config.AGENT_MODEL]
    assert [c["model"] for c in c1.calls] == [config.AGENT_MODEL, config.FALLBACK_MODEL]
    assert llm.last_model == config.FALLBACK_MODEL and llm.fallbacks == 1


def test_per_key_usage_accounting_and_backward_compatible_totals(tmp_path):
    llm, (c0, c1), _ = multi(tmp_path, [["a", DAILY], ["b", "c"]])
    llm._chat("s", "1")                       # key 0
    llm._chat("s", "2")                       # key 0 daily-limited on qwen AND... -> key 1
    llm._chat("s", "3")                       # key 1
    day = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))[llm.usage.today()]
    fp0, fp1 = key_fingerprint(KEYS[0]), key_fingerprint(KEYS[1])
    assert day["tokens"] == 300 and day["requests"] == 3            # day totals keep the old format
    assert day["keys"] == {fp0: {"tokens": 100, "requests": 1}, fp1: {"tokens": 200, "requests": 2}}
    assert all(KEYS[i] not in json.dumps(day) for i in range(2))     # fingerprints only
    # a pre-existing single-total ledger entry is still read
    (tmp_path / "usage.json").write_text(json.dumps({llm.usage.today(): {"tokens": 5, "requests": 1}}), encoding="utf-8")
    old = GroqLLM(client=FakeClient(["x"]), cache_dir=tmp_path, rpm=0)
    assert old.usage.day()["tokens"] == 5


def test_local_budget_is_per_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GROQ_DAILY_REQUEST_BUDGET", 1)
    llm, (c0, c1), _ = multi(tmp_path, [["a"], ["b"]])
    assert llm._chat("s", "1") == "a"
    assert llm._chat("s", "2") == "b"         # key 0 used its 1 request -> key 1, with no error from the server
    assert len(c0.calls) == 1 and len(c1.calls) == 1 and llm.key_rotations == 1
    with pytest.raises(QuotaExhausted):
        llm._chat("s", "3")                   # every key at its budget


def test_all_keys_daily_limited_raises_quota_exhausted(tmp_path):
    llm, (c0, c1), _ = multi(tmp_path, [[DAILY, DAILY], [DAILY, DAILY]])
    with pytest.raises(QuotaExhausted) as ei:
        llm._chat("s", "u")
    assert [c["model"] for c in c0.calls] == [config.AGENT_MODEL, config.FALLBACK_MODEL]
    assert [c["model"] for c in c1.calls] == [config.AGENT_MODEL, config.FALLBACK_MODEL]
    with pytest.raises(QuotaExhausted):
        llm._chat("s", "again")               # remembered: no more requests are made
    assert len(c0.calls) == 2 and len(c1.calls) == 2


def test_strict_mode_raises_only_when_all_keys_exhausted(tmp_path):
    text = "Payee: A\nAccount: 123456789\nAmount: CNY 10\nPurpose: rent"
    llm, _, _ = multi(tmp_path / "a", [[DAILY, '{"payee_name": "A"}'], ["spare"]], strict=True)
    assert llm.extract(text).fields["amount"] == 10.0          # failed over; no exception
    llm2, _, _ = multi(tmp_path / "b", [[DAILY, DAILY], [DAILY, DAILY]], strict=True)
    with pytest.raises(QuotaExhausted):
        llm2.extract(text)


def test_auth_failure_on_one_key_rotates_but_all_bad_fails_fast(tmp_path):
    llm, (c0, c1), _ = multi(tmp_path, [[Err("bad", 401)], ["fine"]])
    assert llm._chat("s", "u") == "fine"
    bad, (b0, b1), _ = multi(tmp_path / "x", [[Err("bad", 401)], [Err("bad", 401)]])
    with pytest.raises(RuntimeError):
        bad._chat("s", "u")
    with pytest.raises(RuntimeError):
        bad._chat("s", "u2")
    assert len(b0.calls) == 1 and len(b1.calls) == 1


def test_no_key_value_ever_appears_in_errors_or_exceptions(tmp_path):
    msgs = [f"Invalid API key {k} (Bearer {k})" for k in KEYS]
    e0 = [Err(msgs[0], 500), Err(msgs[0], 500)]
    llm, _, _ = multi(tmp_path, [e0 + e0 + e0 + e0 + e0 + e0, [Err(msgs[1], 400), Err(msgs[2], 400)], []], max_retries=0)
    with pytest.raises(RuntimeError) as ei:
        llm._chat("s", "u")
    blob = str(ei.value) + json.dumps(llm.errors)
    for k in KEYS:
        assert k not in blob
    # every configured key is redacted, whatever its format
    for k in KEYS:
        assert k not in llm._scrub(f"x {k} y")
    # the auth path too
    bad, _, _ = multi(tmp_path / "y", [[Err(f"401 {KEYS[0]}", 401)], [Err(f"401 {KEYS[1]}", 401)], [Err(f"401 {KEYS[2]}", 401)]])
    with pytest.raises(RuntimeError) as ei2:
        bad._chat("s", "u")
    assert not any(k in str(ei2.value) for k in KEYS) and not any(k in json.dumps(bad.errors) for k in KEYS)


def test_chat_tools_fails_over_on_daily_limit(tmp_path):
    ok = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=None))],
                         usage=SimpleNamespace(total_tokens=42))
    llm, (c0, c1), _ = multi(tmp_path, [[DAILY], []])
    c1.chat.completions.create = lambda **kw: (c1.calls.append(kw), ok)[1]
    out = llm.chat_tools([{"role": "user", "content": "plan"}], [{"type": "function", "function": {"name": "t"}}])
    assert out["content"] == "done" and out["tokens"] == 42 and out["model"] == config.AGENT_MODEL
    assert llm.usage.key_day(key_fingerprint(KEYS[1])) == {"tokens": 42, "requests": 1}
    assert llm.usage.key_day(key_fingerprint(KEYS[0])) == {"tokens": 0, "requests": 0}
