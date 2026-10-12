"""A small TRAINED fraud-risk model (logistic regression, pure Python, no extra dependency) that sits next to the rule scorer.

What it is: the rule scorer (`heuristic_risk`) has hand-set weights combined by a noisy-OR. This model learns its weights from
labelled documents instead, and also reads the wording itself (hashed word features), which the rules only touch through a
short keyword list. Its weights ship as a small JSON file (`ml_risk_model.json`) so any score can be explained feature by
feature: `explain()` returns the strongest contributions.

What it is not: a decision-maker. Like the LLM scorer it can only ESCALATE (`combined = max(rule score, model score)`), the
policy engine and the executor still decide, and it is OFF unless OASIS_ML_RISK=1. Training data, split and the measured
result are in `eval/ml_risk_train.py` and `eval/reports/ml_risk.md`; read those caveats before quoting a number.
"""
from __future__ import annotations
import hashlib
import json
import math
import random
import re
import unicodedata
from pathlib import Path

from .llm import heuristic_risk

MODEL_PATH = Path(__file__).with_name("ml_risk_model.json")
BUCKETS = 256
# Indicator -> the substring of a rule-scorer evidence line that raises it. The rules stay the single source of truth for what
# counts as a warning sign; the model learns how much each sign is worth.
_EVIDENCE_KEYS = {
    "rule_urgency": "urgency/pressure", "rule_injection": "instructions addressed", "rule_isolation": "not to contact",
    "rule_invisible": "invisible (zero-width)", "rule_fullwidth": "full-width", "rule_lookalike_letters": "look-alike (non-ASCII)",
    "rule_name_close": "closely resembles", "rule_name_partial": "partly matches", "rule_registry_unknown": "not found in the independent",
    "rule_registry_conflict": "contradicts the independent", "rule_account_differs": "differ from the account on file",
    "rule_amount_off": "differs from the expected obligation", "rule_new_payee": "new to this student",
    "rule_near_threshold": "just under", "rule_splitting": "possible splitting",
}
_WORD = re.compile(r"[\w一-鿿]+", re.U)
_ZW = re.compile("[​-‏‪-‮⁠-⁤﻿]")


def _bucket(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big") % BUCKETS


def featurize(fields: dict, text: str, known_names: list[str], known_accounts: dict[str, str],
              expected_amount: float | None, ctx: dict | None = None) -> dict[str, float]:
    """Sparse feature dict: the rule scorer's indicators, its own score, a few text-shape numbers and hashed words."""
    h = heuristic_risk(fields, text, known_names, known_accounts, expected_amount, ctx)
    f: dict[str, float] = {"rule_score": h.score}
    for name, key in _EVIDENCE_KEYS.items():
        if any(key in e for e in h.evidence):
            f[name] = 1.0
    n = max(1, len(text))
    f["shape_nonascii"] = sum(ord(c) > 127 for c in text) / n
    f["shape_zero_width"] = min(3, len(_ZW.findall(text))) / 3
    f["shape_long"] = min(1.0, len(text) / 2000)
    f["shape_exclaim"] = min(1.0, text.count("!") / 3)
    f["shape_upper"] = sum(c.isupper() for c in text) / n
    f["shape_markup"] = 1.0 if re.search(r"<!--|<span|<div|```|\[\[", text) else 0.0
    toks = [t.casefold() for t in _WORD.findall(unicodedata.normalize("NFKC", text))]
    seen: dict[int, int] = {}
    for t in toks:
        if t.isdigit() and len(t) > 3:
            continue                     # account / amount digits are not wording
        seen[_bucket("w:" + t)] = 1
    for b in seen:
        f[f"w{b}"] = 1.0 / math.sqrt(max(1, len(seen)))
    return f


class LogReg:
    def __init__(self, weights: dict[str, float] | None = None, bias: float = 0.0):
        self.w, self.b = dict(weights or {}), bias

    def logit(self, x: dict[str, float]) -> float:
        return self.b + sum(self.w.get(k, 0.0) * v for k, v in x.items())

    def prob(self, x: dict[str, float]) -> float:
        z = self.logit(x)
        return 1 / (1 + math.exp(-z)) if z > -60 else 0.0

    def fit(self, X: list[dict[str, float]], y: list[int], epochs: int = 300, lr: float = 0.3, l2: float = 1e-3,
            seed: int = 7, balance: bool = True) -> "LogReg":
        """Full-batch gradient descent with L2 and class balancing; deterministic for a given seed and data order."""
        rng = random.Random(seed)
        pos = sum(y) or 1
        neg = (len(y) - sum(y)) or 1
        cw = {1: len(y) / (2 * pos), 0: len(y) / (2 * neg)} if balance else {0: 1.0, 1: 1.0}
        keys = sorted({k for x in X for k in x})
        self.w = {k: rng.uniform(-0.01, 0.01) for k in keys}
        self.b = 0.0
        n = len(X)
        for _ in range(epochs):
            gw = {k: 0.0 for k in keys}
            gb = 0.0
            for x, t in zip(X, y):
                e = (self.prob(x) - t) * cw[t]
                gb += e
                for k, v in x.items():
                    gw[k] += e * v
            self.b -= lr * gb / n
            for k in keys:
                self.w[k] -= lr * (gw[k] / n + l2 * self.w[k])
        return self

    def to_json(self) -> dict:
        return {"bias": round(self.b, 6), "weights": {k: round(v, 6) for k, v in sorted(self.w.items()) if abs(v) > 1e-4}}

    @classmethod
    def from_json(cls, d: dict) -> "LogReg":
        return cls(d.get("weights", {}), float(d.get("bias", 0.0)))


class MLRisk:
    """Loads the shipped weights; `score` returns (probability, top contributing features)."""

    def __init__(self, path: Path | None = None):
        self.path = path or MODEL_PATH
        self.model: LogReg | None = None
        self.meta: dict = {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.model, self.meta = LogReg.from_json(d), d.get("meta", {})
        except (OSError, ValueError):
            pass

    @property
    def available(self) -> bool:
        return self.model is not None

    def score(self, fields, text, known_names, known_accounts, expected_amount, ctx=None, top: int = 4):
        x = featurize(fields, text, known_names, known_accounts, expected_amount, ctx)
        p = self.model.prob(x)
        contrib = sorted(((self.model.w.get(k, 0.0) * v, k) for k, v in x.items() if k in self.model.w), reverse=True)
        names = [(c, k) for c, k in contrib if c > 0.15 and not k.startswith("w")][:top]
        words = [k for c, k in contrib if c > 0.15 and k.startswith("w")][:2]
        why = [f"{k.replace('rule_', '').replace('shape_', '').replace('_', ' ')} (+{c:.1f})" for c, k in names]
        if words:
            why.append("wording typical of fraud")
        return p, why
