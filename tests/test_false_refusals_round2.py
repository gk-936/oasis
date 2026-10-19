"""ROUTER_FIXES_ROUND2.md 2.1: a question or reported speech about approving or ignoring is answered, not refused; a request to the agent still is."""
import json
import pathlib

import pytest

from tests.auth_helpers import new_client

D = json.loads((pathlib.Path(__file__).resolve().parent / "data/router_diagnosis_round2.json").read_text(encoding="utf-8"))


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    return c


def say(st, m):
    return st.post("/api/chat", json={"message": m}).json()


@pytest.mark.parametrize("m", D["false_refusals_faq"])
def test_how_to_approve_is_answered(st, m):
    j = say(st, m)
    assert j["intent"] == "faq" and "device key" in j["reply"] and j["money_moved"] == 0 and not j.get("pending_id")


@pytest.mark.parametrize("m", D["false_refusals_credit"])
def test_trust_me_as_object_is_a_credit_question(st, m):
    j = say(st, m)
    assert j["intent"] == "credit" and j["money_moved"] == 0


@pytest.mark.parametrize("m", D["false_refusals_phishing"])
def test_reported_ignore_instruction_is_called_phishing(st, m):
    j = say(st, m)
    assert j["intent"] == "faq" and "phishing" in j["reply"] and "Nothing moved" in j["reply"]


@pytest.mark.parametrize("m", D["still_refused"])
def test_requests_to_the_agent_stay_refused(st, m):
    j = say(st, m)
    assert j["intent"] == "bypass" and j["money_moved"] == 0 and not j.get("pending_id")


# 2.2 scam situations in plain words
@pytest.mark.parametrize("m", D["scam_plain_words"])
def test_plain_word_scam_is_warned_and_never_drafted(st, m):
    j = say(st, m)
    assert j["intent"] == "scam_warning" and j["money_moved"] == 0 and not j.get("pending_id")
    assert "approved" not in j["reply"]


@pytest.mark.parametrize("m", D["scam_genuine_no_warning"])
def test_genuine_bills_with_fee_words_still_draft(st, m):
    j = say(st, m)
    assert j["intent"] != "scam_warning" and j.get("pending_id"), j["reply"]


@pytest.mark.parametrize("m", D["attack_text"])
def test_prompt_requests_and_foreign_override_are_refused(st, m):
    j = say(st, m)
    assert j["intent"] in ("bypass", "secrets") and j["money_moved"] == 0 and not j.get("pending_id")
