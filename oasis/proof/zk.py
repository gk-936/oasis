"""Zero-knowledge threshold proofs over Pedersen commitments (edwards25519, via libsodium in PyNaCl).

Goal: show "at least 90% of my payments were on time" or "at least 3 payments" WITHOUT revealing the counts, and without the
issuer having to pre-sign that particular threshold. The issuer signs Pedersen commitments to the hidden numbers; the holder
later proves, for any threshold they choose, that a linear combination of the committed values is >= 0.

Construction (standard, textbook):
- Commitment  C(v, r) = v*G + r*H  (additively written). G is the curve base point, H = hash-to-curve("oasis/pedersen/H"): nobody
  knows log_G(H), so a commitment binds the value and hides it.
- Homomorphism: the verifier derives the commitment to  d = 100*on - k*tot  as  100*C_on - k*C_tot  from the SIGNED commitments;
  nothing about it is taken from the prover.
- Range: d in [0, 2^N) is shown by committing to each bit of d (C_i = b_i*G + r_i*H), checking sum 2^i * C_i == C_d, and proving
  each C_i opens to 0 or 1 with a Cramer-Damgard-Schoenmakers OR-proof of knowledge of the blinding factor. Made non-interactive with
  Fiat-Shamir; the challenge hashes a context string (credential hash, audience, statement), so a proof cannot be moved to another
  credential, verifier or threshold.
- Soundness of the range step: a negative d reduces mod the group order to a number far above 2^N, which has no bit decomposition.

Honest limits: this is a from-the-textbook implementation checked by tests (including forgery attempts), NOT independently
audited; proofs are about 2.7 KB for N = 20 (Bulletproofs would be logarithmic, this is linear); it hides the counts but not
that a credential exists, and it proves facts about numbers the ISSUER committed to (the issuer is still trusted for those).
"""
from __future__ import annotations
import hashlib
import os

import nacl.bindings as nb

N_BITS = 20                       # d < 2^20 = 1,048,576 (100 * payments; plenty for a student's history)
_L = 2**252 + 27742317777372353535851937790883648493       # prime order of the edwards25519 main subgroup
G = nb.crypto_scalarmult_ed25519_base_noclamp((1).to_bytes(32, "little"))
H = nb.crypto_core_ed25519_from_uniform(hashlib.sha256(b"oasis/pedersen/H/v1").digest())


class ZkError(ValueError):
    """A proof is malformed or does not verify."""


# ------------------------------------------------------------------------------------------------ scalar / point helpers
def _s(x: int) -> bytes:
    return (x % _L).to_bytes(32, "little")


def _i(b: bytes) -> int:
    return int.from_bytes(b, "little")


def _rand() -> int:
    return _i(nb.crypto_core_ed25519_scalar_reduce(os.urandom(64)))


def _mul(k: int, p: bytes) -> bytes | None:
    k %= _L
    return None if k == 0 else nb.crypto_scalarmult_ed25519_noclamp(_s(k), p)      # None is the identity


def _add(a: bytes | None, b: bytes | None) -> bytes | None:
    if a is None:
        return b
    if b is None:
        return a
    try:
        return nb.crypto_core_ed25519_add(a, b)
    except Exception:                       # a + b = identity (libsodium refuses to encode it here)
        return None


def _neg(p: bytes | None) -> bytes | None:
    return None if p is None else _mul(_L - 1, p)


def _sub(a, b):
    return _add(a, _neg(b))


def _valid(p: bytes) -> bool:
    return isinstance(p, bytes) and len(p) == 32 and nb.crypto_core_ed25519_is_valid_point(p)


def commit(v: int, r: int) -> bytes:
    c = _add(_mul(v, G), _mul(r, H))
    if c is None:
        raise ZkError("degenerate commitment")
    return c


def _challenge(ctx: bytes, *points) -> int:
    h = hashlib.sha512(b"oasis/zk/v1|" + ctx)
    for p in points:
        h.update(b"|" + (p if p is not None else b"\x00" * 32))
    return _i(nb.crypto_core_ed25519_scalar_reduce(h.digest()))


# ------------------------------------------------------------------------------------------------------- bit OR-proof
def _bit_prove(c: bytes, bit: int, r: int, ctx: bytes) -> list[int]:
    """Proof that c = bit*G + r*H with bit in {0,1}, as [c0, c1, s0, s1]: branch 0 proves c = r*H, branch 1 proves c - G = r*H,
    and the prover can only complete the branch it really knows (the other is simulated)."""
    y = (c, _sub(c, G))
    k, cf, sf = _rand(), _rand(), _rand()
    f = 1 - bit
    t = [None, None]
    t[f] = _sub(_mul(sf, H), _mul(cf, y[f]))             # simulated branch
    t[bit] = _mul(k, H)                                   # real branch
    cb = (_challenge(ctx, c, t[0], t[1]) - cf) % _L
    sb = (k + cb * r) % _L
    cc, ss = [0, 0], [0, 0]
    cc[bit], cc[f], ss[bit], ss[f] = cb, cf, sb, sf
    return [cc[0], cc[1], ss[0], ss[1]]


def _bit_verify(c: bytes, proof: list[int], ctx: bytes) -> bool:
    c0, c1, s0, s1 = (x % _L for x in proof)
    t0 = _sub(_mul(s0, H), _mul(c0, c))
    t1 = _sub(_mul(s1, H), _mul(c1, _sub(c, G)))
    return (c0 + c1) % _L == _challenge(ctx, c, t0, t1)


