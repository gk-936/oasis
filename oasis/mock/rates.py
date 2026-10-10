"""MOCK exchange rates, fees, delivery times and reliability. Clearly simulated data."""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    id: str
    name: str
    fixed_fee_inr: float
    pct_fee: float          # fraction of converted amount
    rate_spread: float      # fraction below mid-market rate
    days: int
    reliability: float      # 0..1
    min_inr: float = 0.0
    typical_bank: bool = False


ROUTES = [
    Route("route_bank_swift", "Typical bank SWIFT transfer", 2500, 0.010, 0.030, 4, 0.97, typical_bank=True),
    Route("route_inr_cny_1", "Digital remitter A (INR→CNY)", 400, 0.004, 0.009, 2, 0.95),
    Route("route_inr_cny_2", "Digital remitter B (INR→CNY)", 250, 0.006, 0.006, 1, 0.93),
    Route("route_inr_cny_3", "Education payment specialist", 800, 0.002, 0.004, 3, 0.98),
]


class MockRates:
    """Deterministic mid-market INR→CNY path: a gentle sine around 0.0845 CNY per INR."""
    BASE = 0.0845

    def __init__(self, seed: int = 7):
        self.seed = seed

    def mid(self, day: int = 0) -> float:
        return round(self.BASE * (1 + 0.012 * math.sin((day + self.seed) / 6.0)), 6)

    def route_rate(self, route: Route, day: int = 0) -> float:
        return self.mid(day) * (1 - route.rate_spread)


def delivered_amount(send_inr: float, route: Route, rate_mid: float) -> float:
    """delivered = (send - fixed_fees) * exchange_rate * (1 - percentage_fee)"""
    rate = rate_mid * (1 - route.rate_spread)
    return max(0.0, (send_inr - route.fixed_fee_inr) * rate * (1 - route.pct_fee))
