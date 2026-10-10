from oasis.trust.crypto import (SM2Signer, HybridSigner, Ed25519Signer, MLDSA65Signer,
                                sm2_hybrid_signer, verify_hybrid, sm3_hex, b64)

# GB/T 32918.5 / GM/T 0003.5 Fp-256 example (message "message digest", default ID 1234567812345678)
D = "3945208F7B2144B13F36E38AC6D39F95889393692860B51A42FB81EF4DF7C5B8"
PUB = ("09F9DF311E5421A150DD7D161E4BC5C672179FAD1833FC076BB08FF356F35020"
       "CCEA490CE26775A52DC6EA718CC1AA600AED05FBF35E084A6632F6072DA9AD13")
K = "59276E27D506861A16680F3AD9C02DCCEF3CC1FA3CDBE4CE6D54B80DEAC1BC21"
R = "F5A03B0648D2C4630EEAC513E1BB81A15944DA3827D5B74143AC7EACEEE720B3"
S = "B1B6AA29DF212FD8763182BC0D421CA1BB9038FD1F7F42D4840B69C485BBC1AA"


def test_sm3_vectors():
    assert sm3_hex(b"abc") == "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0"
    assert sm3_hex("abcd" * 16) == "debe9ff92275b8a138604889c18e5a4d6fdb70e5387e5765293dcba39c0c5732"


def test_sm2_standard_vector():
    sg = SM2Signer.from_private_int(int(D, 16))
    assert sg.public_key().hex().upper() == PUB
    sig = sg.sign_with_k(b"message digest", int(K, 16))
    assert sig.hex().upper() == R + S
    assert sg.verify(b"message digest", bytes.fromhex(R + S))
    assert SM2Signer(public_key=bytes.fromhex(PUB)).verify(b"message digest", bytes.fromhex(R + S))


def test_roundtrip_tamper_cross_key():
    a, b = SM2Signer(), SM2Signer()
    sig = a.sign(b"pay 100")
    assert len(sig) == 64 and a.verify(b"pay 100", sig)
    assert SM2Signer(public_key=a.public_key()).verify(b"pay 100", sig)
    assert not a.verify(b"pay 101", sig)
    assert not b.verify(b"pay 100", sig)
    bad = bytearray(sig); bad[5] ^= 1
    assert not a.verify(b"pay 100", bytes(bad))
    assert not a.verify(b"pay 100", sig[:-1])
    assert not a.verify(b"pay 100", bytes(64))


def test_leading_04_pubkey_not_corrupted():
    # gmssl strips leading "0"/"4" hex chars from the public key; such keys must still verify.
    found = 0
    for i in range(400):
        s = SM2Signer(seed=i.to_bytes(4, "big") + b"x")
        if s.public_key().hex()[0] in "04":
            found += 1
            assert SM2Signer(public_key=s.public_key()).verify(b"m", s.sign(b"m"))
            assert s.verify(b"m", s.sign(b"m"))
    assert found >= 5, "no affected key found in the search range; the test would be vacuous"


def test_hybrid_with_sm2_and_swap():
    for hs, algs in ((sm2_hybrid_signer("t", "k"), {"ed25519", "ml-dsa-65", "sm2"}),
                     (sm2_hybrid_signer("t", "k", replace_ed25519=True), {"sm2", "ml-dsa-65"})):
        sigs = hs.sign(b"intent")
        assert set(sigs) == algs
        assert verify_hybrid(b"intent", sigs, hs.public_keys(), required=sorted(algs))
        assert not verify_hybrid(b"intent!", sigs, hs.public_keys(), required=sorted(algs))
        # dropping the SM2 signature must fail when it is required
        no_sm = {k: v for k, v in sigs.items() if k != "sm2"}
        assert not verify_hybrid(b"intent", no_sm, hs.public_keys(), required=sorted(algs))
        other = sm2_hybrid_signer("other", "k")
        assert not verify_hybrid(b"intent", sigs, {**hs.public_keys(), "sm2": other.public_keys()["sm2"]},
                                 required=sorted(algs))


def test_default_scheme_unchanged():
    assert [s.algorithm for s in HybridSigner().signers] == ["ed25519", "ml-dsa-65"]
