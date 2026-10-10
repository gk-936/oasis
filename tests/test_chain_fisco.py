"""FiscoAnchor against a fake console (hermetic) plus one live integration test (OASIS_FISCO_IT=1)."""
import os
import re

import pytest

from oasis.chain.anchor import FiscoAnchor, FiscoError, LocalAnchorChain, make_anchor

ADDR = "0x6849f21d1e455e9f0712b1e99fa4fcd23758e8f1"
TX = "0x" + "ab" * 32
DIGEST = "779a3d3bc77145d97387f2890f07e4b2a5a01838bff8039aac655a5b11ce72b1"


class FakeConsole:
    """Mimics the output of `bash console.sh ...` inside the distro."""

    def __init__(self, reachable=True, fail_tx=False):
        self.reachable, self.fail_tx = reachable, fail_tx
        self.store = {}
        self.cmds = []

    def __call__(self, cmd: str) -> str:
        self.cmds.append(cmd)
        if "anchor_contract.txt" in cmd:
            return ADDR + "\n"
        if not self.reachable:
            return "the error = [connect failed]\n"
        if "getBlockNumber" in cmd:
            return "7\n\nthe error = [libproviders.so: cannot open shared object file]\n"
        if "getTransactionReceipt" in cmd:
            return '{\n "status":0,\n "blockNumber":8,\n "transactionHash":"%s"\n}\n' % TX
        m = re.search(r"OasisAnchor (0x\w{40}) (anchor|get) 0x([0-9a-f]{64})", cmd)
        assert m, cmd
        _, fn, d = m.groups()
        if fn == "anchor":
            if self.fail_tx:
                return "transaction hash: %s\ntransaction status: 22\n" % TX
            self.store[d] = (1791631128706, 8, "0x" + "11" * 20)
            return "transaction hash: %s\ntransaction status: 0\nReceipt message: Success\n" % TX
        ts, blk, sender = self.store.get(d, (0, 0, "0x" + "0" * 40))
        return "Return values:(%d, %d, %s)\n" % (ts, blk, sender)


def test_anchor_and_verify_roundtrip():
    fc = FakeConsole()
    a = FiscoAnchor(runner=fc)
    assert a.contract == ADDR
    r = a.anchor("0x" + DIGEST.upper())
    assert r["tx_hash"] == TX and r["block_number"] == 8 and r["digest"] == DIGEST
    assert r["network"] == "fisco-bcos-3.x local 4-node" and r["contract"] == ADDR
    v = a.verify(DIGEST)
    assert v["block_number"] == 8 and v["timestamp_ms"] == 1791631128706
    assert a.verify("00" * 32) is None


def test_failed_tx_raises_and_bad_digest_rejected():
    a = FiscoAnchor(runner=FakeConsole(fail_tx=True))
    with pytest.raises(FiscoError):
        a.anchor(DIGEST)
    for bad in ("zz", DIGEST + "00", "; rm -rf /", ""):
        with pytest.raises(ValueError):
            a.anchor(bad)


def test_make_anchor_default_is_local_and_fisco_falls_back():
    assert type(make_anchor({})) is LocalAnchorChain
    assert type(make_anchor({"OASIS_ANCHOR": "local"})) is LocalAnchorChain
    fb = make_anchor({"OASIS_ANCHOR": "fisco"}, runner=FakeConsole(reachable=False))
    assert isinstance(fb, LocalAnchorChain) and "fallback" in fb.label and "NOT FISCO" in fb.label
    ok = make_anchor({"OASIS_ANCHOR": "fisco"}, runner=FakeConsole())
    assert isinstance(ok, FiscoAnchor)


def test_missing_contract_falls_back():
    fb = make_anchor({"OASIS_ANCHOR": "fisco"}, runner=lambda c: "")
    assert isinstance(fb, LocalAnchorChain) and "fallback" in fb.label


@pytest.mark.fisco
@pytest.mark.skipif(os.environ.get("OASIS_FISCO_IT") != "1", reason="needs the live oasis-fisco chain (OASIS_FISCO_IT=1)")
def test_live_fisco_anchor():
    import hashlib
    import time
    a = FiscoAnchor()
    assert a.available()
    digest = hashlib.sha256(f"oasis-it-{time.time()}".encode()).hexdigest()
    assert a.verify(digest) is None
    r = a.anchor(digest)
    print("LIVE TX", r)
    assert re.fullmatch(r"0x[0-9a-f]{64}", r["tx_hash"]) and r["block_number"] >= 1
    v = a.verify(digest)
    assert v and v["block_number"] == r["block_number"]


# ------------------------------------------------------------------------------------------ wiring into World / proof pack
def _paid_world(monkeypatch, deterministic=False):
    from eval.approver import SimulatedHumans
    from eval.scenarios import tuition
    from oasis import world as world_mod
    from oasis.agent.llm import OfflineLLM
    from oasis.agent.pipeline import OasisAgent, Request
    fc = FakeConsole()
    monkeypatch.setattr(world_mod, "make_anchor", lambda: FiscoAnchor(runner=fc))
    w = world_mod.World(llm=OfflineLLM(), deterministic=deterministic)
    out = OasisAgent(w).handle(Request(tuition()), SimulatedHumans())
    return w, out, fc


def test_world_uses_make_anchor_unless_deterministic(monkeypatch):
    w, out, fc = _paid_world(monkeypatch, deterministic=False)
    assert isinstance(w.anchor, FiscoAnchor) and out.status == "paid"
    w2, _, _ = _paid_world(monkeypatch, deterministic=True)
    assert isinstance(w2.anchor, LocalAnchorChain)


def test_proof_pack_carries_the_fisco_result_and_verifies_on_chain(monkeypatch):
    import copy
    from oasis.proof.pack import verify_proof_pack
    w, out, fc = _paid_world(monkeypatch)
    pack = w.proofs[out.proof_id]
    assert pack["anchor"]["tx_hash"] == TX and pack["anchor"]["block_number"] == 8
    assert pack["anchor"]["digest"] == pack["intent_hash"]
    res = verify_proof_pack(pack, {w.trust_fingerprint()}, w.anchor, w.approvers.pinned_key_ids())
    assert res["anchor_on_chain"] is True and res["anchor_matches_intent"] is True and res["ok"]
    wrong_block = copy.deepcopy(pack)
    wrong_block["anchor"]["block_number"] = 99
    assert verify_proof_pack(wrong_block, {w.trust_fingerprint()}, w.anchor)["anchor_on_chain"] is False
    other = copy.deepcopy(pack)
    other["anchor"]["digest"] = "00" * 32
    assert verify_proof_pack(other, {w.trust_fingerprint()}, w.anchor)["anchor_on_chain"] is False


def test_default_environment_is_the_local_simulation(monkeypatch):
    monkeypatch.delenv("OASIS_ANCHOR", raising=False)
    assert isinstance(make_anchor(), LocalAnchorChain)
