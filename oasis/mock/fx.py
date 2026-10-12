"""Multi-currency FX for the sandbox wallet: INR, CNY and USD.

MOCK data. The USD->CNY level is a frozen snapshot of the ECB reference cross rate of 2026-10-09 (1 USD = 6.6921 CNY,
Frankfurter), or the live value when OASIS_RATES=live (see oasis/market/live_fx.py). INR is tied to the world's own
INR->CNY mid rate (mock sine path or live ECB) so a wallet INR->CNY quote and the planner agree on the mid rate.

A wallet conversion pays an illustrative mock spread and a fixed fee. These are NOT any real provider's prices. The
"typical bank" comparison uses a mock 3% spread plus a fixed fee, the same shape the route comparison already uses.
Oasis never predicts rates.
"""
from __future__ import annotations

from dataclasses import dataclass

CURRENCIES = ("INR", "CNY", "USD")
SYMBOLS = {"INR": "₹", "CNY": "¥", "USD": "$"}

USD_CNY_SNAPSHOT = 6.6921          # ECB cross, 2026-10-09 (frozen; MOCK when used offline)
WALLET_SPREAD = 0.006              # MOCK: fraction below mid taken by the wallet
WALLET_FIXED_FEE_USD = 1.5         # MOCK: fixed fee, expressed in USD and converted to the source currency
BANK_SPREAD = 0.030                # MOCK typical-bank comparison
BANK_FIXED_FEE_USD = 25.0
MAX_AMOUNT = 1e9


class FxError(ValueError):
    """A request the wallet refuses (unsupported currency, bad amount, same currency, ...)."""


@dataclass(frozen=True)
class FxQuote:
    src: str
    dst: str
    amount: float          # in src
    mid: float             # dst per 1 src, before spread
    rate: float            # dst per 1 src after the wallet spread
    fee: float             # fixed fee, in src
    received: float        # in dst
    bank_received: float   # what a typical bank route would deliver (MOCK), in dst
    saved: float           # received - bank_received, in dst

    def to_dict(self) -> dict:
        return {"from": self.src, "to": self.dst, "amount": self.amount, "mid": self.mid, "rate": self.rate,
                "fee": self.fee, "received": self.received, "bank_received": self.bank_received, "saved": self.saved,
                "mock": "spread and fees are illustrative MOCK values, not a provider's prices"}


def per_usd(cny_per_inr: float, usd_cny: float = USD_CNY_SNAPSHOT) -> dict[str, float]:
    """Units of each currency per 1 USD. INR follows the world's INR->CNY mid so the two views agree."""
    if cny_per_inr <= 0 or usd_cny <= 0:
        raise FxError("non-positive reference rate")
    return {"USD": 1.0, "CNY": float(usd_cny), "INR": float(usd_cny) / float(cny_per_inr)}


def mid(src: str, dst: str, table: dict[str, float]) -> float:
    """`dst` per 1 `src` at the mid rate."""
    _check(src), _check(dst)
    return table[dst] / table[src]


def _check(cur: str) -> None:
    if cur not in CURRENCIES:
        raise FxError(f"unsupported currency {cur!r}; supported: {', '.join(CURRENCIES)}")


def _clean_amount(amount) -> float:
    try:
        a = float(amount)
    except (TypeError, ValueError):
        raise FxError("amount must be a number") from None
    if a != a or a in (float("inf"), float("-inf")) or a <= 0 or a > MAX_AMOUNT:
        raise FxError("amount must be a positive, finite number")
    if round(a, 2) != a:
        a = round(a, 2)
    if a < 0.01:
        raise FxError("amount is below one hundredth of a unit")
    return a


def quote(amount, src: str, dst: str, table: dict[str, float]) -> FxQuote:
    """Mid -> wallet quote: received = (amount - fixed_fee) * mid * (1 - spread). Refuses amounts the fee would swallow."""
    _check(src), _check(dst)
    if src == dst:
        raise FxError("choose two different currencies")
    a = _clean_amount(amount)
    m = mid(src, dst, table)
    fee = WALLET_FIXED_FEE_USD * table[src]                       # USD -> src
    if a <= fee:
        raise FxError(f"amount must exceed the fixed fee ({SYMBOLS[src]}{fee:,.2f})")
    received = round((a - fee) * m * (1 - WALLET_SPREAD), 2)
    bank_fee = BANK_FIXED_FEE_USD * table[src]
    bank = round(max(0.0, (a - bank_fee) * m * (1 - BANK_SPREAD)), 2)
    return FxQuote(src, dst, a, round(m, 6), round(m * (1 - WALLET_SPREAD), 6), round(fee, 2), received, bank,
                   round(received - bank, 2))


def usd_equivalent(amount: float, cur: str, table: dict[str, float]) -> float:
    _check(cur)
    return amount / table[cur]
