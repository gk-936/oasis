import copy
from datetime import timedelta

import pytest

from oasis.mock.registry import VerifiedPayeeRegistry
from oasis.passport.models import Level, Recipient
from oasis.trust import corridor
from oasis.trust.audit import AuditLog, verify_chain
from oasis.trust.canaries import Canaries
from oasis.trust.crypto import Ed25519Signer, HybridSigner, MLDSA65Signer, canonical, verify_hybrid
from oasis.trust.intents import IntentBuilder, check_intent
from oasis.trust.policy import PolicyInput, decide
from oasis.trust.verification import LOW_LIMIT_CNY, Verifier
from oasis.world import Features, World, LANDLORD_ACCT, LANDLORD_ACCT_NEW, UNIV_ACCT


# ---------------------------------------------------------------- crypto
def test_each_signer_roundtrip():
    for s in (Ed25519Signer(), MLDSA65Signer()):
        sig = s.sign(b"m")
        assert s.verify(b"m", sig) and not s.verify(b"x", sig)


def test_hybrid_requires_both_signatures():
    h = HybridSigner()
    m = canonical({"a": 1})
    sigs = h.sign(m)
    assert h.verify(m, sigs)
    assert not h.verify(m, {"ed25519": sigs["ed25519"]})            # PQ part missing
    assert not h.verify(m, {**sigs, "ml-dsa-65": sigs["ed25519"]})  # PQ part invalid
    assert not h.verify(canonical({"a": 2}), sigs)


def test_standalone_verifier_with_public_keys_only():
    h = HybridSigner()
    m = canonical({"x": "y"})
    assert verify_hybrid(m, h.sign(m), h.public_keys())
    assert not verify_hybrid(m, h.sign(m), HybridSigner().public_keys())


# ---------------------------------------------------------------- audit
def test_audit_chain_detects_edit_and_reports_first_broken_link():
    log = AuditLog()
    for i in range(5):
        log.append("evt", {"n": i})
    assert verify_chain(log.entries).ok
    tampered = copy.deepcopy(log.entries)
    tampered[2]["data"]["n"] = 99
    r = verify_chain(tampered)
    assert not r.ok and r.first_broken == 2
    deleted = copy.deepcopy(log.entries)
    del deleted[1]
    assert not verify_chain(deleted).ok


# ---------------------------------------------------------------- verification ramp
def _world():
    return World(Features.full())


def test_forged_account_is_rejected_and_genuine_record_untouched():
    w = _world()
    v = Verifier(w.registry)
    out = v.assess(w.passport, payee_id="payee_univ_x", name="University X Finance Office", account_ref="6228480000009999")
    assert out.level == Level.REJECTED
    assert w.passport.recipients["payee_univ_x"].verification.level == Level.VERIFIED_FULL
    assert w.passport.recipients["payee_univ_x"].account_ref == UNIV_ACCT


def test_legitimate_change_ramps_instead_of_blocking():
    w = _world()
    w.registry.issue("payee_landlord_chen", "Chen Wei", "landlord", LANDLORD_ACCT_NEW)
    v = Verifier(w.registry)
    out = v.assess(w.passport, payee_id=None, name="Chen Wei", account_ref=LANDLORD_ACCT_NEW)
    assert out.account_changed and out.level == Level.REGISTRY_CHECKED and out.needs_test_payment
    out = v.confirm_test_payment(w.passport, "payee_landlord_chen")
    rec = w.passport.recipients["payee_landlord_chen"]
    assert rec.verification.level == Level.VERIFIED_LOW and rec.verification.limit_cny == LOW_LIMIT_CNY
    Verifier.record_success(w.passport, "payee_landlord_chen")
    Verifier.record_success(w.passport, "payee_landlord_chen")
    assert rec.verification.level == Level.VERIFIED_FULL


def test_lookalike_name_does_not_resolve():
    reg = VerifiedPayeeRegistry()
    reg.issue("p1", "University X Finance Office", "university", "A1")
    assert reg.lookup_by_name("Universiity X Finance Office") is None
    assert reg.lookup_by_name("university x finance office").payee_id == "p1"


# ---------------------------------------------------------------- policy
def _pi(w, **k):
    rec = k.pop("rec", w.passport.recipients["payee_univ_x"])
    base = dict(passport=w.passport, recipient=rec, payee_id=rec.id if rec else "x", purpose="tuition",
                amount_cny=30000, amount_inr=355000, corridor=corridor.CorridorResult())
    base.update(k)
    return PolicyInput(**base)


