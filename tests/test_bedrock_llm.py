"""Bedrock adapter: Converse translation, tool calling, JSON mode, error classes. Fake runtime, no AWS, no network."""
import json

import pytest

from oasis.agent.bedrock_llm import BedrockClient, BedrockError, to_converse
from oasis.agent.llm import LiveLLM, classify_error


class FakeRuntime:
    def __init__(self, blocks, fail=None):
        self.blocks, self.fail, self.calls = blocks, fail, []

    def converse(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail
        return {"output": {"message": {"content": self.blocks}}, "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}}


def llm(tmp_path, rt):
    return LiveLLM(client=BedrockClient(rt), cache_dir=tmp_path, sleep=lambda s: None)


def test_json_mode_strips_fence_and_adds_hint(tmp_path):
    rt = FakeRuntime([{"text": "```json\n{\"a\": 1}\n```"}])
    out = llm(tmp_path, rt)._chat("sys", "user", json_mode=True)
    assert json.loads(out) == {"a": 1}
    assert "JSON" in rt.calls[0]["system"][0]["text"]


def test_image_and_usage(tmp_path):
    rt = FakeRuntime([{"text": "Payee: X"}])
    m = llm(tmp_path, rt)
    assert m._chat("s", "u", image=(b"\x89PNG", "image/png")) == "Payee: X"
    img = rt.calls[0]["messages"][0]["content"][0]["image"]
    assert img["format"] == "png" and img["source"]["bytes"] == b"\x89PNG"
    assert m.usage.day()["tokens"] == 15


def test_tool_calling_roundtrip(tmp_path):
    rt = FakeRuntime([{"text": "ok"}, {"toolUse": {"toolUseId": "t1", "name": "plan", "input": {"x": 2}}}])
    tools = [{"type": "function", "function": {"name": "plan", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
    r = llm(tmp_path, rt).chat_tools([{"role": "system", "content": "s"}, {"role": "user", "content": "go"}], tools)
    assert r["tool_calls"] == [{"id": "t1", "name": "plan", "arguments": {"x": 2}}]
    assert rt.calls[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "plan"


def test_message_conversion_merges_roles_and_tool_results():
    system, msgs = to_converse([
        {"role": "system", "content": "s"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t", "function": {"name": "f", "arguments": "{\"k\": 1}"}}]},
        {"role": "tool", "tool_call_id": "t", "content": "res"}])
    assert system == [{"text": "s"}] and [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert len(msgs[0]["content"]) == 2 and msgs[1]["content"][0]["toolUse"]["input"] == {"k": 1}
    assert msgs[2]["content"][0]["toolResult"]["toolUseId"] == "t"


@pytest.mark.parametrize("code,kind", [("ThrottlingException", "rate_limit"), ("AccessDeniedException", "auth"),
                                       ("ResourceNotFoundException", "model_gone")])
def test_error_classification(tmp_path, code, kind):
    err = Exception("boom")
    err.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": 400}}
    with pytest.raises(BedrockError) as e:
        BedrockClient(FakeRuntime([], fail=err)).chat.completions.create("m", [{"role": "user", "content": "x"}])
    assert classify_error(e.value) == kind
