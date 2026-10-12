"""Payment Reliability Record + currency view. Hermetic: in-memory worlds, no network."""
import copy

import pytest
from auth_helpers import Approver, new_client
from fastapi.testclient import TestClient

from eval.approver import SimulatedHumans
from eval.scenarios import rent, tuition
from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.passport.currency import currency_view
from oasis.proof.reliability import (RECORD_TYPE, _canon, amount_band, build_reliability_record, eligible_payments,
                                     verify_reliability_record)
from oasis.trust.crypto import HybridSigner, canonical, sha256_hex
from oasis.trust.keystore import fingerprint
from oasis.world import Features, World


def _world():
    w = World(Features.full(), OfflineLLM(susceptible=True))
    w.ledger.accounts["acct_student_cny"].balance += 100000      # enough CNY for tuition and rent without a conversion step
    w.sync_balances()
    return w, OasisAgent(w)


def _paid_world(*, late_tuition=False):
    w, a = _world()
    assert a.handle(Request(rent()), SimulatedHumans()).status == "paid"
    if late_tuition:
        w.advance(days=40)                                   # simulated clock: 2026-11-21, past the 2026-11-15 due date
    assert a.handle(Request(tuition()), SimulatedHumans()).status == "paid"
    return w, a


def _check(w, rec, **kw):
    return verify_reliability_record(rec, {w.trust_fingerprint()}, lambda pid: w.proofs.get(pid), **kw)


def test_genuine_record_verifies_with_proofs():
    w, _ = _paid_world()
    rec = build_reliability_record(w, share_amounts=True)
    assert rec["type"] == RECORD_TYPE and rec["summary"]["payments"] == 2 and rec["summary"]["on_time"] == 2
    assert rec["summary"]["total_cny"] == 36000
    r = _check(w, rec)
    assert r["ok"] and r["signature"] and r["key_pinned"] and r["proofs_checked"] is True
    assert any("not a credit score" in c for c in rec["caveats"]) and any("SANDBOX" in c for c in rec["caveats"])


def test_record_survives_a_json_round_trip_through_a_browser():
    """A browser re-saves 30000.0 as 30000; the record must still verify."""
    import json
    w, _ = _paid_world()
    rec = build_reliability_record(w, share_amounts=True)
    rec["payments"][0]["amount_cny"] = float(rec["payments"][0]["amount_cny"])
    text = json.dumps(rec).replace("30000.0", "30000").replace("6000.0", "6000").replace("1.0,", "1,")
    assert "30000.0" not in text
    assert _check(w, json.loads(text))["ok"]


def test_no_pin_or_no_lookup_is_never_a_silent_pass():
    w, _ = _paid_world()
    rec = build_reliability_record(w)
    assert verify_reliability_record(rec, None)["ok"] is False                       # no pinned fingerprint
    r = verify_reliability_record(rec, {w.trust_fingerprint()})                      # signature fine, proofs NOT cross-checked
    assert r["ok"] and r["proofs_checked"] is None


@pytest.mark.parametrize("edit", [
    lambda r: r["payments"][0].update(amount_cny=1.0),
    lambda r: r["payments"][0].update(paid_date="2026-10-01"),
    lambda r: r["payments"][0].update(proof_id="int_9999"),
    lambda r: r["payments"][0].update(intent_hash="0" * 64),
    lambda r: r["payments"][0].update(on_time=False),
    lambda r: r["summary"].update(on_time=0),
    lambda r: r["student"].update(name="Someone Else"),
    lambda r: r.pop("signatures"),
])
def test_edited_record_fails(edit):
    w, _ = _paid_world()
    rec = build_reliability_record(w, share_amounts=True)
    bad = copy.deepcopy(rec)
    edit(bad)
    assert _check(w, bad)["ok"] is False


def test_entry_that_disagrees_with_its_proof_pack_fails_even_if_resigned_by_the_server():
    w, _ = _paid_world()
    rec = build_reliability_record(w, share_amounts=True)
    forged = copy.deepcopy(rec)
    for k in ("signatures", "public_keys", "record_hash"):
        forged.pop(k)
    forged["payments"][0]["amount_cny"] = 99.0
    forged["summary"]["total_cny"] = round(sum(e["amount_cny"] for e in forged["payments"]), 2)
    forged["record_hash"] = sha256_hex(_canon(forged))
    forged["signatures"] = w.signer.sign(_canon(forged))
    forged["public_keys"] = w.signer.public_keys()
    # signed by the real key over a hash-consistent body, so only the proof pack cross-check can catch it
    r = _check(w, forged)
    assert r["signature"] and r["key_pinned"] and r["record_hash"] and r["proofs_checked"] is False and not r["ok"]


