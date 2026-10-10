"""Optional tamper-evidence anchoring of intent hashes (only hashes go on-chain, never payment data).

`LocalAnchorChain` is a clearly-labelled LOCAL SIMULATION with the same interface a FISCO BCOS
contract would expose. `FiscoAnchor` is the real adapter for a FISCO BCOS 3.x Air chain (see
docs/fisco-bcos.md); `make_anchor()` picks one from the OASIS_ANCHOR env var (default: local).
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
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


_HEX64 = re.compile(r"^(?:0x)?([0-9a-fA-F]{64})$")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


class FiscoError(RuntimeError):
    pass


def _norm_digest(digest: str) -> str:
    m = _HEX64.match(digest.strip())
    if not m:
        raise ValueError("digest must be a 32-byte hex string (sha256)")
    return m.group(1).lower()


def wsl_runner(distro: str = "oasis-fisco", timeout: float = 60.0):
    """Return a callable that runs a shell command inside the FISCO distro (or locally when already on Linux).

    Why a CLI bridge instead of an SDK/JSON-RPC: FISCO BCOS 3.x nodes only expose a mutual-TLS channel
    protocol (no plain HTTP JSON-RPC), and the official Python SDK for 3.x is a native-binding that is not
    reliably installable on Windows. The official Java console ships with the chain and signs/encodes
    transactions correctly, so we drive it through `wsl -d <distro>`.
    """
    def run(cmd: str) -> str:
        argv = ["bash", "-c", cmd] if shutil.which("wsl") is None else ["wsl", "-d", distro, "-u", "root", "--", "bash", "-c", cmd]
        try:
            p = subprocess.run(argv, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise FiscoError(f"cannot reach FISCO distro: {e}") from e
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        return _ANSI.sub("", out.replace("\x00", ""))
    return run


class FiscoAnchor(Anchor):
    """Anchors sha256 digests in the OasisAnchor contract on a local FISCO BCOS 3.x 4-node Air chain."""
    label = "fisco-bcos-3.x local 4-node"
    CONSOLE = "/opt/fisco/console"
    CONTRACT_FILE = "/opt/fisco/anchor_contract.txt"

    def __init__(self, contract_address: str | None = None, runner=None, distro: str = "oasis-fisco"):
        self.run = runner or wsl_runner(distro)
        self.contract = contract_address or self._discover_contract()
        if not _ADDR.match(self.contract or ""):
            raise FiscoError("anchor contract address unknown; run tools/fisco/start.ps1 (deploys it) or set OASIS_FISCO_CONTRACT")

    def _discover_contract(self) -> str:
        lines = self.run(f"cat {self.CONTRACT_FILE} 2>/dev/null").strip().splitlines()
        return lines[-1].strip() if lines else ""

    def _console(self, *args: str) -> str:
        return self.run(f"cd {self.CONSOLE} && bash console.sh {' '.join(args)} 2>&1")

    def block_number(self) -> int:
        m = re.search(r"^\s*(\d+)\s*$", self._console("getBlockNumber"), re.M)
        if not m:
            raise FiscoError("node not reachable (getBlockNumber failed)")
        return int(m.group(1))

    def available(self) -> bool:
        try:
            self.block_number()
            return True
        except Exception:
            return False

    def anchor(self, digest: str) -> dict:
        d = _norm_digest(digest)
        out = self._console("call", "OasisAnchor", self.contract, "anchor", "0x" + d)
        tx = re.search(r"transaction hash:\s*(0x[0-9a-fA-F]{64})", out)
        st = re.search(r"transaction status:\s*(\d+)", out)
        if not tx or not st or st.group(1) != "0":
            raise FiscoError("anchor transaction failed: " + out.strip()[-300:])
        rc = self._console("getTransactionReceipt", tx.group(1))
        bn = re.search(r'"blockNumber":\s*(\d+)', rc)
        if not bn:
            raise FiscoError("receipt has no block number")
        return {"tx_hash": tx.group(1), "block_number": int(bn.group(1)), "digest": d,
                "network": self.label, "contract": self.contract}

    def verify(self, digest: str) -> dict | None:
        d = _norm_digest(digest)
        out = self._console("call", "OasisAnchor", self.contract, "get", "0x" + d)
        m = re.search(r"Return values:\((\d+),\s*(\d+),\s*(0x[0-9a-fA-F]{40})\)", out)
        if not m:
            raise FiscoError("verify call failed: " + out.strip()[-300:])
        ts, blk, sender = int(m.group(1)), int(m.group(2)), m.group(3)
        if ts == 0:
            return None
        return {"digest": d, "timestamp_ms": ts, "block_number": blk, "sender": sender,
                "network": self.label, "contract": self.contract}


def make_anchor(env=None, runner=None) -> Anchor:
    """OASIS_ANCHOR=fisco|local (default local). `fisco` falls back to a labelled local simulation if unreachable."""
    env = os.environ if env is None else env
    mode = (env.get("OASIS_ANCHOR") or "local").strip().lower()
    if mode != "fisco":
        return LocalAnchorChain()
    try:
        fa = FiscoAnchor(contract_address=env.get("OASIS_FISCO_CONTRACT"), runner=runner,
                         distro=env.get("OASIS_FISCO_DISTRO", "oasis-fisco"))
        if fa.available():
            return fa
        reason = "node unreachable"
    except Exception as e:
        reason = str(e)[:80]
    fb = LocalAnchorChain()
    fb.label = f"local-simulated-chain (NOT FISCO BCOS; fallback: {reason})"
    return fb
