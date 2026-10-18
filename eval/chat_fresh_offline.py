"""Offline baseline on the fresh chat set: how the keyword router alone does (right / wrong / unknown / unsafe). No model call.

Run: OASIS_LLM=offline PYTHONPATH=. python -m eval.chat_fresh_offline
pay_label = the router gave a vague/hostile message the payment label; end to end it still moves no money
(tests/test_chat_fresh_set.py). The live labeller is NOT run here (paid; needs the owner's approval); this is the deterministic baseline it would be compared with.
"""
from __future__ import annotations
import json
import os
from collections import Counter
from pathlib import Path

os.environ["OASIS_LLM"] = "offline"
from oasis.agent import nlu  # noqa: E402

SET = Path(__file__).resolve().parent / "chat_llm" / "messages_fresh.json"
PAY = "pay_obligation"


def verdict(m: dict, got: str) -> str:
    if m["kind"] == "trap":
        return "pay_label" if got == PAY else ("unknown" if got == nlu.UNKNOWN else "refused_or_other")
    if got == nlu.UNKNOWN:
        return "unknown"
    return "right" if got == m["expected"] else "wrong"


def run() -> dict:
    msgs = json.loads(SET.read_text(encoding="utf-8"))["messages"]
    rows = [{"text": m["text"], "kind": m["kind"], "expected": m["expected"], "got": (g := nlu.classify(m["text"]).kind),
             "verdict": verdict(m, g)} for m in msgs]
    return {"n": len(rows), "by_kind": {k: dict(Counter(r["verdict"] for r in rows if r["kind"] == k)) for k in ("paraphrase", "trap")}, "rows": rows}


REPORT = Path(__file__).resolve().parent / "reports" / "chat_fresh_offline.md"


def write_report(o: dict) -> None:
    lines = ["# Fresh chat set, offline router baseline (no model call)", "", f"{o['n']} messages; keyword router only.", ""]
    lines += [f"- {k}: {v}" for k, v in o["by_kind"].items()]
    lines += ["", "| verdict | expected | router said | message |", "|---|---|---|---|"]
    lines += [f"| {r['verdict']} | {r['expected']} | {r['got']} | {r['text']} |" for r in o["rows"]]
    REPORT.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


if __name__ == "__main__":
    o = run()
    write_report(o)
    print(f"fresh set: {o['n']} messages (router only, offline)")
    for k, v in o["by_kind"].items():
        print(f"  {k}: {v}")
    for r in o["rows"]:
        if r["verdict"] in ("wrong", "pay_label"):
            print(f"  {r['verdict']:12} {r['text']!r} -> {r['got']} (expected {r['expected']})")
