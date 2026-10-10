"""Optional tamper-evidence anchoring of intent hashes (only hashes go on-chain, never payment data).

`LocalAnchorChain` is a clearly-labelled LOCAL SIMULATION with the same interface a FISCO BCOS
contract would expose. `FiscoAnchor` is the real adapter; it needs a running FISCO BCOS 3.x node and
its Python SDK, and is not exercised in the competition build unless a node is configured.
"""
from __future__ import annotations
import time
from abc import ABC, abstractmethod

from ..trust.crypto import canonical, sha256_hex


class Anchor(ABC):
    label: str

    @abstractmethod
    def anchor(self, digest: str) -> dict: ...

    @abstractmethod
    def verify(self, digest: str) -> dict | None: ...


class LocalAnchorChain(Anchor):
    label = "local-simulated-chain (NOT FISCO BCOS)"

    def __init__(self, clock=time.time):
        self.blocks: list[dict] = []
        self.clock = clock

    def anchor(self, digest: str) -> dict:
        prev = self.blocks[-1]["tx_hash"] if self.blocks else "0" * 64
        ts = round(self.clock(), 3)
        tx = sha256_hex(canonical({"h": len(self.blocks), "prev": prev, "digest": digest, "ts": ts}))
        block = {"height": len(self.blocks), "prev": prev, "digest": digest, "ts": ts, "tx_hash": tx,
                 "network": self.label}
        self.blocks.append(block)
        return block

    def verify(self, digest: str) -> dict | None:
        return next((b for b in self.blocks if b["digest"] == digest), None)

    def chain_ok(self) -> bool:
        prev = "0" * 64
        for b in self.blocks:
            exp = sha256_hex(canonical({"h": b["height"], "prev": prev, "digest": b["digest"], "ts": b["ts"]}))
            if b["prev"] != prev or b["tx_hash"] != exp:
                return False
            prev = b["tx_hash"]
        return True


class FiscoAnchor(Anchor):  # pragma: no cover - needs a live node
    label = "fisco-bcos-3.x"

    def __init__(self, config_path: str, contract_address: str):
        try:
            from client.bcosclient import BcosClient  # python-sdk
        except ImportError as e:
            raise RuntimeError("FISCO BCOS Python SDK not installed; use LocalAnchorChain") from e
        self.client = BcosClient()
        self.contract = contract_address

    def anchor(self, digest: str) -> dict:
        raise NotImplementedError("Deploy the anchor contract and wire client.sendRawTransaction here.")

    def verify(self, digest: str) -> dict | None:
        raise NotImplementedError
