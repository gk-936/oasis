"""Zero-knowledge threshold proofs: completeness, soundness against forgery attempts, binding to context."""
import copy

import pytest

from oasis.proof import zk

CTX = b"credential-hash|Landlord, Room 1203"


@pytest.mark.parametrize("on,tot", [(0, 1), (1, 1), (9, 10), (17, 18), (5, 5), (30, 33), (999, 1000)])
def test_completeness_exact_boundary(on, tot):
    pub, priv = zk.commit_counts(on, tot)
    best = (100 * on) // tot                                  # the highest whole percent the record meets
    if best >= 1:
        assert zk.verify_claim(pub, zk.prove_rate(pub, priv, best, CTX), CTX)
    if best < 100:
        with pytest.raises(zk.ZkError):
            zk.prove_rate(pub, priv, best + 1, CTX)
    assert zk.verify_claim(pub, zk.prove_count(pub, priv, tot, CTX), CTX)
    with pytest.raises(zk.ZkError):
        zk.prove_count(pub, priv, tot + 1, CTX)


def test_commitments_are_randomised_and_hide_the_value():
    a, _ = zk.commit_counts(17, 18)
    b, _ = zk.commit_counts(17, 18)
    assert a["c_on"] != b["c_on"] and a["c_tot"] != b["c_tot"]


def test_proof_does_not_contain_the_counts():
    pub, priv = zk.commit_counts(17, 18)
    c = zk.prove_rate(pub, priv, 90, CTX)
    s = repr(c)
    assert "17" not in c["statement"] and "'on'" not in s and "r_on" not in s and "priv" not in s


def test_bound_to_context_statement_and_commitments():
    pub, priv = zk.commit_counts(17, 18)
    c = zk.prove_rate(pub, priv, 90, CTX)
    assert zk.verify_claim(pub, c, CTX)
    assert not zk.verify_claim(pub, c, b"another credential|someone else")            # cannot be moved to another verifier
    assert not zk.verify_claim(pub, {**c, "k": 94, "statement": "on_time_pct>=94"}, CTX)   # cannot be relabelled upward
    assert not zk.verify_claim(pub, {**c, "k": 80, "statement": "on_time_pct>=80"}, CTX)   # nor downward
    other, _ = zk.commit_counts(17, 18)
    assert not zk.verify_claim(other, c, CTX)                                          # nor reused on another credential
    assert not zk.verify_claim(pub, {**c, "kind": "count", "statement": "payments>=90"}, CTX)


def test_tampering_with_any_part_fails():
    pub, priv = zk.commit_counts(17, 18)
    c = zk.prove_rate(pub, priv, 90, CTX)
    for i in range(zk.N_BITS):
        t = copy.deepcopy(c)
        t["proof"]["or"][i][2] = format((int(t["proof"]["or"][i][2], 16) + 1) % (1 << 256), "064x")
        assert not zk.verify_claim(pub, t, CTX), f"or-proof {i}"
    t = copy.deepcopy(c)
    t["proof"]["bits"][3], t["proof"]["bits"][4] = t["proof"]["bits"][4], t["proof"]["bits"][3]
    assert not zk.verify_claim(pub, t, CTX)                                            # reordered bits break the weighted sum
    t = copy.deepcopy(c)
    t["proof"]["bits"] = t["proof"]["bits"][:-1]
    assert not zk.verify_claim(pub, t, CTX)


def test_a_commitment_to_two_cannot_pass_as_a_bit():
    r = zk._rand()
    c = zk.commit(2, r)
    ctx = b"x"
    for claimed in (0, 1):
        assert not zk._bit_verify(c, zk._bit_prove(c, claimed, r, ctx), ctx)
    good = zk.commit(1, r)
    assert zk._bit_verify(good, zk._bit_prove(good, 1, r, ctx), ctx)


def test_negative_difference_cannot_be_proven_even_by_a_dishonest_prover():
    pub, priv = zk.commit_counts(5, 10)                         # 50 %: a 90 % claim is false
    with pytest.raises(zk.ZkError):
        zk.prove_rate(pub, priv, 90, CTX)
    # a dishonest prover tries the honest machinery on d mod L (what a negative d wraps to): out of range, refused
    d = (100 * 5 - 90 * 10) % zk._L
    with pytest.raises(zk.ZkError):
        zk.prove_nonneg(d, 123, CTX)
    # ... and re-using a valid proof for a different committed value fails the weighted-sum check
    pub2, priv2 = zk.commit_counts(10, 10)
    good = zk.prove_rate(pub2, priv2, 90, CTX)
    assert not zk.verify_claim(pub, good, CTX)


def test_malformed_input_never_raises():
    pub, priv = zk.commit_counts(17, 18)
    c = zk.prove_rate(pub, priv, 90, CTX)
    for bad in (None, {}, {"kind": "rate"}, {**c, "proof": None}, {**c, "proof": {"n": zk.N_BITS}},
                {**c, "k": "x"}, {**c, "proof": {**c["proof"], "bits": ["zz"] * zk.N_BITS}},
                {**c, "proof": {**c["proof"], "or": [[1, 2, 3, 4]] * zk.N_BITS}}):
        assert zk.verify_claim(pub, bad, CTX) is False
    assert zk.verify_claim({"c_on": "00", "c_tot": "11"}, c, CTX) is False


def test_threshold_range_checks():
    pub, priv = zk.commit_counts(17, 18)
    for bad in (0, 101, -5):
        with pytest.raises(zk.ZkError):
            zk.prove_rate(pub, priv, bad, CTX)
    with pytest.raises(zk.ZkError):
        zk.prove_count(pub, priv, 0, CTX)
