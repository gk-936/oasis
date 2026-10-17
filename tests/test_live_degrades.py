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
