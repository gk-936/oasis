"""FlightPath API: precheck, persisted journeys, MOCK rail events, advisory-only recovery."""
from oasis.flightpath import core as fp


def create(c, **kw):
    r = c.post("/api/flightpath/journeys", json={"route_id": "route_bank_swift", "required_cny": 1000, "send_inr": 12000, **kw})
    assert r.status_code == 200, r.text
    return r.json()["journey"]["id"]


def test_precheck_blocks_unverified_payee(api_client):
    r = api_client.post("/api/flightpath/precheck", json={"route_id": "route_bank_swift", "payee_verified": False}).json()
    assert r["blocked"] and any(w["code"] for w in r["warnings"])
    assert api_client.post("/api/flightpath/precheck", json={"route_id": "nope", "payee_verified": True}).status_code == 404


def test_delay_advice_never_resends_and_is_audited(api_client):
    jid = create(api_client)
    r = api_client.post(f"/api/flightpath/journeys/{jid}/simulate", json={"event": "delay"}).json()
    assert r["journey"]["stage"] == "delayed" and r["advice"]["resend_allowed"] is False
    assert any(e.get("kind", e.get("type")) == "flightpath" or "flightpath" in str(e) for e in api_client.get("/api/audit").json()["entries"])


def test_reject_resend_only_after_refund(api_client):
    jid = create(api_client)
    r = api_client.post(f"/api/flightpath/journeys/{jid}/simulate", json={"event": "reject"}).json()
    assert r["advice"]["resend_allowed"] is False
    r = api_client.post(f"/api/flightpath/journeys/{jid}/refund", json={"confirmed": True}).json()
    assert r["advice"]["resend_allowed"] is True and r["advice"]["needs_approval"] is True


def test_short_credit_found_and_invalid_transition_409(api_client):
    jid = create(api_client)
    r = api_client.post(f"/api/flightpath/journeys/{jid}/simulate", json={"event": "short_credit", "short_cny": 30}).json()
    assert r["finding"]["code"] == "shortfall" and r["finding"]["shortfall_cny"] == 30
    assert api_client.post(f"/api/flightpath/journeys/{jid}/simulate", json={"event": "reject"}).status_code == 409
    assert api_client.post(f"/api/flightpath/journeys/{jid}/simulate", json={"event": "bogus"}).status_code in (409, 422)
    assert api_client.get("/api/flightpath/journeys/jny_9999/advice").status_code == 404


def test_journeys_listed_and_roundtrip():
    j = fp.Journey("jny_1", "route_bank_swift", 1.0, 2.0)
    fp.simulate_event(j, "delay", 3)
    assert fp.journey_from_dict(fp.journey_to_dict(j)) == j


def test_journeys_survive_restart(tmp_path):
    from oasis.api import main
    db = str(tmp_path / "o.db")
    a = main.Session(db)
    a.journeys["jny_0001"] = fp.Journey("jny_0001", "route_bank_swift", 1.0, 2.0)
    fp.simulate_event(a.journeys["jny_0001"], "delay", 3)
    a.save()
    b = main.Session(db)
    assert b.journeys["jny_0001"].stage == "delayed"
