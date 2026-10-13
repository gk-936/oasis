"""Generic corridor engine: route comparison and rule checks for any supported currency pair. All prices are MOCK.

The original INR->CNY engine (mock/rates.py, planning/routes.py, trust/corridor.py) stays untouched and is wrapped here
(`engine: legacy`), so both give the same numbers for INR->CNY (tested). New corridors are DATA in
trust/rules/corridors.yaml. Differences from the original engine:
- any currency pair, priced from the shared conversion table (live ECB crosses with OASIS_RATES=live, else the snapshot);
- the send amount is solved in closed form (the delivered formula is linear in the send amount), not by a search;
- fees are shown as one cost in the sending currency and as a share of the mid-market value;
- one rule-check path, with every finding carrying its source and status.
Read-only: nothing here moves money, signs or writes to the audit log.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import yaml

from ..config import RULES_DIR
from ..mock import fx
from ..mock.rates import ROUTES as LEGACY_ROUTES

MOCK_NOTE = "Route prices are illustrative MOCK values, not a provider's prices. Oasis never predicts exchange rates."
MAX_AMOUNT = 1e9
STALE_DAYS = 30


class CorridorError(ValueError):
    pass


@lru_cache(maxsize=1)
def _data() -> dict:
    return yaml.safe_load((RULES_DIR / "corridors.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _inr_cny() -> dict:
    return yaml.safe_load((RULES_DIR / "inr_cny.yaml").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Route:
    id: str
    name: str
    typical_bank: bool
    fixed_fee_src: float        # in the sending currency
    pct_fee: float
    spread: float
    days: int
    reliability: float
    price_status: str           # mock | sourced
    deduction_worst_dst: float  # intermediary deduction, worst case, in the receiving currency; expected is half
    price_source: str = ""
    price_retrieved: str = ""
    price_age_days: int | None = None
    stale: bool = False      # a sourced or estimated price older than STALE_DAYS (needs the simulated/real date to judge)


def corridor_ids() -> list[str]:
    return list(_data()["corridors"])


def corridor(cid: str) -> dict:
    c = _data()["corridors"].get(cid)
    if c is None:
        raise CorridorError(f"unknown corridor {cid!r}; supported: {', '.join(corridor_ids())}")
    return c


def listing() -> list[dict]:
    return [{"id": cid, "from": c["src"], "to": c["dst"], "jurisdiction": _data()["jurisdictions"][c["out_of"]]["label"],
             "routes": len(c.get("routes", LEGACY_ROUTES)), "engine": c.get("engine", "data")} for cid, c in _data()["corridors"].items()]


def routes_for(cid: str, table: dict[str, float], today=None) -> list[Route]:
    c = corridor(cid)
    src, dst = c["src"], c["dst"]
    if c.get("engine") == "legacy":
        from ..flightpath.core import DEDUCTIONS
        return [Route(r.id, r.name, r.typical_bank, r.fixed_fee_inr, r.pct_fee, r.rate_spread, r.days, r.reliability, "mock",
                      DEDUCTIONS.get(r.id, (0.0, 0.0))[1]) for r in LEGACY_ROUTES]
    out = []
    for i, spec in enumerate(c["routes"]):
        t = {**_data()["route_types"][spec["type"]], **{k: v for k, v in spec.items() if k != "type"}}
        out.append(Route(f"route_{cid.lower().replace('-', '_')}_{i + 1}", t["name"], bool(t.get("typical_bank")),
                         t["fixed_fee_usd"] * table[src], t["pct_fee"], t["spread"], t["days"], t["reliability"], t.get("price_status", "mock"),
                         t.get("deduction_worst_usd", 0.0) * table[dst], t.get("price_source", ""), *_age(t, today)))
    return out


def implied_costs(send: float, mid: float, provider_received: float, fixed_fee_src: float = 0.0) -> dict:
    """Calibrate a route from ONE real quote: given what a provider says it delivers for `send`, return the total cost versus
    the mid-market value and the variable (spread plus percentage) cost after the fixed fee. Use it to set corridors.yaml from a
    provider's own quote page, and record the source and date there."""
    if send <= fixed_fee_src or mid <= 0:
        raise CorridorError("send must exceed the fixed fee and mid must be positive")
    return {"total_cost_pct": round((1 - provider_received / (send * mid)) * 100, 3),
            "variable_cost_pct": round((1 - provider_received / ((send - fixed_fee_src) * mid)) * 100, 3)}


def _age(t: dict, today) -> tuple[str, int | None, bool]:
    """(retrieved date, age in days, stale) for a route type; unknown without `today`. Only sourced / estimated prices go stale."""
    ret = str(t.get("price_retrieved") or "")
    if today is None or not ret:
        return ret, None, False
    from datetime import date
    age = (today - date.fromisoformat(ret)).days
    return ret, age, age > STALE_DAYS and t.get("price_status", "mock") in ("sourced", "estimated")


def delivered(send: float, r: Route, mid: float) -> float:
    """(send - fixed fee) * mid * (1 - spread) * (1 - percentage fee); never negative."""
    return max(0.0, (send - r.fixed_fee_src) * mid * (1 - r.spread) * (1 - r.pct_fee))


def send_needed(target_dst: float, r: Route, mid: float) -> float:
    """Exact inverse of `delivered`: the amount to send so the recipient gets `target_dst` even after the worst deduction."""
    return (target_dst + r.deduction_worst_dst) / (mid * (1 - r.spread) * (1 - r.pct_fee)) + r.fixed_fee_src


def _amount(x) -> float:
    try:
        a = float(x)
    except (TypeError, ValueError):
        raise CorridorError("amount must be a number") from None
    if a != a or a <= 0 or a > MAX_AMOUNT:
        raise CorridorError("amount must be a positive, finite number")
    return a


