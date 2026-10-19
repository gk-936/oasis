"""Scores the router on the three sets of ROUTER_OVERHAUL.md section 9 and writes eval/reports/router_sets.md (and a JSON of every row).

    OASIS_LLM=offline PYTHONPATH=. python -m eval.router_sets [--n-dev 2400] [--n-held 1600] [--blind]

DEV is tuned on. WORD-HELD-OUT runs with the withheld 30% of every concept's words removed from the router's lexicon. BLIND is read once per release candidate
(its hash is printed). Offline only: no model, no network, CNY 0 can move (the chat path has no signer here).
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import json
import os
import pathlib
import re
import sys
import time

os.environ.setdefault("OASIS_LLM", "offline")
os.environ.setdefault("OASIS_DB", ":memory:")
os.environ.update(OASIS_PASS_STUDENT="student-demo", OASIS_PASS_PARENT="parent-demo", OASIS_PASS_JUDGE="judge-demo", OASIS_ANCHOR="local", OASIS_CHAT_LLM="0")

from eval import phrase_generator as G  # noqa: E402
from oasis.agent import frames, lexicon as L  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
MENU = re.compile(r"(?<![*\d])1\) .*2\) |Did you mean:")
HEDGE = re.compile(r"^What do you need:|^I think you're asking about")
DEAD = re.compile(r"didn't catch|not sure what you mean", re.I)


@contextlib.contextmanager
def router_without(withheld: dict):
    """Remove the withheld words from the router's lexicon for the duration of the block."""
    saved = (dict(L.BILLS), dict(L.INFO))
    drop = {k: set(v) for k, v in withheld["bills"].items()}
    dropi = {k: set(v) for k, v in withheld["info"].items()}
    L.BILLS.update({k: (c, tuple(w for w in ws if w not in drop.get(k, ()))) for k, (c, ws) in saved[0].items()})
    L.INFO.update({k: (c, tuple(w for w in ws if w not in dropi.get(k, ()))) for k, (c, ws) in saved[1].items()})
    L._CACHE.clear()
    frames._VOCAB = None
    try:
        yield
    finally:
        L.BILLS.update(saved[0])
        L.INFO.update(saved[1])
        L._CACHE.clear()
        frames._VOCAB = None


def status_is_info_needed(j: dict) -> bool:
    return j.get("status") == "needs_info" or j.get("intent") == "clarify"


def state(j: dict) -> str:
    intent, status, reply = j.get("intent"), j.get("status"), j.get("reply", "")
    if intent in ("secrets", "bypass", "scam_warning") or status in ("rejected", "refused", "frozen", "needs_verification"):
        return "refuse"
    if status in ("held", "needs_confirmation") or j.get("pending_id"):
        return "draft"
    if status == "needs_info" or intent == "clarify":
        return "clarify"
    if intent == "unknown":
        return "hedge"
    return "answer"


def score(items: list[dict]) -> dict:
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    c = TestClient(api.app)
    assert c.post("/api/auth/login", json={"role": "student", "passcode": "student-demo"}).status_code == 200
    rows = []
    for it in items:
        c.post("/api/reset")
        r = c.post("/api/chat", json={"message": it["message"]})
        j = r.json() if r.status_code == 200 else {"status": f"http_{r.status_code}", "reply": "", "intent": "?"}
        st = state(j)
        reply = str(j.get("reply", ""))
        want = it.get("class")
        ok_intent = (not it.get("intents")) or j.get("intent") in it["intents"]
        passed = (st == want and ok_intent and not j.get("money_moved") and not (MENU.search(reply) and status_is_info_needed(j)) and not DEAD.search(reply)) if want in ("draft", "answer") else (st == want and not j.get("money_moved"))
        rows.append({"id": it["id"], "message": it["message"], "want": want, "intents": it.get("intents"), "got": st, "intent": j.get("intent"), "ok": passed,
                     "menu": bool(MENU.search(reply)) and (status_is_info_needed(j)), "hedge": bool(HEDGE.search(reply)), "dead": bool(DEAD.search(reply)), "money": j.get("money_moved") or 0,
                     "refused": st == "refuse", "concept": it.get("concept") or it.get("bill"), "reply": reply[:120]})
    n = len(rows) or 1
    gen = [r for r in rows if r["want"] in ("draft", "answer")]
    conf = collections.Counter((r["concept"], r["intent"]) for r in rows if not r["ok"])
    return {"n": len(rows), "pass": sum(r["ok"] for r in rows), "rate": sum(r["ok"] for r in rows) / n,
            "menu_rate": sum(r["menu"] for r in gen) / (len(gen) or 1), "hedge_rate": sum(r["hedge"] for r in rows) / n, "dead": sum(r["dead"] for r in rows),
            "wrong_rate": sum(1 for r in gen if r["got"] == "answer" and not r["ok"] and not r["hedge"]) / (len(gen) or 1),
            "false_refusal": sum(r["refused"] for r in gen) / (len(gen) or 1), "money": sum(r["money"] for r in rows),
            "confusion": conf.most_common(12), "worst": [r for r in rows if not r["ok"]][:30], "rows": rows}


