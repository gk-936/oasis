"""Out-of-scope requests get an honest 'I can't do that, here is what I can do' reply: no draft, no wrong-intent answer, CNY 0 moved."""
import pytest
from tests.auth_helpers import new_client


def _say(msg):
    c = new_client("student")
    c.post("/api/reset")
    return c.post("/api/chat", json={"message": msg}).json()


@pytest.mark.parametrize("msg", [
    "I want a student loan", "can I get an education loan", "I want to open a bank account", "how do I open a savings account here",
    "do I need travel insurance", "how do I invest my savings", "what documents do I need to send tuition from India to China",
    "can I apply for a mortgage", "how do I renew my visa", "apply for a visa extension", "should I buy bitcoin", "what paperwork is required to transfer money abroad",
])
def test_out_of_scope_is_declined_honestly(msg):
    j = _say(msg)
    assert j["intent"] == "out_of_scope" and j["status"] == "info" and j["pending_id"] is None and j["money_moved"] == 0
    assert j["reply"].rstrip().endswith("Nothing moved.") and "pay" in j["reply"] and "scam" in j["reply"]


@pytest.mark.parametrize("msg", ["pay my rent", "what do I owe?", "can I get a credit card in China as a foreign student", "cheapest route for 100000 rupees", "pay my tuition", "convert 1000 rupees to yuan"])
def test_in_scope_still_works(msg):
    assert _say(msg)["intent"] != "out_of_scope"
