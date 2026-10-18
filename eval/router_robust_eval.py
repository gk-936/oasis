"""Before/after of the offline router robustness layers (agent/robust.py) on every message set and outside-written set we have. OFFLINE: no model call.

"Before" = OASIS_ROUTER_ROBUST=0 (the keyword router alone, which already includes the earlier keyword fixes); "after" = the default.
Run: OASIS_LLM=offline PYTHONPATH=. python -m eval.router_robust_eval        (writes eval/reports/router_robust.{md,json})

Honesty notes written into the report: the router-example held-out file is out-of-sample for the matcher (never read by it) but written by the
same team; the message sets and the outside-written sets were used for earlier router fixes, so their numbers are NOT first-run numbers.
"""
from __future__ import annotations
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ["OASIS_LLM"] = "offline"
os.environ.setdefault("OASIS_EXTRACT", "deterministic")
from eval import independent_bench as ib  # noqa: E402  (sets the offline, in-memory environment)
from eval import outside_scenarios_offline as osc  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from oasis.agent import robust  # noqa: E402
from oasis.api import main as api  # noqa: E402

HERE = Path(__file__).resolve().parent
CHAT = HERE / "chat_llm"
REPORT = HERE / "reports"
HELDOUT = HERE.parent / "tests" / "data" / "router_heldout.json"
HELDOUT2 = HERE.parent / "tests" / "data" / "router_heldout2.json"
HELDOUT3 = HERE.parent / "tests" / "data" / "router_heldout3.json"
H1, H2, H3 = ("router held-out 1 (326; tuned: drove the round-4 fixes)", "router held-out 2 (200; tuned: drove the round-5 rule classes)",
              "router held-out 3 (120; written first, never tuned on: the honest row)")
MSG_SETS = (("messages (first set)", CHAT / "messages.json"), ("fresh", CHAT / "messages_fresh.json"),
            ("held-out (chat labeller)", CHAT / "messages_heldout.json"), ("scale", CHAT / "messages_scale.json"))
OUTSIDE = (("Codex scenarios (80)", CHAT / "outside_codex_scenarios.json"), ("Codex round 2 (250)", CHAT / "outside_codex_round2.json"))
INDEPENDENT = (("set 1", ""), ("set 2", "2"), ("set 3 (ChatGPT)", "3"), ("set A", "A"), ("set C (Codex)", "C"), ("set G (Gemini)", "G"))


def setting(on: bool) -> None:
    os.environ["OASIS_ROUTER_ROBUST"] = "1" if on else "0"


def client() -> TestClient:
    c = TestClient(api.app)
    c.post("/api/auth/login", json={"role": "student", "passcode": "student-demo"})
    return c


def verdict(expected: str, label: str) -> str:
    if expected == "unknown":
        return "right" if label in ("unknown", "clarify") else "wrong"
    if expected == "other":                       # chit-chat or noise: the right outcome is to claim no intent
        return "right" if label == "unknown" else ("clarified" if label == "clarify" else "wrong")
    return "right" if label == expected else ("clarified" if label == "clarify" else ("unknown" if label == "unknown" else "wrong"))


def message_set(cases: list[dict], c: TestClient, lat: list[float]) -> dict:
    """cases: {text, expected, kind}. Label from the router; money and drafts from a real /api/chat turn in a fresh session."""
    out = {"n": len(cases), "right": 0, "wrong": 0, "unknown": 0, "clarified": 0, "money_moved": 0.0, "paid": 0, "drafts": 0, "trap_pay_label": 0}
    for m in cases:
        label = robust.route(m["text"])[0]
        v = verdict(m["expected"], label) if m.get("kind", "paraphrase") != "trap" else None
        if v:
            out[v] += 1
        elif label == "pay_obligation":
            out["trap_pay_label"] += 1
        c.post("/api/reset")
        t0 = time.perf_counter()
        j = c.post("/api/chat", json={"message": m["text"]}).json()
        lat.append((time.perf_counter() - t0) * 1000)
        out["money_moved"] += float(j.get("money_moved") or 0)
        out["paid"] += j.get("status") == "paid"
        out["drafts"] += bool(j.get("pending_id"))
    return out


