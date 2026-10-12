"""Trust Pass (selective-disclosure payment credential, earned autonomy) and the multi-currency wallet. Hermetic."""
import copy

import pytest

from eval.approver import SimulatedHumans
from eval.scenarios import rent, tuition
from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.mock import fx
from oasis.passport.currency import convert, currency_view
from oasis.proof import trust_pass as cp
from oasis.trust.crypto import HybridSigner
from oasis.world import Features, World


def _paid_world(*, late_tuition=False):
    w = World(Features.full(), OfflineLLM(susceptible=True))
    w.ledger.accounts["acct_student_cny"].balance += 100000
    w.sync_balances()
    a = OasisAgent(w)
    assert a.handle(Request(rent()), SimulatedHumans()).status == "paid"
    if late_tuition:
        w.advance(days=40)
    assert a.handle(Request(tuition()), SimulatedHumans()).status == "paid"
    return w


def _verify(w, pres, today=None):
    return cp.verify_presentation(pres, {w.trust_fingerprint()}, today or w.today.isoformat(), lambda pid: w.proofs.get(pid))


# ---------------------------------------------------------------------------------------------- claims
def test_claims_are_computed_from_verified_payments():
    w = _paid_world()
    c = cp.compute_claims(cp._entries(w), w.today.isoformat())
    assert c["on_time_all"] == {"on_time": 2, "of": 2} and c["on_time_streak"] == {"count": 2}
    assert c["rent_on_time"] == {"on_time": 1, "of": 1} and c["tuition_on_time"] == {"on_time": 1, "of": 1}
    assert c["no_late"] == {"value": True} and c["volume_band"]["band"] == "CNY 20,000 to 49,999"
    assert set(cp.suggested_asks(c)) == {"lower_deposit", "no_guarantor"}


def test_late_payment_breaks_the_streak_and_the_asks():
    w = _paid_world(late_tuition=True)
    c = cp.compute_claims(cp._entries(w), w.today.isoformat())
    assert c["on_time_streak"]["count"] == 0 and c["no_late"]["value"] is False
    assert "no_guarantor" not in cp.suggested_asks(c)
    assert cp.ladder(w)["level"] == 0


# ---------------------------------------------------------------------------------------------- selective disclosure
def test_presentation_with_nothing_revealed_verifies_and_hides_payments():
    w = _paid_world()
    holder = cp.issue(w, ["on_time_all", "no_late"], audience="Landlord, Room 1203")
    cred = holder["credential"]
    assert len(cred["commitments"]) == 2 and "payments" not in cred
    assert "30000" not in str(cred["commitments"])                       # amounts are not in the signed body
    r = _verify(w, cp.present(holder))
    assert r["ok"] and r["hidden"] == 2 and r["revealed"] == [] and r["audience"] == "Landlord, Room 1203"
    assert [x["id"] for x in r["claims"]] == ["on_time_all", "no_late"]


def test_revealing_one_payment_checks_it_against_commitment_and_proof_pack():
    w = _paid_world()
    holder = cp.issue(w, ["rent_on_time"])
    idx = next(i for i, d in enumerate(holder["disclosures"]) if d["entry"]["obligation_type"] == "rent")
    r = _verify(w, cp.present(holder, [idx]))
    assert r["ok"] and r["hidden"] == 1 and r["proofs_checked"] is True and r["revealed"][0]["amount_cny"] == 6000


@pytest.mark.parametrize("edit", [
    lambda p: p["disclosures"][0]["entry"].update(amount_cny=1.0),
    lambda p: p["disclosures"][0]["entry"].update(on_time=False),
    lambda p: p["disclosures"][0].update(salt="00" * 16),
    lambda p: p["disclosures"].append(copy.deepcopy(p["disclosures"][0])),
    lambda p: p["credential"]["claims"][0]["value"].update(on_time=9, of=9),
    lambda p: p["credential"].update(audience="Some other bank"),
    lambda p: p["credential"].update(valid_until="2099-01-01"),
    lambda p: p["credential"].pop("signatures"),
])
def test_tampered_presentation_fails(edit):
    w = _paid_world()
    pres = copy.deepcopy(cp.present(cp.issue(w, ["on_time_all"], audience="Bank A"), [0]))
    edit(pres)
    assert _verify(w, pres)["ok"] is False


def test_expired_credential_fails_and_foreign_key_fails_the_pin():
    w = _paid_world()
    holder = cp.issue(w, ["on_time_all"])
    late = (w.today.fromordinal(w.today.toordinal() + cp.VALID_DAYS + 1)).isoformat()
    assert _verify(w, cp.present(holder), today=late)["not_expired"] is False
    fake = cp.issue(w, ["on_time_all"], signer=HybridSigner())
    r = _verify(w, cp.present(fake))
    assert r["signature"] and r["key_pinned"] is False and not r["ok"]


def test_issue_needs_a_claim_and_garbage_never_raises():
    w = _paid_world()
    with pytest.raises(ValueError):
        cp.issue(w, ["not_a_claim"])
    assert cp.verify_presentation({"credential": 5}, set())["ok"] is False
    assert cp.verify_presentation(None, None)["ok"] is False


# ---------------------------------------------------------------------------------------------- earned autonomy
def test_ladder_proposes_and_only_accept_applies():
    w = _paid_world()
    lv = cp.ladder(w)
    assert lv["level"] == 1 and lv["proposal"] and lv["earned_threshold_inr"] == 75000
    assert w.passport.rules.parent_coapproval_above_inr == 50000                 # proposing changes nothing
    after = cp.accept_ladder(w)
    assert w.passport.rules.parent_coapproval_above_inr == 75000 and not after["proposal"]
    with pytest.raises(ValueError):
        cp.accept_ladder(w)


