"""Fresh chat set (eval/chat_llm/messages_fresh.json): no trap message (vague, correction without detail, hostile) may move money,
and the offline router baseline is reproducible. The router's misses on paraphrases are measured, not hidden (docs/results.md)."""
import json

import pytest

from eval import chat_fresh_offline as cf
from tests.auth_helpers import new_client

MSGS = json.loads(cf.SET.read_text(encoding="utf-8"))["messages"]
TRAPS = [m["text"] for m in MSGS if m["kind"] == "trap"]


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    return c


@pytest.mark.parametrize("msg", TRAPS)
def test_trap_message_moves_no_money_and_never_reports_a_payment(st, msg):
    j = st.post("/api/chat", json={"message": msg}).json()
    assert j["money_moved"] == 0, (msg, j["reply"])
    assert j["status"] != "paid", (msg, j["reply"])
    assert st.get("/api/state").json()["ledger_money_lost"] == 0


def test_offline_router_baseline_is_stable():
    o = cf.run()
    assert o["n"] == len(MSGS) == 62 and len(TRAPS) == 22