def frozen_items() -> tuple[int, int]:
    from eval import frozen_set as F
    n = k = 0
    for items in (F.TASKS, F.QUESTIONS, F.ATTACKS):
        for r in F.run(items):
            n += 1
            k += r["ok"]
    return k, n


def fmt(name: str, s: dict, note: str) -> list[str]:
    out = [f"### {name}", "", note, "",
           f"- messages {s['n']}; **pass {s['pass']}/{s['n']} = {100 * s['rate']:.1f}%**",
           f"- menu rate on answer/draft messages {100 * s['menu_rate']:.2f}%; hedge rate {100 * s['hedge_rate']:.1f}%; dead-end replies {s['dead']}",
           f"- wrong-answer rate {100 * s['wrong_rate']:.2f}%; false-refusal rate on genuine messages {100 * s['false_refusal']:.2f}%; money moved {s['money']}", "",
           "Top confusions (concept, answered intent): " + ", ".join(f"{a}->{b} x{n}" for (a, b), n in s["confusion"]), "", "30 worst failures:", ""]
    out += [f"- `{r['message'][:90]}` wanted {r['want']}/{r['intents']}, got {r['got']}/{r['intent']}" for r in s["worst"]]
    return out + [""]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-dev", type=int, default=2400)
    ap.add_argument("--n-held", type=int, default=1600)
    ap.add_argument("--blind", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "eval" / "reports" / "router_sets.md"))
    a = ap.parse_args()
    t0 = time.time()
    split = G.concept_split()
    dev = score(G.generate(a.n_dev, 7, False, split))
    fk, fn = frozen_items()
    with router_without(G.withheld_words(split)):
        held = score(G.generate(a.n_held, 7, True, split))
    blind, bh = G.blind_items()
    b = score(blind) if (a.blind and blind) else None
    lines = ["# Router sets (offline, model off)", "",
             f"Seed for the withheld-word split: {G.SEED_SPLIT}. Generator seed 7. Run time {time.time() - t0:.0f}s. All figures are model off.", ""]
    lines += fmt("DEV (tuned on)", dev, f"Generated from the 70% of each concept's words the router has, with openers, closers and 28 noise transforms. The router was tuned on this set. Frozen set (`eval.frozen_set`, written before the overhaul): {fk}/{fn}.")
    lines += fmt("WORD-HELD-OUT (not tuned on)", held, "Generated only from the withheld 30% of each concept's words; those words are removed from `lexicon.py` while this set runs. "
                 "Other layers (keyword regexes, the similarity index) still see them, as in production.")
    if b:
        lines += fmt(f"BLIND (hash {bh})", b, "Written by people who have not seen the router. Read-only; run once per release candidate.")
    else:
        lines += ["### BLIND", "", f"Not run: {'no files in tests/data/blind yet' if not blind else 'pass --blind to run'}. The loader is `eval.phrase_generator.blind_items`; the protocol is in ROUTER_OVERHAUL.md 9.3.", ""]
    pathlib.Path(a.out).write_text("\n".join(lines), encoding="utf-8")
    pathlib.Path(a.out).with_suffix(".json").write_text(json.dumps({"dev": {k: v for k, v in dev.items() if k != "rows"}, "held": {k: v for k, v in held.items() if k != "rows"},
                                                                     "frozen": [fk, fn], "blind": (bh if b else None)}, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    print(f"DEV {dev['pass']}/{dev['n']} ({100 * dev['rate']:.1f}%) | HELD-OUT {held['pass']}/{held['n']} ({100 * held['rate']:.1f}%) | frozen {fk}/{fn} | "
          f"menu dev {100 * dev['menu_rate']:.2f}% held {100 * held['menu_rate']:.2f}% | dead {dev['dead'] + held['dead']} | money {dev['money'] + held['money']}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
