"""List every wrong answer on a held-out file with message, true intent, predicted intent and the layer that produced it. OFFLINE.

Layers: `keyword rule` (nlu.classify; the matching rule names are shown), `slot rule`, `similarity`, `arbitration`, `normalised`.
Run: OASIS_LLM=offline PYTHONPATH=. python -m eval.router_wrong [tests/data/router_heldout.json]
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

os.environ["OASIS_LLM"] = "offline"
from oasis.agent import nlu, robust  # noqa: E402

_NOISE = {"_NUMBER", "_WORD_AMT", "_FILLER", "_SPACED", "_B64", "_NEGATED", "_HAZAAR", "_INFO_CUE", "_PAY_CUE", "_CONDITIONAL_APPROVE", "CJK", "INVOICE_HINT", "_TYPO_MAP", "_URGENCY"}


def rules_matching(norm: str) -> list[str]:
    out = []
    for name, v in vars(nlu).items():
        if isinstance(v, re.Pattern) and name not in _NOISE and not name.startswith("_SECRET") and v.search(norm):
            out.append(name)
    return out


def label(text: str) -> tuple[str, str, str]:
    lab, src, _ = robust.route(text)
    if src == "router":
        it = nlu.classify(text)
        return lab, "keyword rule", ", ".join(rules_matching(nlu.normalise(text))[:5]) or it.kind
    return lab, {"slots": "slot rule", "similarity": "similarity", "arbitrated": "arbitration", "normalised": "keyword rule (normalised text)"}.get(src, src), ""


def main(path: str) -> int:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))["cases"]
    n = wrong = 0
    for c in cases:
        n += 1
        lab, layer, detail = label(c["text"])
        exp = "unknown" if c["expected"] == "other" else c["expected"]
        if lab not in (exp, "clarify", "unknown"):
            wrong += 1
            print(f"{c['text']!r} | true {c['expected']} | got {lab} | {layer}" + (f" [{detail}]" if detail else ""))
        elif c["expected"] == "other" and lab not in ("unknown", "clarify"):
            pass
    print(f"-- {wrong} wrong of {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "tests/data/router_heldout.json"))
