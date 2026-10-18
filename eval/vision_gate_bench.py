"""Offline benchmark of the two-level image-intake quality gate on the generated MOCK invoices: the 40 tuning images (eval/vision/)
and the 30 held-out images (eval/vision_heldout/), reported separately.

No model is called. A scripted "oracle" that returns each image's printed fields stands in for the model, to check the rest of the
chain (gate -> preprocess -> parse -> validate -> two passes). That says nothing about how well the real model reads these images.
Run: OASIS_LLM=offline python -m eval.vision_gate_bench
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from oasis.agent import vision as V
from oasis.agent.vision import VisionHold
from oasis.world import World

REPORTS = Path(__file__).parent / "reports"
SETS = {"vision": ("eval/vision (40 tuning images)", "vision_gate"), "vision_heldout": ("eval/vision_heldout (30 held-out images)", "vision_heldout_gate")}
SKEW_DEG = {"skewed_1": 3, "skewed_2": -4, "skewed_3": 6, "skewed_4": -7}


def oracle_for(case: dict):
    def chat(system, user, image):
        return (f"Payee ID: {case['payee_id']}\nAccount: {case['account_printed']}\nAmount: {case['amount']}\n"
                f"Purpose: {case['purpose']}\nDue: {case['due']}")
    return chat


def run_set(name: str) -> dict:
    vdir = Path(__file__).parent / name
    title, stem = SETS[name]
    cases = json.loads((vdir / "expected.json").read_text(encoding="utf-8"))["cases"]
    ctx = V.context_from_world(World())
    rows = []
    for c in cases:
        data = (vdir / c["file"]).read_bytes()
        img = V.open_image(data)
        hard, soft, m = V.quality_gate(img)
        verdict = "hold" if hard else "borderline" if soft else "pass"
        row = {"image": Path(c["file"]).stem, "category": c["category"], "expected": c["gate"], "verdict": verdict,
               **{k: m[k] for k in ("width", "height", "blur", "brightness", "contrast")}, "reasons": hard + soft}
        if verdict != "hold":
            row["skew_estimate_deg"] = round(V.estimate_skew(img.convert("L")), 2)
            try:
                text, info = V.read_invoice(data, oracle_for(c), ctx)
                row["oracle_chain"] = "accepted" + (" (2 passes forced)" if info["borderline"] else "")
            except VisionHold as e:
                row["oracle_chain"] = f"held ({e.kind})"
        else:
            row["oracle_chain"] = "model not called"
        rows.append(row)
    n = len(rows)
    readable = [r for r in rows if r["expected"] == "pass"]
    unusable = [r for r in rows if r["expected"] == "hold"]
    summary = {"set": name, "images": n, "readable": len(readable), "unusable_controls": len(unusable),
               "readable_hard_held": sum(r["verdict"] == "hold" for r in readable),
               "readable_borderline": sum(r["verdict"] == "borderline" for r in readable),
               "unusable_hard_held": sum(r["verdict"] == "hold" for r in unusable),
               "unusable_sent_to_model": sum(r["verdict"] != "hold" for r in unusable),
               "oracle_accepted": sum(r["oracle_chain"].startswith("accepted") for r in rows),
               "thresholds": {"hard_resolution": [V.HARD_LONG_SIDE, V.HARD_SHORT_SIDE], "soft_resolution": [V.SOFT_LONG_SIDE, V.SOFT_SHORT_SIDE],
                              "blur": [V.HARD_BLUR, V.SOFT_BLUR], "brightness": [V.HARD_BRIGHT_MIN, V.SOFT_BRIGHT_MIN, V.SOFT_BRIGHT_MAX, V.HARD_BRIGHT_MAX],
                              "contrast": [V.HARD_CONTRAST, V.SOFT_CONTRAST]}}
    skew_err = [abs(r["skew_estimate_deg"] + SKEW_DEG[r["image"]]) for r in rows if r["image"] in SKEW_DEG and "skew_estimate_deg" in r]
    if skew_err:
        summary["mean_abs_skew_error_deg"] = round(sum(skew_err) / len(skew_err), 2)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"{stem}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    tuned = name == "vision"
    lines = [f"# Image-intake quality gate, two levels: {title}", "",
             "Generated MOCK invoices; no model was called. `hold` = clearly unusable (no model call), `borderline` = goes to the model with the "
             "two-pass check forced, `pass` = normal. " + ("The thresholds were set on THESE images, so the figures below are a fit, not a "
             "held-out result." if tuned else "These images were generated after the thresholds were fixed and were not used to set them."), "",
             f"- Readable invoices: {summary['readable']}; **hard-held: {summary['readable_hard_held']}**; borderline (sent to the model): {summary['readable_borderline']}",
             f"- Unusable controls: {summary['unusable_controls']}; hard-held: {summary['unusable_hard_held']}; sent to the model: {summary['unusable_sent_to_model']}",
             f"- Scripted oracle (returns each image's printed fields, not a model) accepted by the full chain: {summary['oracle_accepted']}",
             f"- Thresholds (hard, soft): {json.dumps(summary['thresholds'])}", "",
             "| image | expected | verdict | size | blur | brightness | contrast | chain |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['image']} | {r['expected']} | {r['verdict']} | {r['width']}x{r['height']} | {r['blur']} | {r['brightness']} | "
                     f"{r['contrast']} | {r['oracle_chain']} |")
    (REPORTS / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> list[dict]:
    out = [run_set(n) for n in SETS if (Path(__file__).parent / n / "expected.json").exists()]
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
