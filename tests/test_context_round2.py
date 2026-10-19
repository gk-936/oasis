"""ROUTER_FIXES_ROUND2.md 2.5: follow-ups that bind to the last answer. Each conversation runs in one session. DEV fixtures, tuned on."""
import pytest

from tests.auth_helpers import new_client


def run(*msgs):
    c = new_client("student")
    c.post("/api/reset")
    return [c.post("/api/chat", json={"message": m}).json() for m in msgs]


def test_what_do_i_owe_then_the_rent_then_pay_it_drafts_the_rent():
    j = run("what do I owe", "and the rent?", "pay it")[-1]
    assert j["intent"] == "pay_obligation" and j["pending_id"] and "Chen Wei" in j["reply"] and j["money_moved"] == 0


def test_who_is_my_landlord_then_pay_him_drafts_the_rent():
    j = run("who is my landlord", "pay him")[-1]
    assert j["pending_id"] and "Chen Wei" in j["reply"] and j["money_moved"] == 0


def test_a_bare_pay_it_with_no_context_still_asks_which():
    j = run("pay it")[-1]
    assert not j.get("pending_id")


def test_no_2000_corrects_a_conversion_request():
    j = run("convert 3000 yuan to rupees", "no, 2000")[-1]
    assert j["intent"] == "convert" and "2,000" in j["reply"]
