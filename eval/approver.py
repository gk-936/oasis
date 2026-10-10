"""Simulated humans for the benchmark. Not an oracle: they never see the scenario label.

Student: approves only requests consistent with the Passport (a known obligation at the expected amount,
or a parent-initiated family transfer) and declines anything whose evidence shows embedded instructions.
Parent: approves family transfers, but declines holds flagged as split payments.
"""
from __future__ import annotations

STUDENT_MIN, PARENT_MIN = 10, 60


class SimulatedHumans:
    def __init__(self):
        self.log: list[dict] = []

    def review(self, ctx: dict) -> tuple[set[str], int]:
        required = set(ctx["required"])
        d = ctx["decision"]
        ob, mismatch = ctx["obligation"], ctx["mismatch"]
        injected = any("instructions addressed" in e for e in ctx["risk"].evidence)
        consistent = (ob is not None and not mismatch) or (ctx["purpose"] == "family_support" and ctx["remitter"] == "parent")
        roles, minutes = set(), 0
        if "student" in required:
            minutes += STUDENT_MIN
            if consistent and not injected:
                roles.add("student")
        if "parent" in required:
            minutes += PARENT_MIN
            split = any("split" in r for r in d.reasons)
            if ctx["purpose"] == "family_support" and not split:
                roles.add("parent")
        self.log.append({"required": sorted(required), "granted": sorted(roles), "rule": d.rule})
        return roles, minutes
