"""Unusual payment sequences are explained as evidence and can only raise the risk score (policy still decides). Offline."""
from oasis.agent.llm import heuristic_risk, sequence_flags

F = {"payee_name": "Chen Wei", "payee_id": "payee_landlord", "account_ref": "6228480000000001", "amount": 6000.0, "currency": "CNY"}
KN, KA = ["Chen Wei"], {"payee_landlord": "6228480000000001"}


def ev(recent):
    return heuristic_risk(F, "Payee: Chen Wei Amount: 6000", KN, KA, 6000.0, {"recent": recent, "amount_inr": 85000.0})


def test_burst_to_several_payees_is_flagged_with_evidence():
    recent = [{"payee_id": "a", "amount_inr": 1000, "hours_ago": 1}, {"payee_id": "b", "amount_inr": 900, "hours_ago": 2},
              {"payee_id": "c", "amount_inr": 800, "hours_ago": 3}]
    r = ev(recent)
    assert any("different payees in the last 24h" in e for e in r.evidence) and r.score > ev([]).score


def test_third_payment_to_the_same_payee_in_a_day_is_flagged():
    recent = [{"payee_id": "payee_landlord", "amount_inr": 5000, "hours_ago": 2}, {"payee_id": "payee_landlord", "amount_inr": 5000, "hours_ago": 5}]
    assert any("3 payments to the same payee" in e for e in ev(recent).evidence)


def test_amount_far_above_earlier_payments_is_flagged():
    flags = sequence_flags("p", 40000.0, [{"payee_id": "p", "amount_inr": 5000, "hours_ago": 100}, {"payee_id": "p", "amount_inr": 6000, "hours_ago": 700}])
    assert flags and "x larger than any earlier payment" in flags[0][1]


def test_normal_history_adds_nothing():
    assert sequence_flags("p", 6000.0, []) == []
    assert sequence_flags("p", 6000.0, [{"payee_id": "p", "amount_inr": 6000, "hours_ago": 700}]) == []
    assert sequence_flags("p", 6000.0, [{"payee_id": "q", "amount_inr": 100, "hours_ago": 1}, {"payee_id": "r", "amount_inr": 100, "hours_ago": 2}]) == []
    assert ev([]).evidence == []


def test_sequence_flags_never_lower_the_score():
    base = ev([]).score
    assert ev([{"payee_id": "payee_landlord", "amount_inr": 5000, "hours_ago": 2}] * 2).score >= base
