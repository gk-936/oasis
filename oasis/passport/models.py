"""Student Financial Passport: the agent's single source of truth."""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Level(str, Enum):
    UNVERIFIED = "unverified"
    REGISTRY_CHECKED = "registry_checked"
    TEST_PAID = "test_paid"
    VERIFIED_LOW = "verified_low"
    VERIFIED_FULL = "verified_full"
    REJECTED = "rejected"


LEVEL_ORDER = {Level.REJECTED: -1, Level.UNVERIFIED: 0, Level.REGISTRY_CHECKED: 1,
               Level.TEST_PAID: 2, Level.VERIFIED_LOW: 3, Level.VERIFIED_FULL: 4}


class Verification(BaseModel):
    method: str = "none"
    level: Level = Level.UNVERIFIED
    limit_cny: float = 0.0
    verified_at: Optional[str] = None
    successful_payments: int = 0
    notes: list[str] = Field(default_factory=list)


class Recipient(BaseModel):
    id: str
    name: str
    payee_type: str  # university | landlord | family | merchant | wallet
    account_ref: str
    verification: Verification = Field(default_factory=Verification)


class Obligation(BaseModel):
    id: str
    type: str  # tuition | rent | deposit | living | family_support
    payee_id: str
    amount: float
    currency: str = "CNY"
    due: str  # ISO date
    status: str = "pending"  # pending | planned | paid | frozen
    recurring: bool = False
    every_days: int = 30     # recurrence period for recurring bills
    label: str = ""


class Balance(BaseModel):
    currency: str
    amount: float


class Rules(BaseModel):
    tier1_auto_limit_cny: float = 500
    runway_alert_months: float = 1.0
    parent_coapproval_above_inr: float = 50000
    hard_limit_cny: float = 200000
    tier1_auto_convert_cny: float = 5000      # a student-set rate target may convert up to this much automatically
    rate_targets: list[dict] = Field(default_factory=list)  # {"id","pair":"INR-CNY","rate":0.09,"convert_cny":5000,"status"}


class Approver(BaseModel):
    role: str
    name: str
    language: str = "en"


class Student(BaseModel):
    id: str
    name: str
    home_currency: str = "INR"
    host_currency: str = "CNY"
    language: str = "en"
    monthly_budget_cny: float = 4000


class Passport(BaseModel):
    student: Student
    balances: list[Balance]
    obligations: list[Obligation] = Field(default_factory=list)
    recipients: dict[str, Recipient] = Field(default_factory=dict)
    rules: Rules = Field(default_factory=Rules)
    approvers: list[Approver] = Field(default_factory=list)
    remitted_inr_fy: dict[str, float] = Field(default_factory=dict)  # remitter -> INR this FY
    reputation: dict = Field(default_factory=lambda: {"verified_on_time_payments": 0, "proofs": []})
    funding_source: str = "self"  # self | education_loan
    expected_income: list[dict] = Field(default_factory=list)  # {"label","amount_cny","expected":"date","received":bool}
    transactions: list[dict] = Field(default_factory=list)     # {"date","desc","amount_cny","category","source"}
    autonomy_log: list[dict] = Field(default_factory=list)     # Tier-1 actions the agent took on its own
    safe_used_inr: dict[str, float] = Field(default_factory=dict)  # calendar year -> INR already converted (SAFE quota)

    def balance(self, cur: str) -> float:
        return next((b.amount for b in self.balances if b.currency == cur), 0.0)

    def set_balance(self, cur: str, amount: float) -> None:
        for b in self.balances:
            if b.currency == cur:
                b.amount = amount
                return
        self.balances.append(Balance(currency=cur, amount=amount))

    def obligation(self, oid: str) -> Optional[Obligation]:
        return next((o for o in self.obligations if o.id == oid), None)
