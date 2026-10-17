"""Amazon Bedrock (Amazon Nova Pro) client for `LiveLLM` (llm.py).

`BedrockClient` exposes an OpenAI-style `client.chat.completions.create(...)` and answers it with the Bedrock Converse API,
so extraction, risk, explanations, red-team variants, image intake and the native tool-calling planner all share
LiveLLM's cache, retry, rate limit and budget logic.

Select it with OASIS_LLM=bedrock. Credentials come from the normal AWS chain (env vars, profile, role); nothing is read
from or written to the repo. Model/region: OASIS_BEDROCK_MODEL, OASIS_BEDROCK_REGION (see docs/configuration.md).
Safety layers never depend on the model: it only extracts and explains."""
from __future__ import annotations
import base64
import json
import re
from types import SimpleNamespace as NS

from .. import config

JSON_HINT = "\n\nReturn ONLY one valid JSON object. No markdown fence, no commentary."
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


class BedrockError(Exception):
    """Carries an HTTP-style status so llm.classify_error treats throttling, auth and unknown models consistently."""
    def __init__(self, msg: str, status_code: int | None = None):
        super().__init__(msg)
        self.status_code = status_code


def _content_blocks(content) -> list[dict]:
    """OpenAI-style message content (str, or text / image_url parts) -> Converse content blocks."""
    if isinstance(content, str):
        return [{"text": content or " "}]
    out = []
    for part in content or []:
        if part.get("type") == "text":
            out.append({"text": part["text"]})
        elif part.get("type") == "image_url":
            m = re.match(r"data:image/(\w+);base64,(.*)", part["image_url"]["url"], re.S)
            fmt = {"jpg": "jpeg"}.get(m.group(1), m.group(1))
            out.append({"image": {"format": fmt, "source": {"bytes": base64.b64decode(m.group(2))}}})
    return out or [{"text": " "}]


def to_converse(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (system blocks, messages). Tool results become user toolResult blocks; consecutive same-role turns are merged."""
    system, out = [], []

    def add(role, blocks):
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        r = m["role"]
        if r == "system":
            system.append({"text": m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])})
        elif r == "tool":
            add("user", [{"toolResult": {"toolUseId": m["tool_call_id"], "content": [{"text": str(m["content"]) or " "}]}}])
        elif r == "assistant":
            blocks = [{"text": m["content"]}] if m.get("content") else []
            for tc in m.get("tool_calls") or []:
                fn = tc["function"] if isinstance(tc, dict) else tc.function
                args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
                blocks.append({"toolUse": {"toolUseId": tc["id"] if isinstance(tc, dict) else tc.id,
                                           "name": fn["name"] if isinstance(fn, dict) else fn.name,
                                           "input": json.loads(args or "{}") if isinstance(args, str) else (args or {})}})
            add("assistant", blocks or [{"text": " "}])
        else:
            add("user", _content_blocks(m["content"]))
    return system, out


def to_tool_config(tools: list[dict], tool_choice: str | None) -> dict:
    specs = [{"toolSpec": {"name": t["function"]["name"], "description": t["function"].get("description", "") or t["function"]["name"],
                           "inputSchema": {"json": t["function"].get("parameters") or {"type": "object", "properties": {}}}}} for t in tools]
    return {"tools": specs, **({"toolChoice": {"auto": {}}} if tool_choice == "auto" else {})}


class _Completions:
    def __init__(self, runtime):
        self._rt = runtime

    def create(self, model, messages, temperature=0.0, response_format=None, tools=None, tool_choice=None,
               max_tokens=1500, **_ignored):          # extra provider-specific kwargs are ignored
        system, msgs = to_converse(messages)
        json_mode = bool(response_format) and not tools
        if json_mode:
            system = (system or [{"text": ""}])[:-1] + [{"text": (system[-1]["text"] if system else "") + JSON_HINT}]
        kw = dict(modelId=model, messages=msgs, inferenceConfig={"temperature": temperature, "maxTokens": max_tokens})
        if system:
            kw["system"] = system
        if tools:
            kw["toolConfig"] = to_tool_config(tools, tool_choice)
        try:
            r = self._rt.converse(**kw)
        except Exception as e:  # noqa: BLE001 - botocore ClientError and friends
            meta = getattr(e, "response", {}) or {}
            status = (meta.get("ResponseMetadata") or {}).get("HTTPStatusCode")
            code = (meta.get("Error") or {}).get("Code", "")
            if code == "ThrottlingException":
                status = 429
            elif code in ("AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException"):
                status = 403
            elif code in ("ResourceNotFoundException", "ModelNotReadyException") or "model identifier is invalid" in str(e).lower():
                status = 404
            raise BedrockError(f"{code or type(e).__name__}: {e}", status) from None
        blocks = r["output"]["message"]["content"]
        text = "".join(b.get("text", "") for b in blocks)
        if json_mode:
            text = _FENCE.sub("", text.strip())
        calls = [NS(id=b["toolUse"]["toolUseId"], function=NS(name=b["toolUse"]["name"], arguments=json.dumps(b["toolUse"]["input"])))
                 for b in blocks if "toolUse" in b]
        u = r.get("usage") or {}
        return NS(choices=[NS(message=NS(content=text, tool_calls=calls))],
                  usage=NS(total_tokens=u.get("totalTokens", u.get("inputTokens", 0) + u.get("outputTokens", 0))))


class BedrockClient:
    def __init__(self, runtime=None, region: str | None = None):
        if runtime is None:
            import boto3
            from botocore.config import Config
            runtime = boto3.client("bedrock-runtime", region_name=region or config.BEDROCK_REGION,
                                   config=Config(retries={"max_attempts": 1}, read_timeout=config.BEDROCK_TIMEOUT,
                                                  connect_timeout=config.BEDROCK_CONNECT_TIMEOUT))   # our own backoff
        self.chat = NS(completions=_Completions(runtime))
