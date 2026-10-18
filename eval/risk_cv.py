"""Cross-validated flag rate of the risk model with the new deterministic features (riskscorerimp.md, section 2). No model call, no network.

    OASIS_LLM=offline PYTHONPATH=. python -m eval.risk_cv            # writes eval/reports/risk_cv.{md,json}
    OASIS_LLM=offline PYTHONPATH=. python -m eval.risk_cv --fit      # also retrains and ships oasis/agent/ml_risk_model.json

Pool: visible suite + fresh set + risk held-out set (the held-out set is now a DEV set: its misses were read to design features, so its 54% stays
the "before" number and is not a clean estimate any more). The synthetic corpus is always in the training half. Folds are by scenario id, so one
scenario never sits in both halves. Seeded; deterministic. The reported rate is out-of-fold, but features were designed after reading the
held-out misses, so it is still optimistic: only the sealed confirmation set (section 3) can confirm the number.
"""
from __future__ import annotations
import json
import os
import random
import sys
from collections import defaultdict

os.environ["OASIS_LLM"] = "offline"
from oasis.agent.ml_risk import MODEL_PATH, LogReg  # noqa: E402

from . import hidden  # noqa: E402
from .ml_risk_train import THRESHOLD, collect, synthetic  # noqa: E402
from .risk_heldout import PATH as HELDOUT, wilson  # noqa: E402
from .runner import REPORTS  # noqa: E402
from .scenarios import all_scenarios  # noqa: E402

FOLDS = 5
SEEDS = (3, 5, 9)


def _flags(rows, score):
    sc: dict[str, dict] = defaultdict(lambda: {"flag": False})
    for r in rows:
        d = sc[r["id"]]
        d["flag"] |= score(r) >= THRESHOLD
        d["y"], d["cat"] = r["y"], r["category"]
    return sc


def cv(pool, syn_rows, seed):
    ids = sorted({r["id"] for r in pool})
    random.Random(seed).shuffle(ids)
    out = {}
    for k in range(FOLDS):
        test_ids = set(ids[k::FOLDS])
        train = [r for r in pool if r["id"] not in test_ids] + syn_rows
        m = LogReg().fit([r["x"] for r in train], [r["y"] for r in train])
        test = [r for r in pool if r["id"] in test_ids]
        out.update(_flags(test, lambda r: max(r["rule"], m.prob(r["x"]))))
    return out


def main() -> int:
    pool = collect(all_scenarios()) + collect(hidden.load_scenarios(hidden.FRESH_PATH)) + collect(hidden.load_scenarios(HELDOUT))
    syn_rows = collect(synthetic())
    base = _flags(pool, lambda r: r["rule"])
    runs = [cv(pool, syn_rows, s) for s in SEEDS]
    atk = [i for i, d in runs[0].items() if d["y"]]
    leg = [i for i, d in runs[0].items() if not d["y"]]
    k = [sum(r[i]["flag"] for i in atk) for r in runs]
    fl = [sum(r[i]["flag"] for i in leg) for r in runs]
    n, nl = len(atk), len(leg)
    mk = round(sum(k) / len(k))
    lo, hi = wilson(mk, n)
    cats: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for i in atk:
        c = cats[runs[0][i]["cat"]]
        c[0] += 1
        c[1] += sum(r[i]["flag"] for r in runs) / len(runs)
    rule_k = sum(base[i]["flag"] for i in atk)
    L = ["# Risk model with the new deterministic features: cross-validated flag rate", "",
         f"Pool: visible suite + fresh set + risk held-out set = {n} attacks and {nl} legitimate scenarios (poisoned-tool and split-payment excluded). "
         f"{FOLDS}-fold CV by scenario id, {len(SEEDS)} shuffles, synthetic corpus always in the training half. Threshold {THRESHOLD}. Scorer = max(rules, model).", "",
         "The held-out set is a dev set here (its misses were read to design the features); features were designed after reading those misses, so this rate is "
         "optimistic. The 54% held-out figure stays the honest 'before' number. Only the sealed confirmation set can confirm the new rate.", "",
         "| Scorer | Attacks flagged | Rate (95% CI) | Legit flagged |", "|---|---|---|---|",
         f"| Rules only (hand-set, no training) | {rule_k}/{n} | {100 * rule_k / n:.0f}% ({100 * wilson(rule_k, n)[0]:.0f}-{100 * wilson(rule_k, n)[1]:.0f}%) | "
         f"{sum(base[i]['flag'] for i in leg)}/{nl} |",
         f"| Model + new features, out-of-fold (mean of {len(SEEDS)} shuffles: {', '.join(map(str, k))}) | {mk}/{n} | **{100 * mk / n:.0f}% ({100 * lo:.0f}-{100 * hi:.0f}%)** | "
         f"{round(sum(fl) / len(fl))}/{nl} (per shuffle: {', '.join(map(str, fl))}) |", "",
         "| Category | n | Flagged out-of-fold (mean) |", "|---|---|---|"]
    L += [f"| {c} | {v[0]} | {v[1]:.1f} |" for c, v in sorted(cats.items())]
    miss = sorted(i for i in atk if not all(r[i]["flag"] for r in runs))
    L += ["", "Attacks not flagged in every shuffle: " + (", ".join(f"`{i}` ({runs[0][i]['cat']})" for i in miss) or "none") + "."]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "risk_cv.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (REPORTS / "risk_cv.json").write_text(json.dumps({"attacks": n, "legit": nl, "flagged_per_shuffle": k, "legit_flagged_per_shuffle": fl, "rules_only": rule_k,
                                                      "ci95": [lo, hi], "threshold": THRESHOLD}, indent=1), encoding="utf-8")
    print("\n".join(L).encode("ascii", "replace").decode())
    if "--fit" in sys.argv:
        train = pool + syn_rows
        m = LogReg().fit([r["x"] for r in train], [r["y"] for r in train])
        meta = {"train_documents": len(train), "threshold": THRESHOLD, "features": len(m.w),
                "note": "retrained on visible + fresh + risk held-out + synthetic (riskscorerimp.md); the risk held-out set is no longer out of sample for this model"}
        MODEL_PATH.write_text(json.dumps({**m.to_json(), "meta": meta}, indent=1, sort_keys=True), encoding="utf-8")
        print("model written", MODEL_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
