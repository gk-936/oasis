"""F3: the offline parser reads a sentence, not only `Label:` lines, and stays safe: exact registry names, nothing guessed."""
import pytest

from eval.approver import SimulatedHumans
from oasis.agent import nl_extract
from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.world import Features, World


def run(text, features=None):
    w = World(features or Features.full(), OfflineLLM(susceptible=True))
    return w, OasisAgent(w).handle(Request(text), SimulatedHumans())


@pytest.mark.parametrize("text,amount,cur", [
    ("CNY 6000", 6000, "CNY"), ("6000 yuan", 6000, "CNY"), ("¥6,000", 6000, "CNY"), ("6k RMB", 6000, "CNY"), ("6000元", 6000, "CNY"),
    ("六千元", 6000, "CNY"), ("三万元", 30000, "CNY"), ("一万二千元", 12000, "CNY"), ("两千五百元", 2500, "CNY"), ("3万元", 30000, "CNY"),
    ("INR 50,000", 50000, "INR"), ("5 lakh", 500000, "INR"), ("RMB 1,234.50", 1234.5, "CNY"), ("人民币 800", 800, "CNY"),
])
def test_amounts_in_many_spellings(text, amount, cur):
    assert nl_extract.money(f"please pay {text} now") == (amount, cur)


@pytest.mark.parametrize("text", ["CNY 6000 and CNY 7000", "pay rent", "6.000 yuan", "1e5 CNY", "pay 2 months of rent", "in 30 days"])
def test_ambiguous_or_missing_amounts_return_nothing(text):
    assert nl_extract.money(text) is None


def test_account_numbers_are_never_read_as_money():
    assert nl_extract.money("send to account 6222021111110001") is None
    assert nl_extract.account_in_text("send CNY 5 to account 6222 0211 1111 0001") == "6222021111110001"
    assert nl_extract.account_in_text("a/c: 6222-0211-1111-0001") == "6222021111110001"


def test_purpose_keywords_and_the_deposit_before_rent_rule():
    assert nl_extract.purpose_in_text("November rent") == "rent"
    assert nl_extract.purpose_in_text("rent deposit") == "deposit"
    assert nl_extract.purpose_in_text("学费") == "tuition" and nl_extract.purpose_in_text("押金") == "deposit"
    assert nl_extract.purpose_in_text("hello") is None


def test_the_evidence_rows_are_now_read_into_fields():
    for t in ("Please pay Chen Wei CNY 6000 for November rent", "Pay rent 6000 yuan to Chen Wei"):
        w, o = run(t)
        assert o.fields["payee_name"] == "Chen Wei" and o.fields["amount"] == 6000 and o.fields["purpose"] == "rent"
        assert o.card["rule"] == "extract_low_confidence"                         # no account in the sentence: asked, never guessed
    w, o = run("Pay rent 6000 yuan to Chen Wei, account 6222020000005678")
    assert o.status == "rejected" and o.card["rule"] == "R03_rejected_recipient" and not w.ledger.transfers


def test_a_sentence_with_the_registered_account_is_paid_like_an_invoice():
    w, o = run("Please pay Chen Wei CNY 6000 for rent, account 6222021111110001")
    assert o.status in ("paid", "held") and o.fields["account_ref"] == "6222021111110001"


def test_purpose_is_inferred_from_the_payee_type_when_the_invoice_omits_it():
    w, o = run("INVOICE\nPayee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\nAmount: CNY 30,000\nDue: 2026-11-15")
    assert o.fields["purpose"] == "tuition" and o.status == "paid"
    w, o = run("INVOICE\nPayee: Chen Wei\nAccount: 6222021111110001\nAmount: CNY 6,000")
    assert o.fields["purpose"] == "rent"


def test_look_alike_names_never_resolve_to_a_registered_payee():
    w, o = run("Please pay Chen Wel CNY 6000 for rent, account 6222021111110001")
    assert o.fields.get("payee_name") != "Chen Wei" and o.status != "paid" and not w.ledger.transfers
    w, o = run("Please pay Universiity X Finance Office CNY 30000, account 6228480000005555")
    assert o.status != "paid" and not w.ledger.transfers


def test_labelled_fields_are_never_overridden_by_the_sentence_around_them():
    f = {"payee_name": "Chen Wei", "amount": 6000.0, "account_ref": "6222021111110001", "purpose": "rent"}
    before = dict(f)
    assert nl_extract.fill_missing(f, "pay CNY 1 to Mallory account 6666000000000002 for tuition", []) == [] and f == before


def test_a_currency_code_is_not_a_payee_name():
    assert nl_extract.unregistered_payee_name("send CNY 5,000 to account 6666000000000004") is None
    assert nl_extract.unregistered_payee_name("pay my rent") is None
    assert nl_extract.unregistered_payee_name("send 5000 to Alice") == "Alice"