def test_fresh_key_resign_fails_the_pin():
    w, _ = _paid_world()
    fake = build_reliability_record(w, signer=HybridSigner())          # an attacker's own keys, otherwise a perfect record
    r = _check(w, fake)
    assert r["signature"] and r["fingerprint_matches"] and r["key_pinned"] is False and not r["ok"]
    assert fingerprint(fake["public_keys"]) != w.trust_fingerprint()


def test_late_payment_shows_on_time_false():
    w, _ = _paid_world(late_tuition=True)
    rec = build_reliability_record(w)
    by = {e["obligation_type"]: e for e in rec["payments"]}
    assert by["rent"]["on_time"] is True
    assert by["tuition"]["on_time"] is False and by["tuition"]["paid_date"] > by["tuition"]["due_date"]
    assert rec["summary"]["late"] == 1 and rec["summary"]["on_time_share"] == 0.5
    assert _check(w, rec)["ok"]
    flipped = copy.deepcopy(rec)
    next(e for e in flipped["payments"] if e["obligation_type"] == "tuition")["on_time"] = True
    assert not _check(w, flipped)["ok"]


def test_unpaid_frozen_rejected_and_duplicate_payments_never_listed():
    w, a = _world()
    assert build_reliability_record(w)["payments"] == []                          # nothing paid yet
    assert a.handle(Request(tuition("6228480000009999")), SimulatedHumans()).status == "rejected"   # forged account
    assert a.handle(Request(tuition(), tool_poison={"account_ref": "6666000000000002"}), SimulatedHumans()).status == "frozen"
    assert build_reliability_record(w)["payments"] == []
    w2, a2 = _world()
    first = a2.handle(Request(tuition()), SimulatedHumans())
    assert first.status == "paid"
    assert a2.handle(Request(tuition()), SimulatedHumans()).status == "held"      # duplicate: not paid, not listed
    rec = build_reliability_record(w2)
    assert [e["proof_id"] for e in rec["payments"]] == [first.proof_id]


def test_payment_with_a_tampered_or_missing_proof_is_not_listed():
    w, _ = _paid_world()
    ids = list(w.proofs)
    assert len(eligible_payments(w)) == 2
    w.proofs[ids[0]]["intent"]["amount"] = 1.0                                    # pack tampered in the store
    assert {e["proof_id"] for e in build_reliability_record(w)["payments"]} == {ids[1]}
    w.proofs.pop(ids[1])                                                          # pack missing
    assert build_reliability_record(w)["payments"] == []


def test_privacy_options_name_and_amounts():
    w, _ = _paid_world()
    default = build_reliability_record(w)
    assert "name" not in default["student"] and default["student"]["pseudonym"].startswith("stu_")
    assert "Arjun" not in str(default) and "stu_001" not in str(default)
    assert all("amount_cny" not in e and e["amount_band"] for e in default["payments"]) and "total_cny" not in default["summary"]
    assert "30000" not in str(default["payments"]) and any(e["amount_band"] == "CNY 20,000 to 49,999" for e in default["payments"])
    opt = build_reliability_record(w, include_name=True, share_amounts=True)
    assert opt["student"]["name"] == "Arjun" and {e["amount_cny"] for e in opt["payments"]} == {6000, 30000}
    assert default["student"]["pseudonym"] == opt["student"]["pseudonym"]
    assert _check(w, default)["ok"] and _check(w, opt)["ok"]
    assert amount_band(999) == "under CNY 1,000" and amount_band(50000) == "CNY 50,000 or more"


@pytest.mark.parametrize("junk", [None, 5, "x", [], {}, {"type": RECORD_TYPE},
                                  {"type": RECORD_TYPE, "payments": 3, "public_keys": {}, "signatures": {}},
                                  {"type": RECORD_TYPE, "payments": [1, 2], "public_keys": {"a": 1}, "signatures": {"a": 2}}])
def test_verify_never_raises(junk):
    r = verify_reliability_record(junk, {"abc"}, lambda p: None)
    assert r["ok"] is False


# ---------------------------------------------------------------------------------------------- API
def _paid_api(c):
    me = Approver(c, "student")
    for text in (rent(), tuition()):
        o = c.post("/api/intake", json={"text": text}).json()
        if o["status"] == "held":
            o = me.approve(o["pending_id"]).json()
        assert o["status"] == "paid", o


