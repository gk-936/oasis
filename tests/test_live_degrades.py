"""Hardening of the live paths: when the model is unreachable or the token budget is gone, every AI feature falls back to its
deterministic result and nothing raises, so a hosted demo that runs out of tokens (or loses the network) keeps working offline."""
from types import SimpleNamespace

import pytest

from eval.ai_contribution import GENUINE
from oasis import config
from oasis.agent import chat_llm, nlu, recovery
from oasis.agent.llm import LiveLLM, QuotaExhausted, OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.world import Features, World


class Dead:
    """A client whose every call fails like a spent budget."""
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        raise AssertionError("no request may reach the model once the budget is spent")


@pytest.fixture
def spent(tmp_path, monkeypatch):
    llm = LiveLLM(client=Dead(), cache_dir=tmp_path / "c", rpm=0, fallback_model=None, extract_mode="llm", llm_risk=True)

    def boom():
        raise QuotaExhausted("daily token budget used")
    monkeypatch.setattr(llm, "_check_budget", boom)
    return llm


def test_a_genuine_invoice_still_ends_held_for_signature_when_the_budget_is_spent(spent):
    w = World(Features.full(), spent)
    out = OasisAgent(w).handle(Request(GENUINE[0], source="invoice", remitter="student"))
    assert out.status == "held" and out.decision["rule"] == "R11_approval_required" and w.ledger.money_lost() == 0
    assert spent.risk_stats["failed"] == 1                           # recorded, not hidden
    w2 = World(Features.full(), OfflineLLM())
    assert OasisAgent(w2).handle(Request(GENUINE[0], source="invoice", remitter="student")).status == out.status


def test_chat_labeller_returns_nothing_instead_of_raising_when_the_budget_is_spent(spent):
    assert chat_llm.propose(spent, "what are you capable of, exactly?") is None


def test_explanations_and_recovery_fall_back_to_the_template(spent):
    ctx = {"text": "x", "facts": {}, "options": []}
    assert spent.explain("flightpath", ctx, "en")                    # the template, not an exception
    assert spent.draft_recovery({"recipient": "University X Finance Office"}) is None
    assert spent.explain_stats["failed"] == 1


def test_bedrock_client_uses_short_per_call_limits(monkeypatch):
    seen = {}
    import boto3
    monkeypatch.setattr(boto3, "client", lambda svc, **kw: seen.update(kw) or object())
    from oasis.agent.bedrock_llm import BedrockClient
    BedrockClient()
    c = seen["config"]
    assert c.read_timeout == config.BEDROCK_TIMEOUT <= 60 and c.connect_timeout == config.BEDROCK_CONNECT_TIMEOUT <= 10


def test_a_total_budget_stops_the_model_for_good_across_days_and_restarts(tmp_path, monkeypatch):
    import json
    calls = []

    class Counting:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kw):
            calls.append(1)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))], usage=SimpleNamespace(total_tokens=400))

    monkeypatch.setattr(config, "BEDROCK_TOTAL_TOKEN_BUDGET", 1000)
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "usage.json").write_text(json.dumps({"2026-10-01": {"tokens": 300, "requests": 1}, "2026-10-02": {"tokens": 300, "requests": 1}}))
    mk = lambda: LiveLLM(client=Counting(), cache_dir=cache, rpm=0, fallback_model=None, strict=True)        # noqa: E731
    llm = mk()
    assert llm._chat("s", "first") == "OK"                          # 600 counted over earlier days + 400 = 1000
    with pytest.raises(QuotaExhausted, match="total token budget"):
        llm._chat("s", "second")                                    # a different message: not cached, budget spent
    assert llm._chat("s", "first") == "OK"                          # a cached answer costs nothing and still works
    with pytest.raises(QuotaExhausted):
        mk()._chat("s", "third")                                    # a restart reads the same file: still spent
    assert len(calls) == 1


def test_no_total_budget_means_only_the_daily_limit_applies(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(config, "BEDROCK_TOTAL_TOKEN_BUDGET", 0)
    (tmp_path / "usage.json").write_text(json.dumps({"2020-01-01": {"tokens": 5_000_000, "requests": 9}}))     # heavy use on an earlier day
    ok = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))], usage=SimpleNamespace(total_tokens=10)))))
    llm = LiveLLM(client=ok, cache_dir=tmp_path, rpm=0, fallback_model=None, strict=True)
    assert llm._chat("s", "hello") == "OK"
