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


def _rec(level, limit=0.0, payee_type="university"):
    from oasis.passport.models import Verification
    return Recipient(id="r", name="r", payee_type=payee_type, account_ref="a",
                     verification=Verification(level=level, limit_cny=limit))


def _hit():
    from oasis.trust.canaries import CanaryHit
    return CanaryHit("decoy_payee", "x", "t")


def _split_hold(w):
    return corridor.Finding("split_payments", "hold", "split", {"threshold": w.passport.rules.parent_coapproval_above_inr})


def _mismatch_hold():
    return corridor.Finding("purpose_payee_mismatch", "hold", "mismatch")


def _fam(w):
    return w.passport.recipients["payee_student_self"]


def _ll(w):
    return w.passport.recipients["payee_landlord_chen"]


S = ("student",)
POLICY_CASES = [
    # id, kwargs factory, expected action, expected rule
    ("R01_canary", lambda w: dict(canary_hits=[_hit()]), "freeze", "R01_canary"),
    ("R02_hard_limit", lambda w: dict(amount_cny=500000, approvals=S), "freeze", "R02_hard_limit"),
    ("R03_rejected_recipient", lambda w: dict(rec=_rec(Level.REJECTED), approvals=S), "freeze", "R03_rejected_recipient"),
    ("R04_risk_freeze", lambda w: dict(approvals=S, risk_score=0.9), "freeze", "R04_risk_freeze"),
    ("R04b_test_payment_allowed", lambda w: dict(rec=_rec(Level.REGISTRY_CHECKED), purpose="verification_test",
                                                 amount_cny=10, amount_inr=118), "allow", "R04b_test_payment"),
    ("R04c_test_payment_wrong_level", lambda w: dict(purpose="verification_test", amount_cny=5, amount_inr=59),
     "freeze", "R04c_bad_test_payment"),
    ("R04c_test_payment_too_large", lambda w: dict(rec=_rec(Level.REGISTRY_CHECKED), purpose="verification_test",
                                                   amount_cny=10.01, amount_inr=118), "freeze", "R04c_bad_test_payment"),
    ("R05_unverified", lambda w: dict(rec=_rec(Level.UNVERIFIED), approvals=S), "hold", "R05_unverified"),
    ("R06_corridor_hold_goes_to_student", lambda w: dict(corridor=corridor.CorridorResult([_mismatch_hold()])),
     "hold", "R06_corridor"),
    ("R07_over_limit_without_approval", lambda w: dict(rec=_rec(Level.VERIFIED_LOW, 2000)), "hold", "R07_recipient_limit"),
    ("R08_risk_hold", lambda w: dict(approvals=S, risk_score=0.6), "hold", "R08_risk_hold"),
    ("R10_tier1_auto", lambda w: dict(rec=_ll(w), purpose="rent", amount_cny=300, amount_inr=3500, recurring=True),
     "allow", "R10_tier1_auto"),
    ("R11_approval_required", lambda w: dict(), "hold", "R11_approval_required"),
    ("R11_family_needs_parent_too", lambda w: dict(rec=_fam(w), purpose="family_support", amount_cny=6000,
                                                   amount_inr=70000, approvals=S), "hold", "R11_approval_required"),
    ("R12_approved", lambda w: dict(approvals=S), "allow", "R12_approved"),
    ("R07_over_limit_with_approval", lambda w: dict(rec=_rec(Level.VERIFIED_LOW, 2000), approvals=S), "allow", "R12_approved"),
]


@pytest.mark.parametrize("make,action,rule", [pytest.param(m, a, r, id=i) for i, m, a, r in POLICY_CASES])
def test_policy_rule(make, action, rule):
    w = _world()
    d = decide(_pi(w, **make(w)))
    assert (d.action, d.rule) == (action, rule)


