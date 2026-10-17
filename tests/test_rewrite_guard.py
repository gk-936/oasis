"""A model rewrite of a deterministic explanation is shown only when it keeps every number, adds none, and is plain text. Found by the first live
Nova Pro run: a rewrite came back with a chatty preface, bold markdown, a numbered list and a number that was only list numbering."""
import pytest

from oasis.agent import i18n
from oasis.agent.llm import LiveLLM
from tests.test_llm_live import FakeClient

T = "Tuition is due in 8 days. Ask the provider today. Safe for up to 3 days."


@pytest.mark.parametrize("rewrite,ok", [
    ("Your tuition is due in 8 days, so ask the provider today; waiting is safe for up to 3 days.", True),
    ("学费将在 8 天后到期，请今天联系服务商；最多可以等待 3 天。", True),
    ("Here is a more natural rewrite: Your tuition is due in 8 days. Ask today. Safe for up to 3 days.", False),
    ("Here's a rewrite of the draft:\n\nTuition is due in 8 days. Ask today. Safe for up to 3 days.", False),
    ("Tuition is due in 8 days.\n1. Ask the provider today.\n2. Waiting is safe for up to 3 days.", False),
    ("- Tuition is due in 8 days\n- Ask the provider today\n- Safe for up to 3 days", False),
    ("Tuition is **due in 8 days**. Ask today. Safe for up to 3 days.", False),
    ("Tuition is due in 8 days. Ask the provider today. Safe for up to 3 days, maybe 5.", False),     # an added number
    ("Tuition is due soon. Ask the provider today. Safe for up to 3 days.", False),                  # a dropped number
])
def test_guard_accepts_only_plain_rewrites_with_exactly_the_same_numbers(tmp_path, rewrite, ok):
    llm = LiveLLM(client=FakeClient([rewrite]), cache_dir=tmp_path, rpm=0)
    out = llm.explain("flightpath", {"text": T}, "en")
    assert (out == rewrite) is ok and (ok or out == T)


def test_the_prompt_asks_for_plain_text_only(tmp_path):
    fake = FakeClient(["x"])
    LiveLLM(client=fake, cache_dir=tmp_path, rpm=0).explain("flightpath", {"text": T}, "en")
    system = fake.calls[0]["messages"][0]["content"]
    assert "no markdown" in system and "no preface" in system and "numbered lists" in system and "Do not add facts or numbers" in system


def test_helper_functions():
    assert i18n.no_new_numbers("pay 1,000 on day 3", "pay 1000 on day 3") and not i18n.no_new_numbers("pay 1,000", "pay 1,000 on day 3")
    assert i18n.plain_rewrite("Two plain sentences. Nothing else.") and not i18n.plain_rewrite("Sure, here you go.")