def test_api_create_download_verify_and_tamper(api_client, api_session):
    api_session.S.world.ledger.accounts["acct_student_cny"].balance += 100000
    api_session.S.world.sync_balances()
    _paid_api(api_client)
    assert api_client.get("/api/reliability/mine").json() == {"record": None, "eligible_payments": 2}
    rec = api_client.post("/api/reliability/record", json={}).json()
    assert rec["summary"]["payments"] == 2 and "name" not in rec["student"] and "total_cny" not in rec["summary"]
    assert api_client.get("/api/reliability/mine").json()["record"] == rec
    anon = TestClient(api_client.app)
    v = anon.post("/api/reliability/verify", json=rec).json()                  # public: no login
    assert v["ok"] and v["proofs_checked"] is True
    bad = copy.deepcopy(rec)
    bad["payments"][0]["payee_type"] = "family"
    assert not anon.post("/api/reliability/verify", json=bad).json()["ok"]
    full = api_client.post("/api/reliability/record", json={"include_name": True, "share_amounts": True}).json()
    assert full["student"]["name"] == "Arjun" and anon.post("/api/reliability/verify", json=full).json()["ok"]


def test_api_roles(api_session):
    for role in ("parent", "judge"):
        c = new_client(role)
        assert c.post("/api/reliability/record", json={}).status_code == 403
        assert c.get("/api/reliability/mine").status_code == 403
    assert TestClient(api_session.app).post("/api/reliability/record", json={}).status_code == 401
    assert TestClient(api_session.app).get("/api/reliability/mine").status_code == 401
    assert new_client("student").post("/api/reliability/record", json={"include_name": "maybe", "x": 1}).status_code == 422


@pytest.mark.parametrize("body", [[], "x", 5, None, {}, {"type": RECORD_TYPE}, {"payments": "x"},
                                  {"type": RECORD_TYPE, "payments": [{"proof_id": 7}] * 50, "public_keys": {"ed25519": "zz"},
                                   "signatures": {"ed25519": 1}},
                                  {"x": [[[[[[[[1]]]]]]]] * 100}])
def test_api_verify_garbage_never_500(api_session, body):
    r = TestClient(api_session.app, raise_server_exceptions=False).post("/api/reliability/verify", json=body)
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert r.json()["ok"] is False


def test_api_verify_unpaired_surrogate_never_500(api_session):
    r = TestClient(api_session.app, raise_server_exceptions=False).post(
        "/api/reliability/verify", content=rb'{"type":"x","payments":["\ud800"]}', headers={"content-type": "application/json"})
    assert r.status_code in (200, 422)


def test_api_verify_oversized_body_is_refused(api_session):
    r = TestClient(api_session.app).post("/api/reliability/verify", content=b'{"a":"' + b"x" * 2_100_000 + b'"}',
                                         headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_api_verify_deeply_nested_json_never_500(api_session):
    deep = "[" * 3000 + "]" * 3000
    r = TestClient(api_session.app, raise_server_exceptions=False).post(
        "/api/reliability/verify", content=('{"type":"%s","payments":%s}' % (RECORD_TYPE, deep)).encode(),
        headers={"content-type": "application/json"})
    assert r.status_code != 500


# ---------------------------------------------------------------------------------------------- currency view
def test_currency_view_values_and_exposure():
    w, _ = _world()
    p = w.passport
    p.set_balance("INR", 100000)
    p.set_balance("CNY", 5000)
    v = currency_view(p, 0.07, {"source": "MOCK", "label": "MOCK rate"})
    assert v["supported"] == ["INR", "CNY", "USD", "EUR", "GBP", "AUD"] and v["rate_source"] == "MOCK"
    assert v["total_cny"] == 12000 and abs(v["total_inr"] - (100000 + 5000 / 0.07)) < 0.02
    assert v["exposure_pct"] == {"INR": 58.3, "CNY": 41.7, "USD": 0.0, "EUR": 0.0, "GBP": 0.0, "AUD": 0.0}
    assert [h["currency"] for h in v["holdings"]][:2] == ["INR", "CNY"]
    p.set_balance("INR", 0)
    p.set_balance("CNY", 0)
    z = currency_view(p, 0.07)
    assert z["total_cny"] == 0 and set(z["exposure_pct"].values()) == {0.0}


def test_state_carries_currency_view(api_client):
    s = api_client.get("/api/state").json()
    cv = s["currency_view"]
    assert cv["supported"][:2] == ["INR", "CNY"] and cv["rate_cny_per_inr"] == s["rate_mid"]
    assert abs(sum(cv["exposure_pct"].values()) - 100) < 0.5 and "coverage" in cv
    assert cv["rate_label"] == s["rates"]["label"]
