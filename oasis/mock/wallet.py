"""MOCK wallet / QR payment simulator (Alipay / WeChat-style, foreign-card path)."""
from __future__ import annotations


def foreign_card_cost(amount_cny: float, card_bank_fee: float = 0.01,
                      service_rate: float = 0.03, applies_over: float = 200) -> dict:
    """Foreign-card wallet payment costs 3% service fee over ¥200 plus the card bank's own fee."""
    service = amount_cny * service_rate if amount_cny > applies_over else 0.0
    bank = amount_cny * card_bank_fee
    return {"amount_cny": amount_cny, "service_fee": round(service, 2),
            "card_bank_fee": round(bank, 2), "total_cost": round(amount_cny + service + bank, 2),
            "effective_rate": round((service + bank) / amount_cny, 4) if amount_cny else 0.0}


def local_account_cost(amount_cny: float) -> dict:
    return {"amount_cny": amount_cny, "service_fee": 0.0, "card_bank_fee": 0.0,
            "total_cost": round(amount_cny, 2), "effective_rate": 0.0}
