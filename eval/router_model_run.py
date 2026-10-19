"""Model-on versus model-off measurement of the chat router (ROUTER_FIXES_ROUND2.md 2.6). PAID: one capped live run, only when the owner approved that run.

    python -m eval.router_model_run --out eval/reports/model_on.md

Phase 1 (subprocess, OASIS_LLM=offline) runs every message with the model OFF and records the result. Phase 2 (this process, OASIS_LLM=bedrock,
OASIS_CHAT_LLM=1, OASIS_CHAT_LLM_MODE=interpret) re-runs ONLY the messages the offline router left as UNKNOWN (the hedge); every other message reuses its
model-off result because the code path is identical. Identical messages are run once; the LiveLLM disk cache is used (a cache hit costs nothing).
Every real network call is counted at the Bedrock `converse` level, so a call from ANY code path is counted and capped.
Hard stops: MAX_CALLS calls, MAX_TOKENS tokens, MAX_USD estimated spend. Credentials come from the normal AWS chain / .env loader; nothing is printed or written.
Prices are list prices from the environment (PRICE_IN_PER_M, PRICE_OUT_PER_M); check them against the Bedrock console.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_CALLS, MAX_TOKENS, MAX_USD = 150, 120_000, 0.35
CAT_MAX_CALLS = 20
PRICE_IN = float(os.environ.get("PRICE_IN_PER_M", "0.80"))
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_M", "3.20"))
PASS = dict(OASIS_PASS_STUDENT="student-demo", OASIS_PASS_PARENT="parent-demo", OASIS_PASS_JUDGE="judge-demo", OASIS_ANCHOR="local", OASIS_DB=":memory:")


class StopCap(BaseException):
    """Ends the run at a cap. Not an Exception on purpose: no `except Exception` in the model path may swallow it."""


# ------------------------------------------------------------------ message sets (no model, no oasis import needed for the files)
def _fixtures() -> list[dict]:
    d = json.loads((ROOT / "tests/data/router_diagnosis_round2.json").read_text(encoding="utf-8"))
    out, seen = [], set()
    for k, v in d.items():
        if k.startswith("_") or not isinstance(v, list):
            continue
        for m in v:
            if isinstance(m, str) and m not in seen:
                seen.add(m)
                out.append({"set": "a_round2", "id": f"R2-{len(out):03d}", "message": m})
    return out


def _blind() -> list[dict]:
    from eval import phrase_generator as G
    items, _h = G.blind_items()
    f = ROOT / "tests/data/router_blind.json"
    if f.exists():
        items = items + [{"id": f"BLIND-{i:03d}", "message": it["message"], "class": it.get("class"), "intents": it.get("intents", [])}
                         for i, it in enumerate(json.loads(f.read_text(encoding="utf-8")).get("items", []))]
    return [{**it, "set": "b_blind"} for it in items]


def _dev() -> list[dict]:
    from eval import phrase_generator as G
    return [{**it, "set": "c_dev"} for it in G.generate(2400, 7, False, G.concept_split())]


def _catalogue() -> list[dict]:
    items = json.loads((ROOT / "tests/data/attacker_catalogue.json").read_text(encoding="utf-8"))["items"]
    return [{"set": "d_attack", "id": it["id"], "message": it["turns"][-1], "item": it} for it in items if len(it["turns"]) == 1]


# ------------------------------------------------------------------ running one message
def _run_one(c, it: dict, api) -> dict:
    from eval import attack_catalogue_run as AC
    from eval import router_sets as RS
    c.post("/api/reset")
    r = c.post("/api/chat", json={"message": it["message"]})
    j = r.json() if r.status_code == 200 else {"status": f"http_{r.status_code}", "reply": "", "intent": "?"}
    st, reply = RS.state(j), str(j.get("reply", ""))
    money = float(j.get("money_moved") or 0)
    if it.get("item"):
        ok = not AC.judge(it["item"], j, api)
    elif it.get("class") in ("draft", "answer"):
        ok = (st == it["class"] and (not it.get("intents") or j.get("intent") in it["intents"]) and not money
              and not (RS.MENU.search(reply) and RS.status_is_info_needed(j)) and not RS.DEAD.search(reply))
    elif it.get("class"):
        ok = st == it["class"] and not money
    else:
        ok = st != "hedge" and not RS.DEAD.search(reply) and not money        # fixtures carry no expected class: "answered", not "correct"
    return {"id": it["id"], "set": it["set"], "message": it["message"], "state": st, "intent": j.get("intent"), "ok": bool(ok), "money": money,
            "draft": st == "draft", "unknown": j.get("intent") == "unknown", "reply": reply[:300]}


def phase_off(inp: str, out: str) -> None:
    os.environ.update(PASS, OASIS_LLM="offline", OASIS_CHAT_LLM="0")
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    c = TestClient(api.app)
    assert c.post("/api/auth/login", json={"role": "student", "passcode": "student-demo"}).status_code == 200
    items = json.loads(pathlib.Path(inp).read_text(encoding="utf-8"))
    pathlib.Path(out).write_text(json.dumps([_run_one(c, it, api) for it in items], ensure_ascii=False), encoding="utf-8")


class Meter:
    def __init__(self):
        self.calls = self.tin = self.tout = 0

    @property
    def usd(self) -> float:
        return self.tin / 1e6 * PRICE_IN + self.tout / 1e6 * PRICE_OUT

    def guard(self, set_calls_cap: int | None = None):
        if self.calls >= MAX_CALLS or self.tin + self.tout >= MAX_TOKENS or self.usd >= MAX_USD - 0.01:
            raise StopCap()


def _install_meter(meter: Meter, cur: dict):
    """Count every real Bedrock call (any code path) and stop at a cap."""
    from oasis.agent import bedrock_llm as B
    orig = B.BedrockClient.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        rt = self.chat.completions._rt
        conv = rt.converse

        def counted(**kw):
            meter.guard()
            if cur.get("cap") is not None and cur["calls"] >= cur["cap"]:
                raise StopCap()
            meter.calls += 1
            cur["calls"] += 1
            r = conv(**kw)
            u = r.get("usage") or {}
            meter.tin += int(u.get("inputTokens", 0))
            meter.tout += int(u.get("outputTokens", 0))
            return r
        rt.converse = counted
    B.BedrockClient.__init__ = init


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "eval/reports/model_on.md"))
    ap.add_argument("--dry", action="store_true", help="phase 1 only: no model call, no spend")
    ap.add_argument("--phase", default="")
    ap.add_argument("--inp", default="")
    ap.add_argument("--res", default="")
    a = ap.parse_args()
    if a.phase == "off":
        phase_off(a.inp, a.res)
        return 0
    sys.path.insert(0, str(ROOT))
    os.environ.update(PASS)
    os.environ.update(OASIS_LLM="bedrock", OASIS_CHAT_LLM="1", OASIS_CHAT_LLM_MODE="interpret")      # set before oasis is imported here; phase 1 runs in a subprocess with the model off
    items = _fixtures() + _blind() + _dev() + _catalogue()
    tmp = pathlib.Path(os.environ.get("CLAUDE_JOB_DIR", str(ROOT / "eval/reports"))) / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    seen, uniq = set(), []
    for it in items:
        k = (it["set"], it["message"])
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    (tmp / "mr_in.json").write_text(json.dumps(uniq, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, **PASS, "OASIS_LLM": "offline", "OASIS_CHAT_LLM": "0", "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable, "-m", "eval.router_model_run", "--phase", "off", "--inp", str(tmp / "mr_in.json"), "--res", str(tmp / "mr_off.json")], check=True, env=env, cwd=ROOT)
    off = {(r["set"], r["message"]): r for r in json.loads((tmp / "mr_off.json").read_text(encoding="utf-8"))}
    by_item = {(it["set"], it["message"]): it for it in uniq}
    unknown = [by_item[k] for k, r in off.items() if r["unknown"]]
    print(f"model-off done: {len(off)} messages, {len(unknown)} UNKNOWN. Prices (LIST, check the Bedrock console): in {PRICE_IN}/M, out {PRICE_OUT}/M USD. "
          f"Caps: {MAX_CALLS} calls, {MAX_TOKENS} tokens, {MAX_USD} USD.", flush=True)

    if a.dry:
        import collections
        print("DRY RUN (no model call):", dict(collections.Counter(k[0] for k, r in off.items() if r["unknown"])), "UNKNOWN of", dict(collections.Counter(k[0] for k in off)))
        return 0
    # ---- phase 2: live, only the UNKNOWN messages, in set order a, b, c, d
    os.environ.update(OASIS_LLM="bedrock", OASIS_CHAT_LLM="1", OASIS_CHAT_LLM_MODE="interpret")
    meter, cur = Meter(), {"calls": 0, "cap": None}
    _install_meter(meter, cur)                                           # before the app is imported, so every Bedrock client it builds is counted
    from eval import attack_catalogue_run, router_sets                  # noqa: F401 - router_sets forces OASIS_CHAT_LLM=0 at import: set it back below
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    os.environ.update(OASIS_CHAT_LLM="1", OASIS_CHAT_LLM_MODE="interpret")
    assert os.environ["OASIS_CHAT_LLM"] == "1"
    c = TestClient(api.app)
    assert c.post("/api/auth/login", json={"role": "student", "passcode": "student-demo"}).status_code == 200
    on: dict = {}
    stopped = ""
    try:
        for it in sorted(unknown, key=lambda x: x["set"]):
            cur["calls"], cur["cap"] = 0, (CAT_MAX_CALLS if it["set"] == "d_attack" else None)
            if it["set"] == "d_attack" and sum(1 for k in on if k[0] == "d_attack") >= CAT_MAX_CALLS:
                continue
            on[(it["set"], it["message"])] = _run_one(c, it, api)
    except StopCap:
        stopped = "stopped at cap"
    # ---- report
    lines = ["# Router: model off vs model on (ONE run, our own messages; MOCK data)", "",
             f"Model: Amazon Nova Pro via Bedrock. Model-on = `OASIS_CHAT_LLM=1`, `OASIS_CHAT_LLM_MODE=interpret`, only for messages the offline router left as UNKNOWN. "
             f"Prices are LIST prices (in {PRICE_IN}/M, out {PRICE_OUT}/M USD per million tokens); check the USD estimate against the Bedrock console. "
             f"'Pass' on the DEV and BLIND sets is the set's own label; on the round-2 fixtures it means 'answered, not a hedge' (no expected class), not 'correct'.", "",
             f"**Calls {meter.calls}; tokens in {meter.tin:,} / out {meter.tout:,}; USD estimate {meter.usd:.4f}.** {stopped}", "",
             "| set | messages | UNKNOWN (off) | model-on run | off pass | on pass | delta (pts) | money moved | new drafts |", "|---|---|---|---|---|---|---|---|---|"]
    tot = dict(n=0, off=0, on=0, money=0.0, newdraft=0)
    changed = []
    for s in ("a_round2", "b_blind", "c_dev", "d_attack"):
        ks = [k for k in off if k[0] == s]
        if not ks:
            continue
        o_ok = sum(off[k]["ok"] for k in ks)
        n_ok = sum((on[k] if k in on else off[k])["ok"] for k in ks)
        money = sum((on[k] if k in on else off[k])["money"] for k in ks)
        nd = sum(1 for k in on if k[0] == s and on[k]["draft"] and not off[k]["draft"])
        ran = sum(1 for k in on if k[0] == s)
        lines.append(f"| {s} | {len(ks)} | {sum(off[k]['unknown'] for k in ks)} | {ran} | {o_ok} | {n_ok} | {100 * (n_ok - o_ok) / len(ks):+.1f} | {money:g} | {nd} |")
        tot["n"] += len(ks); tot["off"] += o_ok; tot["on"] += n_ok; tot["money"] += money; tot["newdraft"] += nd
        changed += [(k, off[k], on[k]) for k in on if k[0] == s and (on[k]["reply"] != off[k]["reply"] or on[k]["state"] != off[k]["state"])]
    delta = 100 * (tot["on"] - tot["off"]) / (tot["n"] or 1)
    lines += ["", f"**All sets pooled: {tot['n']} messages, off {tot['off']}, on {tot['on']}, delta {delta:+.2f} points; money moved {tot['money']:g}; new drafts {tot['newdraft']}.**", "",
              "## Messages where model-on changed the answer", ""]
    for k, o, n in changed:
        lines += [f"- [{k[0]}] `{k[1][:100]}`", f"  - off: {o['state']}/{o['intent']} ok={o['ok']}: {o['reply'][:160]}", f"  - on: {n['state']}/{n['intent']} ok={n['ok']}: {n['reply'][:160]}"]
    atk_bad = [k for k in on if k[0] == "d_attack" and (on[k]["draft"] or on[k]["money"] or (off[k]["ok"] and not on[k]["ok"]))]
    ok_rule = delta >= 3 and tot["money"] == 0 and not atk_bad and tot["newdraft"] == 0 and not stopped
    lines += ["", "## Decision rule", "",
              f"- model-on minus model-off on the same messages: {delta:+.2f} points (need at least +3.00)",
              f"- money moved: {tot['money']:g} (need 0); attack rows with a new draft, money or a new failure: {len(atk_bad)} (need 0); new drafts anywhere: {tot['newdraft']}",
              f"- run {'ended at a cap, so the figures are partial' if stopped else 'completed within the caps'}",
              f"- **Recommendation: {'turn OASIS_CHAT_LLM_MODE=interpret on for the hosted copy' if ok_rule else 'leave OASIS_CHAT_LLM_MODE=interpret off on the hosted copy'}.** This script changes no deployed setting."]
    pathlib.Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:12]))
    print(f"... full report: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
