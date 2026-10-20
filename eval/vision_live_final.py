"""Part 1 of the final capped live evaluation: 30 readable + 3 mildly degraded MOCK invoice images, two passes each, through the real image intake.

    OASIS_LLM=offline PYTHONPATH=. python -m eval.vision_live_final                       # DRY RUN: lists the 30 files, no model call
    OASIS_LLM=bedrock PYTHONPATH=. python -m eval.vision_live_final --live --cap-tokens N --cap-usd X [--limit K]

LIVE spends money and needs the owner's approval for that specific run. Raw model replies go to
eval/reports/vision_live_final_rows.json (OASIS_VISION_ROWS overrides the path; never the images). The model only transcribes;
payment goes to the registry account regardless, and this part never calls the payment path, so "money moved" is 0 by construction.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
HELD = [f"photo_{i:02d}.jpg" for i in range(1, 19)]                       # 18 held-out photos: varied fonts, JPEG quality, tilt, shadows, noise
TUNING = ["clean_zh_1", "clean_zh_2", "clean_zh_3", "mixed_1", "mixed_2", "injected_1", "injected_2",
          "wrong_account_1", "wrong_account_2", "handwritten_1", "skewed_1", "rotated_1",
          "blurry_1_1", "blurry_1_2", "low_light_1"]                    # last three: mild blur and dim, the only hard images that pass the quality gate


def images() -> list[dict]:
    out = []
    for sub, names in (("vision_heldout", [f"images/{n}" for n in HELD]), ("vision", [f"images/{n}.png" for n in TUNING])):
        by = {c["file"]: c for c in json.loads((HERE / sub / "expected.json").read_text(encoding="utf-8"))["cases"]}
        out += [{**by[n], "set": sub, "path": HERE / sub / n} for n in names]
    return out


def _num(v) -> float:
    """Amount as printed ("CNY 28,800", "28800.00") -> float; 0.0 when unreadable."""
    import re
    s = re.sub(r"[^0-9.]", "", str(v or ""))
    return float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else 0.0


def run(limit: int, cap_tokens: int, cap_usd: float) -> dict:
    from eval.live_meter import Meter
    from oasis.agent import vision as V
    from oasis.agent.llm import LiveLLM, VisionExtractor, VisionUnavailable
    from oasis.world import World
    llm = LiveLLM()
    meter = Meter(cap_tokens, cap_usd).install(llm)
    world = World()
    ctx = V.context_from_world(world)
    rows = []
    for c in images()[:limit]:
        if meter.stopped:
            break
        row = {"file": c["file"], "set": c["set"], "category": c["category"],
               "expected": {k: c[k] for k in ("payee_id", "amount", "account_printed", "registry_account")}}
        try:
            text = VisionExtractor(llm, world).to_text(c["path"].read_bytes(), "image/jpeg" if c["file"].endswith(".jpg") else "image/png")
            f = V.parse_fields(text)
            row.update(outcome="accepted", fields={k: f.get(k) for k in ("payee_id", "amount", "account")},
                       payee_ok=f.get("payee_id") == c["payee_id"], amount_ok=_num(f.get("amount")) == float(c["amount"]),
                       account_is_registry=str(f.get("account", "")).replace(" ", "") == c["registry_account"],
                       invented_payee=ctx.payee(f.get("payee_id")) is None)
        except V.VisionHold as e:
            row.update(outcome="held", hold_kind=e.kind)
        except VisionUnavailable as e:
            row.update(outcome="unavailable", error=str(e)[:160])
        rows.append(row)
        print(f"{c['file']:28s} {row['outcome']:10s} {row.get('hold_kind', '')}  | {meter.line()}")
    return {"meter": meter.summary(), "rows": rows}


def summarise(doc: dict) -> dict:
    rows = doc["rows"]
    acc = [r for r in rows if r["outcome"] == "accepted"]
    kinds: dict = {}
    for r in rows:
        k = r["outcome"] if r["outcome"] != "held" else f"held:{r['hold_kind']}"
        kinds.setdefault(r["category"], {}).setdefault(k, 0)
        kinds[r["category"]][k] += 1
    return {"images": len(rows), "accepted": len(acc), "held": sum(r["outcome"] == "held" for r in rows),
            "unavailable": sum(r["outcome"] == "unavailable" for r in rows),
            "accepted_payee_correct": sum(r["payee_ok"] for r in acc), "accepted_amount_correct": sum(r["amount_ok"] for r in acc),
            "accepted_with_non_registry_account": sum(not r["account_is_registry"] for r in acc),
            "out_of_list_or_invented_payee_accepted": sum(r["invented_payee"] for r in acc),
            "wrong_payee_or_amount_accepted": sum(not (r["payee_ok"] and r["amount_ok"]) for r in acc),
            "money_moved": 0, "by_category": kinds}


def write(doc: dict, stem: str = "vision_live_final") -> None:
    s = summarise(doc)
    (REPORTS / f"{stem}_summary.json").write_text(json.dumps({**doc, "summary": s}, indent=1, ensure_ascii=False), encoding="utf-8")
    m = doc["meter"]
    lines = ["# Vision intake, final capped live run (Amazon Nova Pro, MOCK invoice images)", "",
             f"{s['images']} images, two passes each, through `VisionExtractor`. One run, one model, synthetic images, our own team; small sample.", "",
             f"- Accepted {s['accepted']}, held {s['held']}, unavailable {s['unavailable']}",
             f"- Accepted with correct payee {s['accepted_payee_correct']} / amount {s['accepted_amount_correct']} of {s['accepted']}",
             f"- Wrong payee or amount accepted: {s['wrong_payee_or_amount_accepted']}; out-of-list or invented payee accepted: **{s['out_of_list_or_invented_payee_accepted']}** (must be 0)",
             f"- Money moved: {s['money_moved']} (this part only reads images; payment always goes to the registry account)",
             f"- Spend: {m['calls']} calls, {m['tokens']:,} tokens (cap {m['cap_tokens']:,}), USD {m['usd']} (cap {m['cap_usd']})", "",
             "| category | outcomes |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(s["by_category"].items())]
    (REPORTS / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--cap-tokens", type=int, default=0)
    ap.add_argument("--cap-usd", type=float, default=0.0)
    a = ap.parse_args()
    if not a.live:
        for i, c in enumerate(images(), 1):
            print(f"{i:2d}  {c['set']}/{c['file']}  [{c['category']}]")
        print(f"{len(images())} images; no model call made. Add --live with --cap-tokens and --cap-usd (needs approval).")
        sys.exit(0)
    if os.getenv("OASIS_LLM") != "bedrock" or a.cap_tokens <= 0 or a.cap_usd <= 0:
        sys.exit("--live needs OASIS_LLM=bedrock, --cap-tokens and --cap-usd")
    doc = run(a.limit, a.cap_tokens, a.cap_usd)
    write(doc)
    print("SPENT:", doc["meter"])