# ---------------------------------------------------------------------------------------------- multi-currency
def test_currency_view_covers_six_currencies_and_coverage():
    w = _paid_world()
    p = w.passport
    p.set_balance("USD", 1000)
    p.set_balance("EUR", 500)
    v = currency_view(p, 0.0785, {"source": "MOCK"}, w.today)
    assert v["supported"] == ["INR", "CNY", "USD", "EUR", "GBP", "AUD"]
    usd = next(h for h in v["holdings"] if h["currency"] == "USD")
    assert usd["value_cny"] == round(1000 * fx.USD_CNY_SNAPSHOT, 2)
    assert abs(sum(v["exposure_pct"].values()) - 100) < 0.5
    assert set(v["coverage"]) == {"days", "due_cny", "cny_on_hand", "shortfall_cny"}


def test_convert_moves_own_balances_and_the_ledger():
    w = _paid_world()
    w.passport.set_balance("USD", 1000)
    cny_before = w.passport.balance("CNY")
    rec = convert(w, 500, "USD", "CNY")
    assert w.passport.balance("USD") == 500
    assert abs(w.passport.balance("CNY") - (cny_before + rec["received"])) < 0.01
    assert w.ledger.accounts["acct_student_cny"].balance == w.passport.balance("CNY")
    assert w.audit.entries[-1]["kind"] == "fx_conversion"
    with pytest.raises(fx.FxError):
        convert(w, 10_000, "USD", "EUR")                                   # more than held
    with pytest.raises(fx.FxError):
        convert(w, 10, "USD", "JPY")


# ---------------------------------------------------------------------------------------------- API
def test_api_trust_pass_flow_and_roles(api_client, as_role):
    assert api_client.get("/api/trust-pass/claims").status_code == 200
    r = api_client.post("/api/trust-pass/issue", json={"claims": ["on_time_all"], "audience": "Landlord"})
    assert r.status_code == 200
    holder = r.json()
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    v = TestClient(api.app).post("/api/trust-pass/verify", json={"credential": holder["credential"], "disclosures": []}).json()
    assert v["ok"] and v["hidden"] == 0
    assert api_client.post("/api/trust-pass/ladder/accept").status_code == 403                # the student cannot raise their own limit
    parent = as_role("parent")
    assert parent.get("/api/trust-pass/ladder").status_code == 200
    assert parent.post("/api/trust-pass/ladder/accept").status_code == 400                    # nothing earned in a fresh world
    assert api_client.post("/api/trust-pass/issue", json={"claims": []}).status_code == 400


def test_api_fx_quote_and_convert(api_client):
    q = api_client.post("/api/fx/quote", json={"amount": 100, "from": "USD", "to": "EUR"})
    assert q.status_code == 200 and q.json()["received"] > 0
    assert api_client.post("/api/fx/convert", json={"amount": 100, "from": "USD", "to": "CNY"}).status_code == 400  # no USD held
    r = api_client.post("/api/fx/convert", json={"amount": 10000, "from": "INR", "to": "USD"})
    assert r.status_code == 200, r.text
    s = api_client.get("/api/state").json()
    assert next(h for h in s["currency_view"]["holdings"] if h["currency"] == "USD")["amount"] == r.json()["received"]


# ---------------------------------------------------------------------------------------------- differentiators
def test_verified_payee_claim_and_threshold_claims():
    w = _paid_world()
    c = cp.compute_claims(cp._entries(w), w.today.isoformat())
    assert c["verified_payees"] == {"verified": 2, "of": 2}
    opts = cp.threshold_options(c)
    assert {o["at_least"]: o["met"] for o in opts["on_time_pct_min"]} == {80: True, 90: True, 100: True}
    assert {o["at_least"]: o["met"] for o in opts["payments_min"]} == {2: True, 3: False, 6: False, 12: False}
    holder = cp.issue(w, ["verified_payees", "on_time_pct_min", "payments_min"], thresholds={"on_time_pct_min": 90, "payments_min": 2})
    by = {x["id"]: x for x in holder["credential"]["claims"]}
    assert by["on_time_pct_min"]["value"] == {"at_least": 90}                     # exact counts are not in the claim
    assert _verify(w, cp.present(holder))["ok"]
    with pytest.raises(ValueError):
        cp.issue(w, ["payments_min"], thresholds={"payments_min": 6})              # not met: refused, never overstated
    with pytest.raises(ValueError):
        cp.issue(w, ["payments_min"], thresholds={"payments_min": 5})              # not an allowed value


def test_share_store_drops_expired_and_is_bounded():
    w = _paid_world()
    pres = cp.present(cp.issue(w, ["on_time_all"]))
    store = {}
    code = cp.share(store, pres, w.today.isoformat())
    assert store[code]["presentation"] is pres and len(code) >= 12
    cp.share(store, pres, "2099-01-01")                                           # far future: the first share has expired
    assert code not in store and len(store) == 1


def test_api_share_and_public_check(api_client):
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    holder = api_client.post("/api/trust-pass/issue", json={"claims": ["on_time_all"], "audience": "Landlord"}).json()
    pres = {"credential": holder["credential"], "disclosures": []}
    code = api_client.post("/api/trust-pass/share", json={"presentation": pres}).json()["code"]
    public = TestClient(api.app)                                                  # no login: what the QR opens
    r = public.get(f"/api/trust-pass/check/{code}").json()
    assert r["ok"] and r["audience"] == "Landlord"
    assert public.get("/api/trust-pass/check/nope").status_code == 404
    bad = copy.deepcopy(pres)
    bad["credential"]["audience"] = "Someone else"
    assert api_client.post("/api/trust-pass/share", json={"presentation": bad}).status_code == 400
    assert public.post("/api/trust-pass/share", json={"presentation": pres}).status_code == 401