def compare(cid: str, required_dst, table: dict[str, float], due_in_days: int | None = None, today=None) -> dict:
    """For each route: what to send so the recipient gets `required_dst` even in the worst case, ranked on-time first, then
    cheapest to send, then reliability."""
    c = corridor(cid)
    need = _amount(required_dst)
    src, dst = c["src"], c["dst"]
    mid = fx.mid(src, dst, table)
    opts = []
    for r in routes_for(cid, table, today):
        send = send_needed(need, r, mid)
        got = delivered(send, r, mid)
        opts.append({"route_id": r.id, "route": r.name, "typical_bank": r.typical_bank, "send": round(send, 2),
                     "fee_src": round(send - need / mid, 2), "fee_pct_of_value": round((send * mid - need) / (send * mid) * 100, 3),
                     "expected_received": round(got - r.deduction_worst_dst / 2, 2), "worst_received": round(got - r.deduction_worst_dst, 2),
                     "arrives_in_days": r.days, "reliability": r.reliability,
                     "price_status": r.price_status, "price_source": r.price_source, "stale": r.stale, "price_age_days": r.price_age_days, "meets_target": got - r.deduction_worst_dst >= need - 0.01,
                     "on_time": due_in_days is None or r.days <= due_in_days})
    opts.sort(key=lambda o: (not o["on_time"], o["send"], -o["reliability"]))
    bank = next((o for o in opts if o["typical_bank"]), None)
    best = next((o for o in opts if o["on_time"]), None)
    saving = None
    if best and bank:
        saving = {"best": best["route"], "bank": bank["route"], "saved_src": round(bank["send"] - best["send"], 2),
                  "saved_pct": round((bank["send"] - best["send"]) / bank["send"] * 100, 2)}
    return {"corridor": cid, "from": src, "to": dst, "required": round(need, 2), "mid": round(mid, 6), "options": opts,
            "best": best["route_id"] if best else None, "saving_vs_bank": saving, "mock": MOCK_NOTE}


def quote_send(cid: str, send_src, table: dict[str, float]) -> dict:
    """Forward view: what each route delivers for a given send amount."""
    c = corridor(cid)
    s = _amount(send_src)
    mid = fx.mid(c["src"], c["dst"], table)
    rows = [{"route_id": r.id, "route": r.name, "delivered": round(delivered(s, r, mid), 2),
             "worst_delivered": round(max(0.0, delivered(s, r, mid) - r.deduction_worst_dst), 2), "arrives_in_days": r.days}
            for r in routes_for(cid, table)]
    rows.sort(key=lambda x: -x["delivered"])
    return {"corridor": cid, "from": c["src"], "to": c["dst"], "send": round(s, 2), "mid": round(mid, 6), "routes": rows, "mock": MOCK_NOTE}


def _row(src: dict, rid: str, **extra) -> dict:
    return {"rule": rid, "status": src["status"], "source": " ".join(str(src["source"]).split()),
            "retrieved": str(src["retrieved"]), **extra}


def _info(rule: dict) -> dict:
    return {"rule": rule["id"], "severity": rule["severity"], "message": rule["message"], "status": rule["status"],
            "source": " ".join(str(rule["source"]).split()), "retrieved": str(rule["retrieved"])}


def check(cid: str, amount_src, purpose: str, table: dict[str, float]) -> dict:
    """Rule findings for ONE payment. Cumulative use (this year's earlier payments) is not tracked on these corridors."""
    c = corridor(cid)
    a = _amount(amount_src)
    src = c["src"]
    usd = a / table[src]
    findings = []
    base = _inr_cny()["rules"]
    for rule in _data()["jurisdictions"][c["out_of"]]["rules"]:
        kind = rule["kind"]
        if kind == "annual_cap_usd":
            row = base[rule["from"].split(".", 1)[1]]
            if purpose in rule.get("exempt_purposes", ()):
                findings.append({"rule": rule["id"], "severity": "info", "message": rule["exempt_note"], "status": "confirmed-primary",
                                 "source": "SAFE Tianjin bureau, 'Individual foreign exchange (9)', safe.gov.cn/tianjin/2025/0714/2833.html", "retrieved": "2026-10-13"})
                continue
            cap = float(row["value"])
            if usd > cap:
                findings.append(_row(row, rule["id"], severity=rule["severity"], message=f"This payment (about USD {usd:,.0f}) is above the USD {cap:,.0f} annual limit. {rule['note']}"))
            elif usd > 0.8 * cap:
                findings.append(_row(row, rule["id"], severity="info", message=f"About USD {usd:,.0f} is close to the USD {cap:,.0f} annual limit. {rule['note']}"))
        elif kind == "india_tcs":
            tbl = base["tcs_by_purpose"]
            cat = _inr_cny().get("purpose_tcs_category", {}).get(purpose, "other")
            row = tbl[cat]
            inr = a
            over = max(0.0, inr - tbl["threshold_inr"])
            if over > 0 and row["rate"] > 0:
                findings.append(_row(row, rule["id"], severity=rule["severity"], rate=row["rate"],
                                     message=f"TCS of about INR {over * row['rate']:,.0f} would be collected ({row['rate']:.0%} above the threshold; recoverable as a tax credit). {rule['note']}"))
        elif kind == "info":
            findings.append(_info(rule))
    findings.extend(_info(rule) for rule in _data().get("inbound", {}).get(c["dst"], []))
    return {"corridor": cid, "amount": round(a, 2), "usd_equivalent": round(usd, 2), "findings": findings,
            "disclaimer": "Not legal advice. Several figures are secondary-sourced or unconfirmed; confirm with the sending bank."}