# ------------------------------------------------------------------------------------------------------------- range
def prove_nonneg(d: int, rd: int, ctx: bytes, n: int = N_BITS) -> dict:
    """Proof that the commitment commit(d, rd) opens to some d with 0 <= d < 2^n. Raises ZkError if d is out of range
    (an honest prover cannot prove a false statement, and the check here is only for a clear error message)."""
    if not 0 <= d < 2 ** n:
        raise ZkError("the committed value is outside the provable range")
    rs = [0] + [_rand() for _ in range(n - 1)]
    rs[0] = (rd - sum((1 << i) * rs[i] for i in range(1, n))) % _L
    cd = commit(d, rd)
    bits = [(d >> i) & 1 for i in range(n)]
    cs = [commit(b, r) for b, r in zip(bits, rs)]
    ors = [_bit_prove(c, b, r, ctx + b"|" + cd + b"|bit" + str(i).encode()) for i, (c, b, r) in enumerate(zip(cs, bits, rs))]
    return {"n": n, "bits": [c.hex() for c in cs], "or": [[_s(x).hex() for x in o] for o in ors]}


def verify_nonneg(cd: bytes, proof: dict, ctx: bytes, n: int = N_BITS) -> bool:
    """True only if `proof` shows that `cd` commits to a value in [0, 2^n). Never raises."""
    try:
        if not _valid(cd) or proof.get("n") != n or len(proof["bits"]) != n or len(proof["or"]) != n:
            return False
        cs = [bytes.fromhex(h) for h in proof["bits"]]
        if not all(_valid(c) for c in cs):
            return False
        total = None
        for i, c in enumerate(cs):
            total = _add(total, _mul(1 << i, c))
        if total != cd:
            return False
        for i, (c, o) in enumerate(zip(cs, proof["or"])):
            sc = [_i(bytes.fromhex(x)) for x in o]
            if len(sc) != 4 or any(x >= _L for x in sc):
                return False
            if not _bit_verify(c, sc, ctx + b"|" + cd + b"|bit" + str(i).encode()):
                return False
        return True
    except (ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return False


# --------------------------------------------------------------------------------------------- committed counters (issuer)
def commit_counts(on: int, tot: int) -> tuple[dict, dict]:
    """(public, private): commitments to the on-time and total payment counts, and their openings."""
    r_on, r_tot = _rand(), _rand()
    pub = {"scheme": "pedersen-ed25519/v1", "c_on": commit(on, r_on).hex(), "c_tot": commit(tot, r_tot).hex()}
    return pub, {"on": on, "tot": tot, "r_on": hex(r_on), "r_tot": hex(r_tot)}


def _ctx(base: bytes, statement: str) -> bytes:
    return base + b"|" + statement.encode()


def rate_statement(percent: int) -> str:
    return f"on_time_pct>={percent}"


def count_statement(minimum: int) -> str:
    return f"payments>={minimum}"


def _derived(pub: dict, kind: str, k: int) -> bytes:
    """The commitment to the quantity that must be >= 0, computed by the VERIFIER from the signed commitments."""
    c_on, c_tot = bytes.fromhex(pub["c_on"]), bytes.fromhex(pub["c_tot"])
    if kind == "rate":                       # 100*on - k*tot  >= 0   <=>   on/tot >= k/100
        d = _sub(_mul(100, c_on), _mul(k, c_tot))
    else:                                    # tot - k >= 0
        d = _sub(c_tot, _mul(k, G))
    if d is None:
        raise ZkError("degenerate")
    return d


def prove_rate(pub: dict, priv: dict, percent: int, base_ctx: bytes) -> dict:
    if not 1 <= percent <= 100:
        raise ZkError("percent must be 1..100")
    on, tot = priv["on"], priv["tot"]
    d, rd = 100 * on - percent * tot, (100 * int(priv["r_on"], 16) - percent * int(priv["r_tot"], 16)) % _L
    if d < 0:
        raise ZkError("the record does not meet that threshold")
    return {"statement": rate_statement(percent), "kind": "rate", "k": percent,
            "proof": prove_nonneg(d, rd, _ctx(base_ctx, rate_statement(percent)))}


def prove_count(pub: dict, priv: dict, minimum: int, base_ctx: bytes) -> dict:
    if minimum < 1:
        raise ZkError("minimum must be at least 1")
    d, rd = priv["tot"] - minimum, int(priv["r_tot"], 16)
    if d < 0:
        raise ZkError("the record does not meet that threshold")
    return {"statement": count_statement(minimum), "kind": "count", "k": minimum,
            "proof": prove_nonneg(d, rd, _ctx(base_ctx, count_statement(minimum)))}


def verify_claim(pub: dict, claim: dict, base_ctx: bytes) -> bool:
    try:
        kind, k = claim["kind"], int(claim["k"])
        stmt = rate_statement(k) if kind == "rate" else count_statement(k) if kind == "count" else None
        if stmt is None or claim.get("statement") != stmt or (kind == "rate" and not 1 <= k <= 100) or k < 1:
            return False
        return verify_nonneg(_derived(pub, kind, k), claim["proof"], _ctx(base_ctx, stmt))
    except (ValueError, TypeError, KeyError, ZkError):
        return False