def run_config(on: bool) -> dict:
    setting(on)
    res: dict = {"messages": {}, "outside": {}, "independent": {}, "latency_ms": {}}
    c, lat = client(), []
    for name, path in MSG_SETS:
        res["messages"][name] = message_set(json.loads(path.read_text(encoding="utf-8"))["messages"], c, lat)
    held = json.loads(HELDOUT.read_text(encoding="utf-8"))["cases"]
    res["messages"][H1] = message_set([{"text": x["text"], "expected": x["expected"]} for x in held], c, lat)
    held2 = json.loads(HELDOUT2.read_text(encoding="utf-8"))["cases"]
    res["messages"][H2] = message_set([{"text": x["text"], "expected": x["expected"]} for x in held2], c, lat)
    held3 = json.loads(HELDOUT3.read_text(encoding="utf-8"))["cases"]
    res["messages"][H3] = message_set([{"text": x["text"], "expected": x["expected"]} for x in held3], c, lat)
    res["latency_ms"] = {"n": len(lat), "median": round(statistics.median(lat), 1), "p95": round(sorted(lat)[int(len(lat) * 0.95)], 1), "max": round(max(lat), 1)}
    for name, path in OUTSIDE:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = [osc.run_one(osc.repair(s) or s) for s in data["scenarios"]]
        res["outside"][name] = {"n": len(rows), "passed": sum(r["ok"] for r in rows), "unsafe": sum(r["unsafe"] for r in rows),
                                "money_moved": sum(r["money_moved"] for r in rows)}
    for name, suf in INDEPENDENT:
        rep = ib.run(suf)
        res["independent"][name] = {k: [sum(r["ok"] for r in rep[k]), len(rep[k])] for k in ("tasks", "attacks", "lookalikes")}
    return res


def table(before: dict, after: dict) -> str:
    L = ["| Message set (paraphrases) | n | correct before > after | wrong before > after | unknown before > after | clarified after | money moved | drafts created before > after |", "|---|---|---|---|---|---|---|---|"]
    tot = {k: [0, 0] for k in ("n", "right", "wrong", "unknown", "clarified")}
    for name in after["messages"]:
        b, a = before["messages"][name], after["messages"][name]
        n = a["right"] + a["wrong"] + a["unknown"] + a["clarified"]
        if name in (H2, H3):                                    # shown on its own row; the 481 total stays comparable with the earlier report
            L.append(f"| {name} | {n} | {b['right']} > {a['right']} | {b['wrong']} > {a['wrong']} | {b['unknown']} > {a['unknown']} | {a['clarified']} | {a['money_moved']:g} | {b['drafts']} > {a['drafts']} |")
            continue
        for k in ("right", "wrong", "unknown"):
            tot[k][0] += b[k]
            tot[k][1] += a[k]
        tot["clarified"][1] += a["clarified"]
        tot["n"][0] += n
        L.append(f"| {name} | {n} | {b['right']} > {a['right']} | {b['wrong']} > {a['wrong']} | {b['unknown']} > {a['unknown']} | {a['clarified']} | {a['money_moved']:g} | {b['drafts']} > {a['drafts']} |")
    L.append(f"| **sum of the five rows other than held-out 2 and 3** | {tot['n'][0]} | {tot['right'][0]} > {tot['right'][1]} | {tot['wrong'][0]} > {tot['wrong'][1]} | {tot['unknown'][0]} > {tot['unknown'][1]} | {tot['clarified'][1]} | | |")
    L += ["", "| Outside-written scenario set | n | met every expectation before > after | scenarios where money moved or was lost |", "|---|---|---|---|"]
    for name, a in after["outside"].items():
        b = before["outside"][name]
        L.append(f"| {name} | {a['n']} | {b['passed']} > {a['passed']} | {b['unsafe']} > {a['unsafe']} (money moved {a['money_moved']:g}) |")
    L += ["", "| Independent set | tasks before > after | attacks passed before > after | look-alikes passed before > after |", "|---|---|---|---|"]
    for name, a in after["independent"].items():
        b = before["independent"][name]
        L.append(f"| {name} | {b['tasks'][0]}/{b['tasks'][1]} > {a['tasks'][0]}/{a['tasks'][1]} | {b['attacks'][0]}/{b['attacks'][1]} > {a['attacks'][0]}/{a['attacks'][1]} | "
                 f"{b['lookalikes'][0]}/{b['lookalikes'][1]} > {a['lookalikes'][0]}/{a['lookalikes'][1]} |")
    return "\n".join(L)


def main() -> int:
    before, after = run_config(False), run_config(True)
    setting(True)
    lat = after["latency_ms"]
    md = ["# Router robustness layers: before and after (offline, no model call)", "",
          "Before = keyword router alone; after = keyword router + normalisation, slot rules, similarity fallback, arbitration and clarification (`agent/robust.py`).",
          "**Honest labels:** held-out 3 (120 phrases) was written before the round-5 changes and never used for tuning: it is the honest figure (out-of-sample for the matcher, written by the team that wrote the router). "
          "Held-out 1 and 2 are no longer out-of-sample: their failures were used to fix keyword rules. Every other set below was used for earlier router fixes, so those figures are not first-run figures. 'Right' means the label equals the one written with the message.", "",
          table(before, after), "",
          f"Reply latency over {lat['n']} chat turns through the API test client (router + handler + save): median {lat['median']} ms, p95 {lat['p95']} ms, max {lat['max']} ms. "
          "The matcher alone takes about 1 ms per message."]
    REPORT.mkdir(exist_ok=True)
    (REPORT / "router_robust.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (REPORT / "router_robust.json").write_text(json.dumps({"before": before, "after": after}, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
