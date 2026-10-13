"""World: wires the Passport, mock layer and trust modules for one student/session."""
from __future__ import annotations
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from .agent.llm import LLM, make_llm
from .chain.anchor import Anchor, LocalAnchorChain, make_anchor
from .mock import money
from .mock.ledger import Account, SandboxLedger, Transfer
from .market import make_rates
from .mock.rates import MockRates
from .mock.registry import VerifiedPayeeRegistry
from .passport.models import (Approver, Balance, Level, Obligation, Passport, Recipient, Rules, Student)
from .trust.approvals import ApproverRegistry, SimDevices
from .trust.audit import AuditLog
from .trust.canaries import CanaryHit, Canaries
from .trust.crypto import HybridSigner, demo_signer
from .trust.executor import Executor
from .trust.intents import IntentBuilder
from .trust.keystore import fingerprint
from .trust.verification import Verifier

CST = timezone(timedelta(hours=8))
STUDENT_ACCT = "acct_student_cny"
UNIV_ACCT = "6228480000001234"
LANDLORD_ACCT = "6222021111110001"
LANDLORD_ACCT_NEW = "6222021111110002"
STUDENT_SELF_ACCT = "acct_student_cny"
TELECOM_ACCT = "6228480000002468"
MIN_CONVERSION_CNY = 500.0
FX_ACCTS = {"USD": "acct_student_usd", "EUR": "acct_student_eur"}   # the student's own foreign-currency accounts (MOCK)


@dataclass(frozen=True)
class Features:
    verification: bool = True
    intents_policy: bool = True   # signed intents + deterministic policy engine + intent-enforcing executor
    canaries: bool = True

    @staticmethod
    def baseline() -> "Features":
        return Features(False, False, False)

    @staticmethod
    def plus_verification() -> "Features":
        return Features(True, False, False)

    @staticmethod
    def plus_intents() -> "Features":
        return Features(True, True, False)

    @staticmethod
    def full() -> "Features":
        return Features(True, True, True)

    def label(self) -> str:
        return {(False, False, False): "baseline", (True, False, False): "+verification",
                (True, True, False): "+intents+policy", (True, True, True): "full"}.get(
            (self.verification, self.intents_policy, self.canaries), "custom")


