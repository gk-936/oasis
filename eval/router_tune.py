"""Tune the similarity thresholds (robust.ACCEPT / robust.MARGIN) by leave-one-out on intent_examples.TRAIN only.

The held-out file (tests/data/router_heldout.json) is never read here. Offline, no model call.
Run: OASIS_LLM=offline PYTHONPATH=. python -m eval.router_tune
"""
from __future__ import annotations
import os

os.environ["OASIS_LLM"] = "offline"
from oasis.agent import robust  # noqa: E402
from oasis.agent.intent_examples import TRAIN  # noqa: E402


def loo() -> list[tuple[str, list[tuple[str, float]]]]:
    idx = robust.index()
    rows, i = [], 0
    for lab, ts in TRAIN.items():
        for t in ts:
            rows.append((lab, idx.scores(t, skip=i)))
            i += 1
    return rows


def sweep(rows, max_wrong: float = 0.02):
    best = None
    n = len(rows)
    for a in [x / 100 for x in range(2, 50)]:
        for m in [x / 100 for x in range(0, 16)]:
            ok = bad = 0
            for lab, ranked in rows:
                d = robust.decide(ranked, a, m)
                if d is None:
                    continue
                ok += d == lab
                bad += d != lab
            if bad / n <= max_wrong and (best is None or ok > best[2]):
                best = (a, m, ok, bad)
    return best, n


if __name__ == "__main__":
    rows = loo()
    for a, m in [(0.0, 0.0), (robust.ACCEPT, robust.MARGIN)]:
        ok = sum(robust.decide(r, a, m) == lab for lab, r in rows)
        bad = sum(robust.decide(r, a, m) not in (None, lab) for lab, r in rows)
        print(f"accept={a} margin={m}: correct {ok}/{len(rows)} wrong {bad} abstain {len(rows) - ok - bad}")
    print("best (accept, margin, correct, wrong) with wrong <= 2%:", sweep(rows))


def _cached():
    """Train phrases, similarity by leave-one-out, keyword classification and similarity cached so a grid of settings is quick."""
    import functools
    from oasis.agent import nlu
    idx = robust.index()
    flat = [(lab, t) for lab, ts in TRAIN.items() for t in ts]
    pos = {t: i for i, (_, t) in enumerate(flat)}
    orig = idx.scores
    loo_scores = functools.lru_cache(maxsize=None)(lambda text: orig(text, skip=pos.get(text)))
    idx.scores = lambda text, skip=None: loo_scores(text)
    nlu.classify = functools.lru_cache(maxsize=None)(nlu.classify)
    robust.nlu.classify = nlu.classify
    return flat


def outcome(expected: str, label: str) -> str:
    if expected == "other":
        return "right" if label == "unknown" else ("clarified" if label == "clarify" else "wrong")
    return "right" if label == expected else ("clarified" if label == "clarify" else ("none" if label == "unknown" else "wrong"))


def measure(flat) -> dict:
    out = {"right": 0, "wrong": 0, "clarified": 0, "none": 0}
    for lab, t in flat:
        out[outcome(lab, robust.route(t)[0])] += 1
    return out


def pairs() -> None:
    """The label pairs the train phrases get mixed up (pipeline wrong answers and similarity top-1 errors): the source of robust.CONFUSABLE."""
    import collections
    flat = _cached()
    wrong, top1 = collections.Counter(), collections.Counter()
    for lab, t in flat:
        got = robust.route(t)[0]
        if outcome(lab, got) == "wrong":
            wrong[frozenset((lab, got))] += 1
        r = robust.similar(t)
        if r[0][0] != lab:
            top1[frozenset((lab, r[0][0]))] += 1
    print("pipeline wrong pairs:", [(sorted(k), v) for k, v in wrong.most_common(20)])
    print("similarity top-1 error pairs:", [(sorted(k), v) for k, v in top1.most_common(20)])


def pipeline_grid() -> None:
    """Joint tuning on the TRAIN phrases only (the held-out file is never read). Picks the setting with the most right answers among those with
    wrong <= 4% and right + clarified >= 85%; prints every setting tried so the trade-off can be tabulated."""
    import itertools
    flat = _cached()
    n = len(flat)
    best = None
    for acc, mar, conf, aa, am, pa, pm in itertools.product((0.22, 0.27), (0.08,), (9.0,), (0.0, 0.04, 0.08, 0.12), (0.0, 0.04, 0.08), (0.04, 0.08), (0.0, 0.04)):
        robust.ACCEPT, robust.MARGIN, robust.CONFUSE_MARGIN, robust.ARB_ACCEPT, robust.ARB_MARGIN, robust.PAY_ACCEPT, robust.PAY_MARGIN = acc, mar, conf, aa, am, pa, pm
        m = measure(flat)
        ok = m["wrong"] / n <= 0.04 and (m["right"] + m["clarified"]) / n >= 0.85
        print(f"ACCEPT={acc} MARGIN={mar} CONFUSE={conf} ARB={aa}/{am} PAY={pa}/{pm}: right {m['right']} wrong {m['wrong']} clarified {m['clarified']} none {m['none']} {'OK' if ok else ''}", flush=True)
        key = (ok, m["right"] if ok else -m["wrong"], m["right"] + m["clarified"])
        if best is None or key > best[0]:
            best = (key, (acc, mar, conf, aa, am, pa, pm), m)
    print("BEST", best, "of", n)


