"""Corridor rules engine: data-driven (YAML) checks for the INR -> CNY corridor."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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


def tcs_rate(passport: Passport, purpose: str, rules: dict) -> dict:
    """TCS rate for a purpose, from the data file: {"rate", "status" (see STATUSES), "category", "threshold_inr"}."""
    table = rules["rules"]["tcs_by_purpose"]
    category = rules.get("purpose_tcs_category", {}).get(purpose, "other")
    if category == "education" and passport.funding_source == "education_loan":
        category_row = "education_loan"
    else:
        category_row = category
    row = table[category_row]
    return {"rate": row["rate"], "status": row["status"], "category": category_row, "threshold_inr": table["threshold_inr"]}


STATUSES = ("confirmed-primary", "researched-secondary", "unconfirmed")


def tcs_caveat(tr: dict) -> str:
    """Text appended to a TCS message unless the rate was read from a primary source (none of the TCS rows was)."""
    if tr["status"] == "confirmed-primary":
        return ""
    return (f" The {tr['rate']:.0%} rate for this purpose is UNCONFIRMED/secondary-sourced (status: {tr['status']}): "
            f"confirm it with the authorised dealer bank.")


def rules_public(name: str = "inr_cny.yaml") -> dict:
    """Every rule with its value, source, retrieval date, confidence and status, for the API and the UI. Read-only view of the
    data file; flattens the per-purpose TCS rows. Not legal advice."""
    data = load_rules(name)
    out: list[dict] = []

    def add(rule_id: str, row: dict, label: str) -> None:
        values = {k: v for k, v in row.items() if k not in ("source", "retrieved", "confidence", "status", "kind", "description", "action")}
        out.append({"id": rule_id, "label": label, "values": values, "description": row.get("description"),
                    "kind": row.get("kind", "regulatory"), "source": " ".join(str(row["source"]).split()),
                    "retrieved": str(row["retrieved"]), "confidence": row["confidence"], "status": row["status"]})

    labels = {"lrs_annual_limit_usd": "India LRS annual limit (USD)", "tcs_threshold_inr": "India TCS threshold (INR)",
              "purpose_code_education": "RBI purpose code, education", "safe_quota_usd": "China SAFE annual quota (USD)",
              "wallet_foreign_card_fee": "Wallet foreign-card fee", "split_pattern": "Split-payment pattern (Oasis policy)"}
    tcs_labels = {"education": "India TCS, education (self-funded)", "education_loan": "India TCS, education (specified-FI loan)",
                  "other": "India TCS, other purposes (rent, living, family)"}
    for rid, row in data["rules"].items():
        if rid == "tcs_by_purpose":
            for k, lab in tcs_labels.items():
                add(f"tcs_{k}", row[k], lab)
        else:
            add(rid, row, labels.get(rid, rid))
    return {"corridor": data["corridor"], "version": data["version"], "as_of": data["as_of"], "retrieved": "2026-10-11",
            "statuses": list(STATUSES),
            "disclaimer": ("Researched on 2026-10-11 from the named sources; several are secondary and none is confirmed by a bank "
                           "or counsel. Not legal advice. Confirm with an authorised dealer bank before relying on any figure."),
            "rules": out}


def tcs_amount(passport: Passport, remitter: str, amount_inr: float, purpose: str, rules: dict) -> float:
    r = tcs_rate(passport, purpose, rules)
    already = passport.remitted_inr_fy.get(remitter, 0.0)
    t = r["threshold_inr"]
    over = max(0.0, already + amount_inr - t) - max(0.0, already - t)
    return round(over * r["rate"], 2)


def check(passport: Passport, *, payee_type: str, purpose: str, amount_cny: float, amount_inr: float,
          remitter: str = "student", history: list[dict] | None = None, payee_id: str = "",
          now_ts: float = 0.0, year: int | None = None) -> CorridorResult:
    """`year` is the calendar year used for the SAFE quota (default: the year of `now_ts`)."""
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
    tr = tcs_rate(passport, purpose, rules)
    if tcs > 0:
        note = tcs_caveat(tr)
        res.findings.append(Finding("tcs", "warn",
                                    f"TCS of INR {tcs:,.0f} would be collected (recoverable as a tax credit).{note}",
                                    {"tcs_inr": tcs, "rate": tr["rate"], "rate_status": tr["status"],
                                     "category": tr["category"]}))
    elif used + amount_inr > r["tcs_threshold_inr"]["value"] * 0.8 and passport.funding_source != "education_loan":
        res.findings.append(Finding("tcs_near", "info",
                                    "Approaching the INR 10 lakh TCS threshold for this remitter."))

    # SAFE facilitation quota: cumulative per CALENDAR year, the same arithmetic as the plan validator
    # (planning/validator.py): INR already converted this year (Passport.safe_used_inr) plus this amount.
    safe_inr = r["safe_quota_usd"]["value"] * USD_INR
    y = year if year is not None else (datetime.fromtimestamp(now_ts, timezone.utc).year if now_ts else date.today().year)
    safe_used = passport.safe_used_inr.get(str(y), 0.0)
    if safe_used + amount_inr > safe_inr:
        res.findings.append(Finding("safe_quota", "warn",
                                    f"Conversions in {y} would total INR {safe_used + amount_inr:,.0f}, above the annual SAFE "
                                    f"facilitation quota of INR {safe_inr:,.0f}; stage it or prepare documents.",
                                    {"year": y, "used_inr": round(safe_used, 2), "quota_inr": round(safe_inr, 2)}))

    if purpose == "tuition":
        res.findings.append(Finding("purpose_code", "info",
                                    f"Report under education purpose code {r['purpose_code_education']['value']} "
                                    f"(UNCONFIRMED: {r['purpose_code_education']['status']}; verify with the authorised dealer bank)."))

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
