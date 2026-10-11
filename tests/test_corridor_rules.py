"""Corridor TCS cases and the sourced-rules view (data in oasis/trust/rules/inr_cny.yaml). Hermetic."""
import pytest

from oasis.agent.llm import OfflineLLM
from oasis.trust import corridor
from oasis.world import Features, World

LAKH = 100_000


def _p(funding="family"):
    p = World(Features.full(), OfflineLLM()).passport
    p.funding_source = funding
    return p


def _tcs(p, purpose, amount, remitter="student"):
    return corridor.tcs_amount(p, remitter, amount, purpose, corridor.load_rules())


def test_education_self_funded_below_threshold_is_nil():
    p = _p()
    assert _tcs(p, "tuition", 9 * LAKH) == 0.0
    assert _tcs(p, "tuition", 10 * LAKH) == 0.0          # exactly at the threshold: nothing above it


def test_education_self_funded_above_threshold_is_2_percent_of_the_excess():
    p = _p()
    assert _tcs(p, "tuition", 12 * LAKH) == pytest.approx(2 * LAKH * 0.02)


def test_education_loan_is_nil_even_above_threshold():
    p = _p("education_loan")
    assert _tcs(p, "tuition", 30 * LAKH) == 0.0
    assert corridor.tcs_rate(p, "tuition", corridor.load_rules())["category"] == "education_loan"


@pytest.mark.parametrize("purpose", ["rent", "deposit", "living", "family_support"])
def test_non_education_is_20_percent_above_threshold(purpose):
    p = _p()
    assert _tcs(p, purpose, 9 * LAKH) == 0.0
    assert _tcs(p, purpose, 12 * LAKH) == pytest.approx(2 * LAKH * 0.20)


def test_loan_funding_does_not_make_rent_nil():
    p = _p("education_loan")
    assert _tcs(p, "rent", 11 * LAKH) == pytest.approx(1 * LAKH * 0.20)


def test_remitter_cumulative_threshold_crossing_taxes_only_the_part_above():
    p = _p()
    p.remitted_inr_fy["parent"] = 9 * LAKH + 50_000
    # 150,000 more: 50,000 stays under the threshold, 100,000 is above it
    assert _tcs(p, "family_support", 150_000, "parent") == pytest.approx(100_000 * 0.20)
    assert _tcs(p, "tuition", 150_000, "parent") == pytest.approx(100_000 * 0.02)
    assert _tcs(p, "tuition", 150_000, "student") == 0.0           # the student's own threshold is separate
    p.remitted_inr_fy["parent"] = 12 * LAKH                        # already over: all of the next amount is taxed
    assert _tcs(p, "family_support", 100_000, "parent") == pytest.approx(100_000 * 0.20)


def test_unconfirmed_tag_is_in_the_finding_for_every_secondary_sourced_rate():
    p = _p()
    for purpose, payee in (("tuition", "university"), ("rent", "landlord")):
        res = corridor.check(p, payee_type=payee, purpose=purpose, amount_cny=1, amount_inr=15 * LAKH)
        f = next(x for x in res.findings if x.rule == "tcs")
        assert "UNCONFIRMED/secondary-sourced" in f.message and f.data["rate_status"] == "researched-secondary"


def test_every_rule_has_source_date_confidence_and_a_valid_status():
    data = corridor.load_rules()
    for rid, row in data["rules"].items():
        rows = [row[k] for k in ("education", "education_loan", "other")] if rid == "tcs_by_purpose" else [row]
        for r in rows:
            assert r["status"] in corridor.STATUSES, rid
            assert len(r["source"].strip()) > 40 and r["retrieved"] == "2026-10-11" and r["confidence"], rid


def test_nothing_unreadable_from_a_primary_source_is_marked_confirmed():
    rules = {r["id"]: r for r in corridor.rules_public()["rules"]}
    for rid in ("tcs_threshold_inr", "tcs_education", "tcs_education_loan", "tcs_other", "wallet_foreign_card_fee"):
        assert rules[rid]["status"] == "researched-secondary", rid
    assert rules["purpose_code_education"]["status"] == "unconfirmed"
    assert rules["lrs_annual_limit_usd"]["status"] == "confirmed-primary" and rules["safe_quota_usd"]["status"] == "confirmed-primary"
    assert "Income-tax Act 2025 s.394" in rules["tcs_other"]["source"] and "7.D(b)" in rules["tcs_other"]["source"]
    assert "Alipay" in rules["wallet_foreign_card_fee"]["source"] and "UNCONFIRMED" in rules["wallet_foreign_card_fee"]["source"]


def test_corridor_rules_endpoint_returns_sources_to_any_role_and_needs_login(api_session, as_role):
    from fastapi.testclient import TestClient
    assert TestClient(api_session.app).get("/api/corridor/rules").status_code == 401
    for role in ("student", "parent", "judge"):
        r = as_role(role).get("/api/corridor/rules")
        assert r.status_code == 200, role
        j = r.json()
        by = {x["id"]: x for x in j["rules"]}
        assert by["tcs_other"]["values"]["rate"] == 0.20 and by["tcs_other"]["status"] == "researched-secondary"
        assert all(x["source"] and x["retrieved"] == "2026-10-11" and x["status"] in j["statuses"] for x in j["rules"])
        assert "confirmed by a bank or counsel" in j["disclaimer"]