class World:
    def __init__(self, features: Features | None = None, llm: LLM | None = None, seed: int = 7,
                 inr: float = 500000, persona: str = "arjun", audit_path=None, deterministic: bool = False,
                 store=None, autonomy: bool = False, signer: HybridSigner | None = None,
                 approvers: ApproverRegistry | None = None, sim_devices: bool = True,
                 rates_mode: str | None = None):
        """`deterministic=True` (scripted demo only): seeded demo keys and nonces, simulated-clock anchor
        timestamps, so a run reproduces the same audit-chain head every time. `store` is an optional SqliteStore.
        `signer` supplies the trust signing keys (the API passes the persistent server keys, see trust/keystore.py);
        by default a fresh in-memory key set is generated (demo keys when deterministic).
        Approvals are signatures by per-role device keys (trust/approvals.py). `approvers` is the registry of their public
        keys. `sim_devices=True` (sandbox worlds: benchmark, scripted demo, red team, tests) adds in-process device keys
        for the SIMULATED humans; the API's real world passes `sim_devices=False`, so only real devices can approve."""
        self.features = features or Features.full()
        self.llm = llm or make_llm()
        # Exchange rates: OASIS_RATES=live uses the real ECB reference rate (see docs/live-rates.md); the default and every
        # deterministic/benchmark/test world use the mock. `rates_mode` forces a mode ("mock" | "live").
        self.rates: MockRates = make_rates(seed, mode="mock" if deterministic else rates_mode)
        self.seed = seed
        self.deterministic = deterministic
        self.store = store
        self.autonomy_enabled = autonomy
        self.start = datetime(2026, 10, 12, 10, 0, tzinfo=CST)
        self.now = self.start
        self.day_index = 0
        self.registry = VerifiedPayeeRegistry(deterministic=deterministic)
        self.ledger = SandboxLedger(static_credential=not self.features.intents_policy)
        self.audit = AuditLog(audit_path, clock=lambda: self.now.timestamp(),
                              on_append=store.append_audit if store else None)
        self.canaries = Canaries.plant(f"{seed:02d}") if self.features.canaries else None
        self.signer = signer or (demo_signer("trust", "oasis-demo-key-1") if deterministic else HybridSigner())
        self.builder = IntentBuilder(self.signer, seed=seed if deterministic else None)
        self.verifier = Verifier(self.registry)
        # Deterministic worlds (scripted demo, tests) always use the local simulated chain. Otherwise OASIS_ANCHOR picks it:
        # local (default) or fisco (a real local FISCO BCOS 3.x chain, labelled fallback to local if it is unreachable).
        self.anchor: Anchor = (LocalAnchorChain(clock=lambda: self.now.timestamp()) if deterministic else make_anchor())
        self.approvers = approvers if approvers is not None else ApproverRegistry()
        self.sim_devices = SimDevices(self.approvers, seed=b"oasis-demo-devices" if deterministic else None) if sim_devices else None
        self.executor = Executor(self.ledger, self.signer, self.audit, self.canaries, self.now_iso, self.approvers)
        self.history: list[dict] = []
        self.proofs: dict[str, dict] = {}
        self.cards: list[dict] = []     # "Why was I stopped?" cards
        self.plans: list[dict] = []     # agentic payment plans (proposals; see oasis/agent/planner.py)
        self.sim_minutes = 0
        self.passport = self._seed_passport(inr, persona)
        self._seed_world()
        self.sync_balances()

    def trust_fingerprint(self) -> str:
        return fingerprint(self.signer.public_keys())

    # -- clock -----------------------------------------------------------
    def now_iso(self) -> str:
        return self.now.isoformat()

    @property
    def today(self) -> date:
        return self.now.date()

    def advance(self, minutes: float = 0, days: int = 0) -> None:
        self.now += timedelta(minutes=minutes, days=days)
        self.day_index += days
        self.sim_minutes += int(minutes)

    # -- seeding ---------------------------------------------------------
    def _seed_passport(self, inr: float, persona: str) -> Passport:
        p = Passport(
            student=Student(id="stu_001", name=persona.title(), language="en", monthly_budget_cny=4000),
            balances=[Balance(currency="INR", amount=inr), Balance(currency="CNY", amount=0.0)],
            rules=Rules(),
            approvers=[Approver(role="parent", name="Lakshmi", language="ta")],
            obligations=[
                Obligation(id="obl_tuition_1", type="tuition", payee_id="payee_univ_x", amount=30000, due="2026-11-15"),
                Obligation(id="obl_rent_1", type="rent", payee_id="payee_landlord_chen", amount=6000, due="2026-11-01"),
                Obligation(id="obl_deposit_1", type="deposit", payee_id="payee_landlord_chen", amount=6000, due="2026-10-25"),
            ])
        return p

    def _seed_world(self) -> None:
        r = self.registry
        r.issue("payee_univ_x", "University X Finance Office", "university", UNIV_ACCT)
        r.issue("payee_landlord_chen", "Chen Wei", "landlord", LANDLORD_ACCT)
        r.issue("payee_student_self", "Arjun (own CNY account)", "student", STUDENT_SELF_ACCT)
        # Verified contact channels (MOCK, reserved example domains / fictional numbers). Recovery messages use only these.
        r.set_contact("payee_univ_x", "the finance office's official portal inbox", "finance@univ-x.example.edu")
        r.set_contact("payee_landlord_chen", "the phone number on the signed lease", "+86 755 0100 0001 (MOCK)")
        self.ledger.open(STUDENT_ACCT, "student")
        self.ensure_fx_accounts()
        # Parent's remittance source (CNY-equivalent after their own INR conversion; MOCK).
        self.ledger.open("acct_parent", "parent (Lakshmi)", balance=100000)
        self.ledger.open(UNIV_ACCT, "University X")
        self.ledger.open(LANDLORD_ACCT, "Chen Wei")
        self.ledger.open(LANDLORD_ACCT_NEW, "Chen Wei (new account)")
        for ref in ("6228480000009999", "6228480000007777", "6228480000008888", "6228480000005555",
                    "6666000000000001", "6666000000000002", "6666000000000003"):
            self.ledger.open(ref, "attacker", is_attacker=True)
        # University and landlord start as fully verified recipients; the demo can reset them.
        for pid, name, typ, acct in (("payee_univ_x", "University X Finance Office", "university", UNIV_ACCT),
                                     ("payee_landlord_chen", "Chen Wei", "landlord", LANDLORD_ACCT),
                                     ("payee_student_self", "Arjun (own CNY account)", "student", STUDENT_SELF_ACCT)):
            rec = Recipient(id=pid, name=name, payee_type=typ, account_ref=acct)
            Verifier.seed_verified(self.passport, rec)
        if self.autonomy_enabled:
            # A small recurring bill to a Verified_Full recipient (MOCK carrier): the agent may pay it on its own (Tier 1).
            r.issue("payee_telecom", "Shenzhen Mobile (demo)", "merchant", TELECOM_ACCT)
            r.set_contact("payee_telecom", "the carrier's official app", "app:shenzhen-mobile (MOCK)")
            self.ledger.open(TELECOM_ACCT, "Shenzhen Mobile (demo)")
            Verifier.seed_verified(self.passport, Recipient(id="payee_telecom", name="Shenzhen Mobile (demo)",
                                                            payee_type="merchant", account_ref=TELECOM_ACCT))
            self.passport.obligations.append(Obligation(
                id="obl_phone_1", type="living", payee_id="payee_telecom", amount=150, due="2026-10-15",
                recurring=True, every_days=30, label="Mobile plan (recurring)"))
        # Canary bait: a decoy payee that exists only as bait.
        if self.canaries:
            for d in self.canaries.decoy_payees:
                self.passport.recipients[d] = Recipient(id=d, name="Reserve Fund (legacy)", payee_type="merchant",
                                                        account_ref="6666000000000001")

    # -- balances --------------------------------------------------------
    def ensure_fx_accounts(self) -> None:
        for cur, ref in FX_ACCTS.items():
            if ref not in self.ledger.accounts:
                self.ledger.open(ref, f"student ({cur})", currency=cur)

    def credit_fx(self, cur: str, amount: float) -> None:
        """Sandbox funding of the student's own USD / EUR account (tests and demo setup; the ledger is the source of truth)."""
        self.ledger.accounts[FX_ACCTS[cur]].balance = money.add(self.ledger.accounts[FX_ACCTS[cur]].balance, amount)
        self.sync_balances()

    def sync_balances(self) -> None:
        self.passport.set_balance("CNY", round(self.ledger.accounts[STUDENT_ACCT].balance, 2))
        for cur, ref in FX_ACCTS.items():
            if ref in self.ledger.accounts:
                bal = round(self.ledger.accounts[ref].balance, 2)
                if bal or any(b.currency == cur for b in self.passport.balances):    # a zero balance is not listed until it has been used
                    self.passport.set_balance(cur, bal)

    def convert(self, cny_needed: float, due: date | None = None) -> dict | None:
        """Plan step: convert INR to CNY with the best on-time route if funds are short."""
        from .planning.routes import best_route, inr_needed, savings_vs_bank
        short = cny_needed - self.passport.balance("CNY")
        if short <= 0.005:
            return None
        short = max(short, MIN_CONVERSION_CNY)  # fixed fees make tiny conversions wasteful
        quote, bank = best_route(self.rates, 1_000_000, self.today, due, self.day_index)
        if quote is None:      # nothing arrives by the due date: take the fastest route rather than fail
            from .planning.routes import quote_routes
            quote = min((q for q in quote_routes(self.rates, 1_000_000, self.today, None, self.day_index)
                         if not q.route.typical_bank), key=lambda q: (q.arrives_in_days, -q.delivered_cny))
        route = quote.route
        send = inr_needed(self.rates, route, short + 0.01, self.day_index)
        if send > self.passport.balance("INR"):
            return {"error": "insufficient_inr", "needed_inr": send}
        from .mock.rates import delivered_amount
        got = round(delivered_amount(send, route, self.rates.mid(self.day_index)), 2)
        self.passport.set_balance("INR", round(self.passport.balance("INR") - send, 2))
        self.ledger.accounts[STUDENT_ACCT].balance = money.add(self.ledger.accounts[STUDENT_ACCT].balance, got)
        self.note_safe_use(send)
        self.sync_balances()
        bank_got = delivered_amount(send, bank.route, self.rates.mid(self.day_index))
        rec = {"route": route.name, "route_id": route.id, "sent_inr": send, "delivered_cny": got,
               "bank_delivered_cny": round(bank_got, 2), "saved_cny": round(got - bank_got, 2),
               "saved_pct": round((got - bank_got) / bank_got * 100, 2) if bank_got else 0.0,
               "tax_note": "TCS is an advance tax credit, not a fee."}
        self.audit.append("conversion", rec)
        return rec

    def note_safe_use(self, send_inr: float) -> None:
        y = str(self.today.year)
        self.passport.safe_used_inr[y] = round(self.passport.safe_used_inr.get(y, 0.0) + send_inr, 2)

    def convert_step(self, send_inr: float, route_id: str, remitter: str = "student") -> dict:
        """Execute one conversion of an accepted plan: a fixed INR amount on a named route into the student's own CNY
        account. Never pays a third party. The caller has already passed `policy.decide_conversion`."""
        from .mock.rates import ROUTES, delivered_amount
        route = next(r for r in ROUTES if r.id == route_id)
        if remitter == "student" and send_inr > self.passport.balance("INR") + 0.005:
            return {"error": "insufficient_inr", "needed_inr": send_inr}
        mid = self.rates.mid(self.day_index)
        got = round(delivered_amount(send_inr, route, mid), 2)
        bank = next(r for r in ROUTES if r.typical_bank)
        bank_got = delivered_amount(send_inr, bank, mid)
        if remitter == "student":
            self.passport.set_balance("INR", round(self.passport.balance("INR") - send_inr, 2))
        else:     # the parent sends INR from their own account; it counts against the parent's LRS / TCS, not the student's
            self.passport.remitted_inr_fy[remitter] = self.passport.remitted_inr_fy.get(remitter, 0.0) + send_inr
        self.ledger.accounts[STUDENT_ACCT].balance = money.add(self.ledger.accounts[STUDENT_ACCT].balance, got)
        self.note_safe_use(send_inr)
        self.sync_balances()
        rec = {"route": route.name, "route_id": route.id, "sent_inr": send_inr, "delivered_cny": got, "remitter": remitter,
               "bank_delivered_cny": round(bank_got, 2), "saved_cny": round(got - bank_got, 2),
               "saved_pct": round((got - bank_got) / bank_got * 100, 2) if bank_got else 0.0,
               "tax_note": "TCS is an advance tax credit, not a fee."}
        self.audit.append("conversion", rec)
        return rec

    def convert_fx_step(self, cid: str, route_id: str, send: float, remitter: str = "student", counts_against_quota: bool = True) -> dict:
        """Execute one conversion of an accepted foreign-currency plan: `send` in the corridor's source currency on a named
        route into the student's own USD / EUR account. Never pays a third party. The caller has already passed
        `policy.decide_conversion`. The sandbox credits the EXPECTED delivery (the plan only counted on the worst case)."""
        from .corridors import core as cor
        from .mock import fx as fxm
        c = cor.corridor(cid)
        src, dst = c["src"], c["dst"]
        if dst not in FX_ACCTS or c.get("engine") == "legacy":
            return {"error": "unsupported_corridor"}
        table = fxm.table_for(self.rates, self.day_index)
        route = next((r for r in cor.routes_for(cid, table) if r.id == route_id), None)
        if route is None:
            return {"error": "unknown_route"}
        mid = fxm.mid(src, dst, table)
        if remitter == "student":
            held = (self.passport.balance(src) if src not in ("CNY", *FX_ACCTS) else self.ledger.accounts[STUDENT_ACCT if src == "CNY" else FX_ACCTS[src]].balance)
            if send > held + 0.005:
                return {"error": f"insufficient_{src.lower()}", "needed": send}
        elif remitter == "parent" and src != "INR":
            return {"error": "only an INR conversion can be remitted by the parent"}
        got = round(max(0.0, cor.delivered(send, route, mid) - route.deduction_worst_dst / 2), 2)
        bank = next((r for r in cor.routes_for(cid, table) if r.typical_bank), None)
        bank_got = round(max(0.0, cor.delivered(send, bank, mid) - bank.deduction_worst_dst / 2), 2) if bank else 0.0
        if remitter == "student":
            if src == "INR":
                self.passport.set_balance("INR", round(self.passport.balance("INR") - send, 2))
            else:
                a = self.ledger.accounts[STUDENT_ACCT if src == "CNY" else FX_ACCTS[src]]
                a.balance = money.sub(a.balance, send)
        if src == "INR":
            self.passport.remitted_inr_fy[remitter] = money.add(self.passport.remitted_inr_fy.get(remitter, 0.0), send)
        elif src == "CNY" and counts_against_quota:     # counts against the SAFE annual quota (USD equivalent, per calendar year)
            y = str(self.today.year)
            self.passport.cn_outbound_usd[y] = money.add(self.passport.cn_outbound_usd.get(y, 0.0), send / table[src])
        d = self.ledger.accounts[FX_ACCTS[dst]]
        d.balance = money.add(d.balance, got)
        self.sync_balances()
        rec = {"corridor": cid, "route": route.name, "route_id": route.id, "sent": send, "from": src, "to": dst, "delivered": got,
               "remitter": remitter, "bank_delivered": bank_got, "saved": round(got - bank_got, 2), "price_status": route.price_status,
               "mock": "route prices are public-range estimates, not live quotes"}
        self.audit.append("conversion", rec)
        return rec

    # -- persistence -----------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        """Everything needed to rebuild this session except signing keys (ephemeral) and the audit log
        (stored entry by entry)."""
        return {
            "kv": {
                "passport": self.passport.model_dump(),
                "ledger": {"accounts": [asdict(a) for a in self.ledger.accounts.values()],
                           "transfers": [asdict(t) for t in self.ledger.transfers]},
                "history": self.history,
                "clock": {"now": self.now_iso(), "day_index": self.day_index, "sim_minutes": self.sim_minutes,
                          "seed": self.seed},
                "trust": {"nonces": sorted(self.executor.used_nonces), "intent_counter": self.builder._n,
                          "anchor_blocks": self.anchor.blocks if isinstance(self.anchor, LocalAnchorChain) else [],
                          "canary_hits": [h.__dict__ for h in self.canaries.hits] if self.canaries else []},
                "registry": self.registry.all(),
                "plans": self.plans,
            },
            "proofs": self.proofs,
            "cards": self.cards,
        }

    def restore(self, snap: dict) -> None:
        kv = snap["kv"]
        self.passport = Passport.model_validate(kv["passport"])
        self.ledger.accounts = {a["ref"]: Account(**a) for a in kv["ledger"]["accounts"]}
        self.ensure_fx_accounts()
        self.ledger.transfers = [Transfer(**t) for t in kv["ledger"]["transfers"]]
        self.history = list(kv["history"])
        c = kv["clock"]
        self.now, self.day_index, self.sim_minutes = datetime.fromisoformat(c["now"]), c["day_index"], c["sim_minutes"]
        t = kv["trust"]
        self.executor.used_nonces = set(t["nonces"])
        self.builder._n = t["intent_counter"]
        if isinstance(self.anchor, LocalAnchorChain):
            self.anchor.blocks = list(t["anchor_blocks"])
        if self.canaries:
            self.canaries.hits = [CanaryHit(**h) for h in t["canary_hits"]]
        for cred in kv["registry"]:    # re-issued under this process's issuer key
            self.registry.issue(cred["payee_id"], cred["name"], cred["payee_type"], cred["account_ref"], cred["issued_at"])
        self.proofs = dict(snap["proofs"])
        self.cards = list(snap["cards"])
        self.plans = list(kv.get("plans", []))
        self.audit.entries = list(snap.get("audit", []))

    def save(self) -> None:
        if self.store:
            self.store.save(self.snapshot())