def test_policy_family_over_threshold_requires_parent():
    w = _world()
    d = decide(_pi(w, rec=_fam(w), purpose="family_support", amount_cny=6000, amount_inr=70000, approvals=S))
    assert d.required_approvals == ["parent"]
    ok = decide(_pi(w, rec=_fam(w), purpose="family_support", amount_cny=6000, amount_inr=70000, approvals=("student", "parent")))
    assert ok.action == "allow"


def test_policy_r07_names_student_as_approver():
    w = _world()
    d = decide(_pi(w, rec=_rec(Level.VERIFIED_LOW, 2000)))
    assert d.required_approvals == ["student"] and d.tier == 2


def test_policy_r06_routes_to_student_normally_and_parent_for_split_dodge():
    w = _world()
    d = decide(_pi(w, corridor=corridor.CorridorResult([_mismatch_hold()])))
    assert d.rule == "R06_corridor" and d.required_approvals == ["student"]
    d = decide(_pi(w, corridor=corridor.CorridorResult([_split_hold(w)])))
    assert d.rule == "R06_corridor" and d.required_approvals == ["parent"]
    # a split near some OTHER threshold (tier-1 limit) does not need the parent
    other = corridor.Finding("split_payments", "hold", "s", {"threshold": w.passport.rules.tier1_auto_limit_cny})
    assert decide(_pi(w, corridor=corridor.CorridorResult([other]))).required_approvals == ["student"]


def test_policy_risk_only_escalates_never_grants():
    w = _world()
    assert decide(_pi(w, risk_score=0.0)).action == "hold"          # no approval -> still hold, however low the risk
    assert decide(_pi(w, approvals=S, risk_score=0.0)).action == "allow"


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


def _cor(w, **kw):
    base = dict(payee_type="university", purpose="tuition", amount_cny=1, amount_inr=1000)
    base.update(kw)
    return corridor.check(w.passport, **base)


def test_corridor_tcs_applies_only_to_the_part_above_threshold():
    w = _world()
    w.passport.remitted_inr_fy["student"] = 950000
    r = _cor(w, amount_cny=10000, amount_inr=118000)
    tcs = [f for f in r.findings if f.rule == "tcs"]
    assert tcs and tcs[0].data["tcs_inr"] == pytest.approx((950000 + 118000 - 1000000) * 0.02)


def test_corridor_tcs_waived_for_education_loan():
    w = _world()
    w.passport.remitted_inr_fy["student"] = 950000
    w.passport.funding_source = "education_loan"
    assert not [f for f in _cor(w, amount_inr=118000).findings if f.rule == "tcs"]


def test_corridor_lrs_limit_holds():
    w = _world()
    w.passport.remitted_inr_fy["student"] = 250000 * 88
    assert any(f.rule == "lrs_limit" for f in _cor(w).holds)


def test_corridor_purpose_payee_mismatch_holds():
    w = _world()
    assert any(f.rule == "purpose_payee_mismatch" for f in _cor(w, payee_type="landlord").holds)
    assert not _cor(w).holds


def test_corridor_split_payments_hold():
    w = _world()
    hist = [{"payee_id": "s", "amount_cny": 4000, "amount_inr": 48000, "ts": 0}]
    r = corridor.check(w.passport, payee_type="student", purpose="family_support", amount_cny=4000, amount_inr=48000,
                       remitter="parent", history=hist, payee_id="s", now_ts=3600)
    assert any(f.rule == "split_payments" for f in r.holds)


def test_corridor_safe_quota_warning():
    w = _world()
    over = 50000 * corridor.USD_INR + 1
    r = _cor(w, amount_cny=1, amount_inr=over, remitter="parent")
    assert [f.severity for f in r.findings if f.rule == "safe_quota"] == ["warn"]
    assert not [f for f in _cor(w, remitter="parent").findings if f.rule == "safe_quota"]
    assert not any(f.rule == "safe_quota" for f in r.holds)          # a warning, never a hold on its own


# ---------------------------------------------------------------- executor: canary + policy hold
def _payload(it):
    return {k: it[k] for k in ("payee_id", "account_ref", "amount", "currency", "route_id")}


