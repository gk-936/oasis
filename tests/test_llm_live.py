"""Live adapter behaviour with a fake client. No test makes a network call."""
import json
from types import SimpleNamespace

import pytest

from oasis import config
from oasis.agent.llm import LiveLLM, QuotaExhausted, RateLimiter, VisionExtractor, VisionUnavailable, classify_error


FB = "test-fallback-model"


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
    kw.setdefault("fallback_model", FB)
    llm = LiveLLM(client=FakeClient(script), cache_dir=tmp_path, sleep=sleeps.append, rpm=0, **kw)
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
    assert [c["model"] for c in llm.client.calls] == [config.AGENT_MODEL, FB]
    assert llm.fallbacks == 1 and llm.last_model == FB
    # the retired model is skipped from now on
    llm.client.script = ["again"]
    assert llm._chat("s", "u2") == "again"
    assert llm.client.calls[-1]["model"] == FB and len(llm.client.calls) == 3


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
    monkeypatch.setattr(config, "BEDROCK_DAILY_TOKEN_BUDGET", 100)
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


def test_vision_uses_live_agent_model_only_and_never_guesses(tmp_path, monkeypatch):
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
    with pytest.raises(VisionUnavailable):
        VisionExtractor()
    with pytest.raises(VisionUnavailable):
        VisionExtractor(llm).to_text(b"0" * (20 * 1024 * 1024 + 1))
    # runaway value from a blurry image: caught by the line-length rule (500 digits) and by the repeat rule (45 digits)
    for i, bad_out in enumerate(["Payee: X\nPayee ID: 1" + "0" * 500, "Payee: X\nPayee ID: 1" + "0" * 45]):
        junk, _ = make(tmp_path / f"junk{i}", [bad_out])
        with pytest.raises(VisionUnavailable):
            VisionExtractor(junk).to_text(b"img")


def test_redteam_variants_are_filtered_and_fall_back_to_templates(tmp_path):
    from oasis.agent.llm import TEMPLATE_ATTACKS
    ok = json.dumps({"variants": ["Payee: A\nAccount: 6228480000001111\nAmount: CNY 30,000", "just prose"]})
    llm, _ = make(tmp_path / "a", [ok])
    assert llm.attack_variants("lookalike", 3) == ["Payee: A\nAccount: 6228480000001111\nAmount: CNY 30,000"]
    assert "lookalike" in llm.client.calls[0]["messages"][1]["content"]
    llm2, _ = make(tmp_path / "b", [json.dumps({"variants": ["no fields at all"]})])
    assert llm2.attack_variants("lookalike", 1) == TEMPLATE_ATTACKS["lookalike"][:1]