if __name__ == "__main__" and os.environ.get("ROUTER_TUNE_GRID") == "1":
    pipeline_grid()
if __name__ == "__main__" and os.environ.get("ROUTER_TUNE_PAIRS") == "1":
    pairs()


def tradeoff() -> None:
    """The threshold trade-off as a table: settings chosen on the TRAIN phrases (leave-one-out), with the held-out outcome shown beside them.
    The held-out file is only READ here to report; no setting is selected from it. Writes eval/reports/router_tradeoff.md."""
    import json
    from pathlib import Path
    flat = _cached()
    held = json.loads((Path(__file__).resolve().parents[1] / "tests" / "data" / "router_heldout.json").read_text(encoding="utf-8"))["cases"]
    base = (robust.ACCEPT, robust.MARGIN, robust.CONFUSE_MARGIN, robust.ARB_ACCEPT, robust.ARB_MARGIN, robust.PAY_ACCEPT, robust.PAY_MARGIN)
    rows = []
    for name, acc, mar, conf, aa, am in (
            ("no pair rule, answer at 0.12", 0.12, 0.05, 0.0, 9.0, 0.12), ("pair rule on, answer at 0.12", 0.12, 0.05, 9.0, 9.0, 0.12),
            ("**shipped:** pair rule on, answer at 0.17", 0.17, 0.08, 9.0, 9.0, 0.12), ("pair rule on, answer at 0.22", 0.22, 0.08, 9.0, 9.0, 0.12),
            ("pair rule on, answer at 0.27", 0.27, 0.08, 9.0, 9.0, 0.12), ("pair rule on, answer at 0.32", 0.32, 0.08, 9.0, 9.0, 0.12),
            ("+ keyword answers in doubt at 0.25 / 0.12", 0.22, 0.08, 9.0, 0.25, 0.12), ("+ keyword answers in doubt at 0.17 / 0.12", 0.22, 0.08, 9.0, 0.17, 0.12),
            ("+ keyword answers in doubt at 0.0 (any disagreement)", 0.22, 0.08, 9.0, 0.0, 0.0)):
        robust.ACCEPT, robust.MARGIN, robust.CONFUSE_MARGIN, robust.ARB_ACCEPT, robust.ARB_MARGIN = acc, mar, conf, aa, am
        tr = measure(flat)
        ho = {"right": 0, "wrong": 0, "clarified": 0, "none": 0}
        for c in held:
            ho[outcome(c["expected"], robust.route(c["text"])[0])] += 1
        rows.append((name, tr, ho))
    robust.ACCEPT, robust.MARGIN, robust.CONFUSE_MARGIN, robust.ARB_ACCEPT, robust.ARB_MARGIN, robust.PAY_ACCEPT, robust.PAY_MARGIN = base
    nt, nh = len(flat), len(held)
    L = ["# Router thresholds: trade-off table (offline)", "",
         f"Train = leave-one-out over the {nt} train phrases (what the thresholds are chosen on). Held-out = the {nh} phrases the matcher never reads (reported, never selected on).",
         "Percentages of the set. 'none' = no intent claimed (correct for chit-chat). Targets that were asked for: wrong <= 5% and right + clarified >= 85% on held-out.", "",
         "| Setting | train right | train wrong | train clarified | train none | held-out right | held-out wrong | held-out clarified | held-out none |", "|---|---|---|---|---|---|---|---|---|"]
    for name, tr, ho in rows:
        p = lambda d, k, n: f"{d[k]} ({100 * d[k] / n:.0f}%)"
        L.append(f"| {name} | {p(tr, 'right', nt)} | {p(tr, 'wrong', nt)} | {p(tr, 'clarified', nt)} | {p(tr, 'none', nt)} | {p(ho, 'right', nh)} | {p(ho, 'wrong', nh)} | {p(ho, 'clarified', nh)} | {p(ho, 'none', nh)} |")
    out = Path(__file__).resolve().parent / "reports" / "router_tradeoff.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__" and os.environ.get("ROUTER_TUNE_TABLE") == "1":
    tradeoff()
