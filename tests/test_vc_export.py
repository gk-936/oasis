"""W3C VC export of the Trust Pass: did:key format, round trip, tamper rejection. Hermetic."""
import copy

import pytest

from oasis.proof import trust_pass as tp
from oasis.proof import vc_export as vc
from test_trust_pass import _paid_world


@pytest.fixture(scope="module")
def setup():
    w = _paid_world()
    holder = tp.issue(w, ["on_time_all", "verified_payees"], "Landlord")
    return w, holder, vc.export_vc(holder, w.signer)


def test_did_key_format(setup):
    w, _, doc = setup
    assert doc["issuer"].startswith("did:key:z6Mk")          # Ed25519 multicodec 0xed01 always yields z6Mk
    assert vc.did_key_public(doc["issuer"]) == w.signer.signers[0].public_key()
    assert doc["credentialSubject"]["id"].startswith("did:key:z6Mk")
    assert doc["type"] == ["VerifiableCredential", "OasisTrustPass"]
    assert doc["proof"]["proofValue"].startswith("z")
    with pytest.raises(ValueError):
        vc.did_key_public("did:web:example.com")


def test_b58_roundtrip():
    for b in (b"\0\0abc", bytes(range(40)), b"\xff" * 5):
        assert vc.b58decode(vc.b58encode(b)) == b


def test_round_trip_and_no_private_data(setup):
    w, holder, doc = setup
    assert vc.verify_vc(doc, {w.trust_fingerprint()})["ok"]
    assert vc.import_vc(doc) == holder["credential"]
    s = repr(doc)
    assert holder["disclosures"][0]["salt"] not in s
    assert "zk_openings" not in s
    assert tp.verify_presentation({"credential": holder["credential"], "disclosures": []}, {w.trust_fingerprint()},
                                  w.today.isoformat(), lambda p: w.proofs.get(p))["ok"]      # native format untouched


def test_tamper_rejected(setup):
    w, _, doc = setup
    for mut in (lambda d: d["credentialSubject"]["claims"][0].__setitem__("statement", "forged"),
                lambda d: d["credentialSubject"].__setitem__("audience", "Someone else"),
                lambda d: d.__setitem__("expirationDate", "2099-01-01T00:00:00Z"),
                lambda d: d["evidence"][0]["credential"]["claims"][0].__setitem__("statement", "forged"),
                lambda d: d["proof"].__setitem__("proofValue", "z" + d["proof"]["proofValue"][2:] + "1"),
                lambda d: d.__setitem__("issuer", vc.holder_did("x"))):
        bad = copy.deepcopy(doc)
        mut(bad)
        assert not vc.verify_vc(bad)["ok"]
        with pytest.raises(ValueError):
            vc.import_vc(bad)
    assert not vc.verify_vc({})["ok"]
    assert not vc.verify_vc(doc, {"someone-elses-fingerprint"})["ok"]


def test_api_endpoints(api_client):
    c = api_client
    h = c.post("/api/trust-pass/issue", json={"claims": ["no_late"], "thresholds": {}}).json()
    r = c.post("/api/trust-pass/vc/export", json={"holder": {"credential": h["credential"]}})
    assert r.status_code == 200, r.text
    assert c.post("/api/trust-pass/vc/verify", json=r.json()).json()["ok"]
    h["credential"]["claims"][0]["statement"] = "x"
    assert c.post("/api/trust-pass/vc/export", json={"holder": {"credential": h["credential"]}}).status_code == 400