def test_executor_freezes_on_canary_in_payload_even_if_it_matches_the_intent():
    w = _world()
    w.ledger.accounts["acct_student_cny"].balance = 1000
    decoy = next(iter(w.canaries.decoy_fields))
    it = _intent(w, account_ref=decoy)                      # signed intent names the decoy account: payload matches it
    payload = _payload(it)
    assert check_intent(w.signer, it, payload, w.now_iso(), set()).ok
    called = []
    res = w.executor.execute(it, payload, lambda: called.append(1) or decide(_pi(w, amount_cny=100, approvals=S)),
                             "acct_student_cny")
    assert res.status == "frozen" and any("canary" in r for r in res.reasons)
    assert not called and w.ledger.transfers == [] and w.canaries.tripped
    assert w.audit.find("canary_tripped")


def test_executor_returns_held_when_policy_holds_and_moves_no_money():
    w = _world()
    w.ledger.accounts["acct_student_cny"].balance = 1000
    it = _intent(w)
    res = w.executor.execute(it, _payload(it), lambda: decide(_pi(w, amount_cny=100)), "acct_student_cny")   # no approvals
    assert res.status == "held" and res.decision.rule == "R11_approval_required" and not res.ok
    assert w.ledger.transfers == [] and it["nonce"] not in w.executor.used_nonces


# ---------------------------------------------------------------- audit persistence + proof pack + hybrid edge cases
def test_audit_log_persisted_to_file_reloads_and_verifies(tmp_path):
    path = tmp_path / "sub" / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append("evt", {"n": i})
    again = AuditLog(path)
    assert again.entries == log.entries and verify_chain(again.entries).ok and again.head() == log.head()
    again.append("evt", {"n": 4})                                   # the reloaded log continues the same chain
    assert verify_chain(AuditLog(path).entries).ok and len(AuditLog(path).entries) == 5


def test_tampered_audit_file_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append("evt", {"n": i})
    lines = path.read_text().splitlines()
    assert '"n": 2' in lines[2]
    lines[2] = lines[2].replace('"n": 2', '"n": 99')
    path.write_text("\n".join(lines) + "\n")
    r = verify_chain(AuditLog(path).entries)
    assert not r.ok and r.first_broken == 2


def _pack(w, digest=None):
    from oasis.proof.pack import build_proof_pack
    from oasis.trust.crypto import sha256_hex
    from oasis.trust.intents import strip_sigs
    it = _intent(w)
    entry = w.audit.append("transfer_executed", {"intent_id": it["intent_id"]})
    h = sha256_hex(canonical(strip_sigs(it)))
    return build_proof_pack(signer=w.signer, intent=it, verification={}, costs={}, audit_entry=entry,
                            anchor={"digest": digest or h}, trust_public_keys=w.signer.public_keys())


def test_proof_pack_anchor_digest_must_match_intent_hash():
    from oasis.proof.pack import verify_proof_pack
    w = _world()
    assert verify_proof_pack(_pack(w))["ok"]
    bad = verify_proof_pack(_pack(w, digest="0" * 64))              # properly signed pack, wrong anchor
    assert bad["anchor_matches_intent"] is False and bad["pack_signature"] is True and not bad["ok"]


def test_verify_hybrid_rejects_unknown_algorithm_and_empty_required():
    h = HybridSigner()
    m = canonical({"x": 1})
    sigs, keys = h.sign(m), h.public_keys()
    assert verify_hybrid(m, sigs, keys)
    assert not verify_hybrid(m, {**sigs, "rsa": "AAAA"}, {**keys, "rsa": "AAAA"}, required=["rsa"])
    assert not verify_hybrid(m, sigs, keys, required=sorted(keys) + ["rsa"])
    assert not verify_hybrid(m, {}, {}, required=[])
    assert not verify_hybrid(m, {}, {})
