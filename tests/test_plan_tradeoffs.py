"""The plan's 'why' now sets the chosen route against the alternatives (arithmetic only) and asks instead of guessing when the plan has
nothing to work from. Offline, MOCK rates; the validator, the planner and every number it checks are unchanged."""
from oasis.agent import planner as P
from oasis.agent.llm import OfflineLLM
from oasis.mock.rates import ROUTES, delivered_amount
from oasis.world import Features, World


def world():
    return World(Features.full(), OfflineLLM())


def test_tradeoff_line_compares_every_other_route_with_correct_arithmetic():
    w = world()
    rec = P.propose(w, goal="plan my semester")
    line = next(x for x in rec["why"] if x.startswith("Trade-offs"))
    convs = [s for s in rec["validation"]["schedule"] if s["action"] == "convert"]
    chosen_ids = {c["route_id"] for c in convs}
    send = sum(c["send_inr"] for c in convs)
    mid = w.rates.mid(w.day_index)
    chosen = next(r for r in ROUTES if r.id in chosen_ids)
    for r in ROUTES:
        if r.id in chosen_ids:
            assert r.name not in line.split("against")[1].split(":")[1]
            continue
        diff = delivered_amount(send, r, mid) - delivered_amount(send, chosen, mid)
        assert f"{r.name} ({r.days} day" in line
        assert f"CNY {abs(diff):,.0f} {'more' if diff >= 0 else 'less'}" in line
    assert "still arrives in time" in line or "would arrive after the payment it funds" in line


def test_plan_without_conversions_has_no_tradeoff_line():
    assert P.tradeoffs(world(), {"schedule": [{"action": "pay", "date": "2026-11-01"}]}) == []


def test_it_asks_instead_of_guessing_when_there_is_no_open_bill():
    w = world()
    for o in w.passport.obligations:
        o.status = "paid"
    qs = P.missing_info(w)
    assert qs and "no open bill" in qs[0]
    rec = P.propose(w, goal="plan my semester")
    assert any(x.startswith("Question:") for x in rec["why"])


def test_no_question_when_the_plan_has_what_it_needs():
    assert P.missing_info(world()) == []


def test_tradeoff_and_question_lines_translate_to_chinese():
    from oasis.agent.zh_messages import is_translated, tr
    w = world()
    line = next(x for x in P.propose(w, goal="plan my semester")["why"] if x.startswith("Trade-offs"))
    zh = tr(line)
    assert is_translated(line) and "到账 ¥" in zh and "Trade-offs" not in zh
    for q in P.missing_info(world()) + ["There is no open bill to plan for. Which payment should I plan (for example 'tuition of CNY 30,000 by 15 November')?"]:
        assert is_translated("Question: " + q) if q.startswith("There is no open bill") else True
