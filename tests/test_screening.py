"""Sanctions screening and bank-identifier checks (public data, evidence only)."""
from oasis.agent.llm import heuristic_risk
from oasis.screening import Sanctions, cn_card_check, ifsc_check, luhn_ok, sanctions, screen_payee


def test_snapshot_loads_and_records_provenance():
    s = sanctions()
    assert s.available and s.meta["count"] > 10000 and s.meta["retrieved"] and "OFAC" in s.meta["source"]


def test_demo_payees_do_not_match():
    for n in ("Chen Wei", "University X Finance Office", "Arjun (own CNY account)", "Universiity X Finance Office"):
        assert sanctions().screen(n) == [], n


def test_known_entity_matches_even_with_case_and_order():
    h = sanctions().screen("university of technology malek ashtar")
    assert h and h[0]["type"] == "entity" and h[0]["score"] >= 0.9


def test_missing_file_is_not_an_error(tmp_path):
    s = Sanctions(tmp_path / "none.gz")
    assert not s.available and s.screen("anything") == []


def test_entity_hit_raises_risk_to_review_individual_hit_does_not_alone():
    ent = {"type": "entity", "name": "MAHAN AIR", "score": 1.0}
    ind = {"type": "individual", "name": "ZHANG, Wei", "score": 1.0}
    f = {"payee_name": "Mahan Air", "amount": 100.0}
    e = heuristic_risk(f, "x", [], {}, None, {"sanctions_hits": [ent]})
    i = heuristic_risk(f, "x", [], {}, None, {"sanctions_hits": [ind]})
    assert e.score >= 0.5 and any("OFAC" in m for m in e.evidence)
    assert 0 < i.score < 0.5                         # a common name alone does not trigger a hold


def test_card_and_ifsc_checks():
    assert luhn_ok("4539578763621486") and not luhn_ok("4539578763621487")
    c = cn_card_check("6228 4800 0000 1234")
    assert c["length_ok"] and c["issuer_prefix"] == "Agricultural Bank of China"
    assert not cn_card_check("12345")["length_ok"]
    assert ifsc_check("hdfc0000001")["format_ok"] and not ifsc_check("HDFC1000001")["format_ok"]


def test_screen_endpoint_needs_login_and_returns_caveat(api_client):
    r = api_client.post("/api/screen", json={"name": "Mahan Air", "account": "6228480000001234", "ifsc": "HDFC0000001"})
    assert r.status_code == 200
    j = r.json()
    assert j["sanctions"]["hits"] and "not a clearance" in j["sanctions"]["caveat"] and j["card"]["luhn_ok"] in (True, False)
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    assert TestClient(api.app).post("/api/screen", json={"name": "x"}).status_code == 401


def test_pipeline_unchanged_for_demo_payees():
    assert screen_payee("Chen Wei")["sanctions"]["hits"] == []
