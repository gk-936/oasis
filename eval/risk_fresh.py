"""Out-of-sample check of the risk scorers on the FRESH attack set, plus a cross-validation of the trained model on its own
training distribution. No model call, no network.

    OASIS_LLM=offline PYTHONPATH=. python -m eval.risk_fresh     # writes eval/reports/risk_fresh.md

The shipped weights (`oasis/agent/risk_model.json`) are NOT retrained here and the fresh set is not used to choose anything: it is
the first time these scorers see it. Cross-validation uses the team-written training corpus only, so it shows how stable the
fit is, not how well it generalises to attacks nobody on the team imagined (the fresh set is for that)."""
from __future__ import annotations
import random
import sys
from collections import defaultdict

from oasis.agent.ml_risk import LogReg, MLRisk

from .hidden import FRESH_PATH, file_sha256, load_scenarios
from .ml_risk_train import THRESHOLD, auc, collect, rates, synthetic
from .runner import REPORTS
from .scenarios import all_scenarios

FOLDS = 5


def cv_auc(rows: list[dict], seed: int = 3) -> tuple[float, float]:
    """Mean and spread of the model's AUC over FOLDS folds, split by scenario so one scenario never sits in both halves."""
    ids = sorted({r["id"] for r in rows})
    random.Random(seed).shuffle(ids)
    scores = []
    for k in range(FOLDS):
        test_ids = set(ids[k::FOLDS])
        tr = [r for r in rows if r["id"] not in test_ids]
        te = [r for r in rows if r["id"] in test_ids]
        m = LogReg().fit([r["x"] for r in tr], [r["y"] for r in tr])
        a = auc([(m.prob(r["x"]), r["y"]) for r in te])
        if a is not None:
            scores.append(a)
    mean = sum(scores) / len(scores)
    return mean, (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5


def main() -> int:
    ml = MLRisk()
    if not ml.available:
        print("no shipped risk model found; run python -m eval.ml_risk_train first", file=sys.stderr)
        return 1
    fresh_rows = collect(load_scenarios(FRESH_PATH))
    rule = lambda r: r["rule"]                                  # noqa: E731
    mlf = lambda r: ml.model.prob(r["x"])                       # noqa: E731
    comb = lambda r: max(r["rule"], ml.model.prob(r["x"]))      # noqa: E731
    res = {n: rates(fresh_rows, f) for n, f in (("Rules (hand-set)", rule), ("Trained model", mlf), ("Combined (max)", comb))}
    train_rows = collect(all_scenarios()) + collect(synthetic())
    cv_mean, cv_sd = cv_auc(train_rows)
    a = lambda v: "n/a" if v is None else f"{v:.3f}"            # noqa: E731
    cats: dict[str, list] = defaultdict(lambda: [0, 0, 0])
    for sid, d in res["Rules (hand-set)"]["by_category"].items():
        if d["y"]:
            c = cats[d["category"]]
            c[0] += 1
            c[1] += d["flag"]
            c[2] += res["Trained model"]["by_category"][sid]["flag"]
    L = ["# Risk scorers on the fresh attack set (out of sample)", "",
         f"Fresh set: `eval/fresh/scenarios_fresh.json` (sha256 `{file_sha256(FRESH_PATH)}`); the shipped model was trained before this set existed and "
         f"is unchanged. Threshold {THRESHOLD}; a scenario is flagged if ANY of its documents reaches it. Poisoned-tool cases are excluded (their text is innocent).", "",
         "| Scorer | Attacks flagged | Legit flagged | AUC |", "|---|---|---|---|"]
    for n, r in res.items():
        L.append(f"| {n} | {r['attack_flagged']}/{r['attacks']} | {r['legit_flagged']}/{r['legit']} | {a(r['auc'])} |")
    L += ["", f"Cross-validation of the model on its own training corpus ({FOLDS} folds split by scenario): AUC {cv_mean:.3f} +/- {cv_sd:.3f}. "
          "The corpus was written by the team, so this measures stability, not generalisation.", "",
          "## Fresh attacks by category (flagged by rules / by model, of n)", "", "| Category | n | Rules | Model |", "|---|---|---|---|"]
    L += [f"| {k} | {n} | {r} | {m} |" for k, (n, r, m) in sorted(cats.items())]
    L += ["", "## Reading this", "",
          "- The scorers only ever ESCALATE a decision. What stops an attack that the text scorers miss is the registry check, the policy engine and the signed intent "
          "(see `benchmark_fresh.md`); the scorer is a second opinion on the wording.",
          "- 49 cases, written by an AI assistant that had read parts of the defence code: fresh, not blind. One case more or less moves a rate by about 3 points.", ""]
    (REPORTS / "risk_fresh.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L).encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