def test_policy_rules():
    w = _world()
    assert decide(_pi(w)).rule == "R11_approval_required"
    assert decide(_pi(w, approvals=("student",))).action == "allow"
    assert decide(_pi(w, approvals=("student",), risk_score=0.9)).action == "freeze"       # risk escalates only
    assert decide(_pi(w, approvals=("student",), risk_score=0.6)).action == "hold"
    assert decide(_pi(w, amount_cny=500000, approvals=("student",))).rule == "R02_hard_limit"
    from oasis.trust.canaries import CanaryHit
    assert decide(_pi(w, canary_hits=[CanaryHit("decoy_payee", "x", "t")])).action == "freeze"
    unver = Recipient(id="n", name="n", payee_type="university", account_ref="a")
    assert decide(_pi(w, rec=unver, approvals=("student",))).rule == "R05_unverified"
    # family transfer above the co-approval threshold needs the parent too
    fam = w.passport.recipients["payee_student_self"]
    d = decide(_pi(w, rec=fam, purpose="family_support", amount_cny=6000, amount_inr=70000, approvals=("student",)))
    assert d.action == "hold" and d.required_approvals == ["parent"]
    # tier 1: small recurring payment to a fully verified recipient
    ll = w.passport.recipients["payee_landlord_chen"]
    assert decide(_pi(w, rec=ll, purpose="rent", amount_cny=300, amount_inr=3500, recurring=True)).tier == 1


def test_policy_is_deterministic():
    w = _world()
    assert decide(_pi(w)).to_dict() == decide(_pi(w)).to_dict()


# ---------------------------------------------------------------- intents + executor
def _intent(w, **over):
    b = dict(student_id="stu_001", payee_id="payee_univ_x", account_ref=UNIV_ACCT, amount=100.0, currency="CNY",
             purpose="tuition", route_id="r", not_after=(w.now + timedelta(hours=2)).isoformat(), tier=2,
             approvals=[{"role": "student"}])
    b.update(over)
    return w.builder.build(**b)


def test_intent_check_mismatch_replay_expiry():
    w = _world()
    it = _intent(w)
    payload = {k: it[k] for k in ("payee_id", "account_ref", "amount", "currency", "route_id")}
    assert check_intent(w.signer, it, payload, w.now_iso(), set()).ok
    bad = check_intent(w.signer, it, {**payload, "account_ref": "6666"}, w.now_iso(), set())
    assert not bad.ok and any("account_ref" in r for r in bad.reasons)
    assert not check_intent(w.signer, it, payload, w.now_iso(), {it["nonce"]}).ok
    late = (w.now + timedelta(days=1)).isoformat()
    assert not check_intent(w.signer, it, payload, late, set()).ok
    forged = {**it, "amount": 99999.0}
    assert "signature invalid" in check_intent(w.signer, forged, {**payload, "amount": 99999.0}, w.now_iso(), set()).reasons


def test_executor_refuses_replay_after_success():
    w = _world()
    w.ledger.accounts["acct_student_cny"].balance = 1000
    it = _intent(w)
    payload = {k: it[k] for k in ("payee_id", "account_ref", "amount", "currency", "route_id")}
    allow = lambda: decide(_pi(w, amount_cny=100, approvals=("student",)))
    assert w.executor.execute(it, payload, allow, "acct_student_cny").ok
    assert w.executor.execute(it, payload, allow, "acct_student_cny").status == "frozen"
    assert len(w.ledger.transfers) == 1


# ---------------------------------------------------------------- canaries + corridor
def test_canaries_fire_only_on_decoys():
    c = Canaries.plant("aa")
    assert not c.scan({"account_ref": UNIV_ACCT}, "x")
    tok = next(iter(c.decoy_tokens))
    hits = c.scan({"tool_calls": [tok]}, "understand")
    assert hits and hits[0].kind == "decoy_credential" and c.tripped


def test_corridor_tcs_lrs_split_and_purpose():
    w = _world()
    p = w.passport
    p.remitted_inr_fy["student"] = 950000
    r = corridor.check(p, payee_type="university", purpose="tuition", amount_cny=10000, amount_inr=118000)
    tcs = [f for f in r.findings if f.rule == "tcs"]
    assert tcs and tcs[0].data["tcs_inr"] == pytest.approx((950000 + 118000 - 1000000) * 0.02)
    p.funding_source = "education_loan"
    assert not [f for f in corridor.check(p, payee_type="university", purpose="tuition", amount_cny=1,
                                          amount_inr=118000).findings if f.rule == "tcs"]
    p.remitted_inr_fy["student"] = 250000 * 88
    assert any(f.rule == "lrs_limit" for f in corridor.check(p, payee_type="university", purpose="tuition",
                                                             amount_cny=1, amount_inr=1000).holds)
    assert any(f.rule == "purpose_payee_mismatch" for f in corridor.check(p, payee_type="landlord", purpose="tuition",
                                                                          amount_cny=1, amount_inr=1).holds)
    hist = [{"payee_id": "s", "amount_cny": 4000, "amount_inr": 48000, "ts": 0}]
    r = corridor.check(p, payee_type="student", purpose="family_support", amount_cny=4000, amount_inr=48000,
                       remitter="parent", history=hist, payee_id="s", now_ts=3600)
    assert any(f.rule == "split_payments" for f in r.holds)
