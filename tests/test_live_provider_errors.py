"""A live Bedrock call that FAILS (credit exhausted, access denied, throttled, network down, malformed reply) must degrade to the
deterministic result, never raise, never leave money in a worse state. Fake runtime: no AWS, no network, no cost."""
import pytest

from eval.ai_contribution import GENUINE
from oasis.agent import chat_llm
from oasis.agent.bedrock_llm import BedrockClient
from oasis.agent.llm import LiveLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.world import Features, World

ERRORS = {
    "credit_exhausted": ("ServiceQuotaExceededException", 400),
    "access_denied": ("AccessDeniedException", 403),
    "throttled": ("ThrottlingException", 429),
    "server_error": ("InternalServerException", 500),
    "model_gone": ("ResourceNotFoundException", 404),
}


class FailingRuntime:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def converse(self, **kw):
        self.calls += 1
        raise self.exc


def _exc(code, status):
    e = Exception(f"{code}: simulated")
    e.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
    return e


@pytest.fixture(params=sorted(ERRORS) + ["network_down", "timeout"])
def failing(request, tmp_path):
    if request.param == "network_down":
        exc = ConnectionError("connection refused")
    elif request.param == "timeout":
        exc = TimeoutError("read timed out")
    else:
        exc = _exc(*ERRORS[request.param])
    rt = FailingRuntime(exc)
    llm = LiveLLM(client=BedrockClient(rt), cache_dir=tmp_path / "c", rpm=0, fallback_model=None, extract_mode="llm",
                  llm_risk=True, sleep=lambda s: None, max_retries=1)
    return llm, rt


def test_a_genuine_invoice_still_ends_held_for_signature_when_the_provider_fails(failing):
    llm, rt = failing
    w = World(Features.full(), llm)
    out = OasisAgent(w).handle(Request(GENUINE[0], source="invoice", remitter="student"))
    assert out.status == "held" and w.ledger.money_lost() == 0 and sum(t.amount for t in w.ledger.transfers) == 0


def test_chat_labeller_and_explanations_fall_back_when_the_provider_fails(failing):
    llm, _ = failing
    assert chat_llm.propose(llm, "what are you capable of, exactly?") is None
    assert llm.explain("flightpath", {"text": "x", "facts": {}, "options": []}, "en")      # the template, not an exception
    assert llm.draft_recovery({"recipient": "University X Finance Office"}) is None
