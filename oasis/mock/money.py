"""Exact fen arithmetic for sandbox balances.

Balances stay JSON-friendly floats, but every addition and subtraction is done in `Decimal` on the shortest decimal form of
each operand and rounded half-even to whole fen, so repeated transfers cannot accumulate binary floating-point error
(0.1 + 0.2 is exactly 0.3). Amounts inside signed intents and API bodies are still floats (README Known limitation 7).
"""
from __future__ import annotations
from decimal import ROUND_HALF_EVEN, Decimal

FEN = Decimal("0.01")


def _d(x) -> Decimal:
    return Decimal(repr(float(x)))


def fen(x) -> float:
    return float(_d(x).quantize(FEN, rounding=ROUND_HALF_EVEN))


def add(a, b) -> float:
    return float((_d(a) + _d(b)).quantize(FEN, rounding=ROUND_HALF_EVEN))


def sub(a, b) -> float:
    return float((_d(a) - _d(b)).quantize(FEN, rounding=ROUND_HALF_EVEN))
