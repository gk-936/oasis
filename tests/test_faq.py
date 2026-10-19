import json
import pathlib
import re

from oasis.agent import faq
from tests.auth_helpers import new_client

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIAG = json.loads((ROOT / "tests/data/router_diagnosis.json").read_text(encoding="utf-8"))


def test_the_corpus_has_sixty_entries_with_six_phrasings_and_short_answers():
    es = faq.entries()
    assert len(es) >= 60 and len({e[0] for e in es}) == len(es)
    for eid, qs, ans, screen in es:
        assert len(qs) >= 6, eid
        assert len(ans.split()) <= 60, (eid, len(ans.split()))
        assert screen


def test_most_phrasings_retrieve_their_own_entry():
    total = hit = 0
    for eid, qs, ans, _ in faq.entries():
        if eid == "scope":
            continue
        for q in qs:
            total += 1
            r = faq.answer(q)
            hit += bool(r and r[0] == ans)
    assert hit / total >= 0.9, (hit, total)


def test_digits_and_noise_never_match():
    for q in ("12345", "", "   ", "blah", "asdfgh"):
        assert faq.answer(q) is None


def test_the_generic_fallback_strings_are_gone_from_the_router_code():
    for f in ("oasis/agent/chat.py", "oasis/agent/robust.py", "oasis/agent/router_v2.py"):
        p = ROOT / f
        if p.exists():
            t = p.read_text(encoding="utf-8")
            assert "I didn't catch that" not in t and "I'm not sure what you mean" not in t, f


def test_no_clear_question_from_the_diagnosis_ends_in_a_menu_or_a_dead_end():
    c = new_client("student")
    for m in DIAG["dead_end_on_clear_questions"] + DIAG["followups"]:
        c.post("/api/reset")
        j = c.post("/api/chat", json={"message": m}).json()
        r = j["reply"]
        assert "Did you mean" not in r and "I didn't catch" not in r and "I'm not sure what you mean" not in r and not re.search(r"\b1\) .*\b2\) ", r), (m, r)
        assert j["money_moved"] == 0 and j["intent"] != "clarify", m


def test_scam_and_safety_questions_get_an_answer():
    c = new_client("student")
    for m, word in (("how do I know this isn't a scam", "gift cards"), ("what happens if I get hacked", "signature"),
                    ("is it safe to give you my bank details", "registered payees")):
        c.post("/api/reset")
        r = c.post("/api/chat", json={"message": m}).json()["reply"]
        assert word in r and "No warning signs" not in r, (m, r)
