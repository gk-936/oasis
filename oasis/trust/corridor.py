"""Corridor rules engine: data-driven (YAML) checks for the INR -> CNY corridor."""
from __future__ import annotations
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from ..config import RULES_DIR
from ..passport.models import Passport


@lru_cache(maxsize=4)
def load_rules(name: str = "inr_cny.yaml") -> dict:
    return yaml.safe_load((RULES_DIR / name).read_text(encoding="utf-8"))


@dataclass
class Finding:
    rule: str
    severity: str  # info | warn | hold
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class CorridorResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def holds(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "hold"]

    @property
    def warns(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]

    def to_dict(self) -> dict:
        return {"findings": [f.__dict__ for f in self.findings]}


USD_INR = 88.0  # MOCK reference rate for limit arithmetic


def tcs_amount(passport: Passport, remitter: str, amount_inr: float, purpose: str, rules: dict) -> float:
    if passport.funding_source == "education_loan":
        return 0.0
    t = rules["rules"]["tcs_threshold_inr"]
    already = passport.remitted_inr_fy.get(remitter, 0.0)
    over = max(0.0, already + amount_inr - t["value"]) - max(0.0, already - t["value"])
    return round(over * t["rate_above"], 2)


def check(passport: Passport, *, payee_type: str, purpose: str, amount_cny: float, amount_inr: float,
          remitter: str = "student", history: list[dict] | None = None, payee_id: str = "",
          now_ts: float = 0.0) -> CorridorResult:
    rules = load_rules()
    r = rules["rules"]
    res = CorridorResult()

    allowed = rules["purpose_payee_types"].get(purpose)
    if allowed is not None and payee_type not in allowed:
        res.findings.append(Finding("purpose_payee_mismatch", "hold",
                                    f"Purpose '{purpose}' does not fit payee type '{payee_type}'."))

    lrs_inr = r["lrs_annual_limit_usd"]["value"] * USD_INR
    used = passport.remitted_inr_fy.get(remitter, 0.0)
    if used + amount_inr > lrs_inr:
        res.findings.append(Finding("lrs_limit", "hold",
                                    f"The {remitter} remitter's LRS limit would be exceeded this financial year.",
                                    {"used_inr": used, "limit_inr": lrs_inr}))

    tcs = tcs_amount(passport, remitter, amount_inr, purpose, rules)
    if tcs > 0:
        res.findings.append(Finding("tcs", "warn",
                                    f"TCS of INR {tcs:,.0f} would be collected (recoverable as a tax credit).",
                                    {"tcs_inr": tcs}))
    elif used + amount_inr > r["tcs_threshold_inr"]["value"] * 0.8 and passport.funding_source != "education_loan":
        res.findings.append(Finding("tcs_near", "info",
                                    "Approaching the INR 10 lakh TCS threshold for this remitter."))

    safe_inr = r["safe_quota_usd"]["value"] * USD_INR
    if amount_inr > safe_inr:
        res.findings.append(Finding("safe_quota", "warn",
                                    "Conversion exceeds the annual SAFE facilitation quota; stage it or prepare documents."))

    if purpose == "tuition":
        res.findings.append(Finding("purpose_code", "info",
                                    f"Report under education purpose code {r['purpose_code_education']['value']} "
                                    f"(unconfirmed - verify with the authorised dealer bank)."))

    res.findings.extend(split_flags(passport, payee_id, amount_cny, amount_inr, history or [], now_ts,
                                    r["split_pattern"]))
    return res


def split_flags(passport: Passport, payee_id: str, amount_cny: float, amount_inr: float,
                history: list[dict], now_ts: float, cfg: dict) -> list[Finding]:
    """Payments clustered just under an approval threshold within a window."""
    out: list[Finding] = []
    window = cfg["window_hours"] * 3600
    ratio = cfg["near_limit_ratio"]
    recent = [h for h in history if h["payee_id"] == payee_id and now_ts - h["ts"] <= window]
    for label, threshold, key, val in (
            ("tier1_auto_limit_cny", passport.rules.tier1_auto_limit_cny, "amount_cny", amount_cny),
            ("parent_coapproval_above_inr", passport.rules.parent_coapproval_above_inr, "amount_inr", amount_inr)):
        near = [h for h in recent if ratio * threshold <= h.get(key, 0) <= threshold]
        if ratio * threshold <= val <= threshold and len(near) + 1 >= cfg["min_payments"]:
            out.append(Finding("split_payments", "hold",
                               f"{len(near)+1} payments to the same payee just under the {label} within "
                               f"{cfg['window_hours']}h look like splitting to dodge approval.",
                               {"threshold": threshold}))
    return out
