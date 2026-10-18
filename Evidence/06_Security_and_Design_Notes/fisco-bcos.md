# FISCO BCOS anchoring (4-node local test chain)

Only 32-byte intent digests are anchored (contract `OasisAnchor`, `tools/fisco/contracts/OasisAnchor.sol`); no payment data goes on-chain.
The chain is a 4-node local test chain (real FISCO BCOS 3.17.1, single host). Oasis does not claim the on-chain challenge bonus (that is for Topic F; Oasis is Topic C). Default remains the labelled local simulation; set `OASIS_ANCHOR=fisco` to use the real chain (falls back to local, labelled, if unreachable).

## What was built (2026-10-10)

- Dedicated WSL2 distro `oasis-fisco` (Ubuntu 22.04 official WSL rootfs) imported to `D:\WSL\oasis-fisco`.
- FISCO BCOS v3.17.1 Air, 4 nodes (`/opt/fisco/nodes/127.0.0.1`, PBFT, non-SM, group0/chain0), official `build_chain.sh`; console 3.8.0 in `/opt/fisco/console`; JDK 11.
- Downloads: `D:\china_hackathon\tools\dl\` (rootfs tarball, git-ignored).

## Why a CLI bridge

FISCO BCOS 3.x nodes expose only a mutual-TLS channel (no plain HTTP JSON-RPC), so Windows cannot just POST JSON-RPC. The 3.x Python SDK is a native binding (bcos-c-sdk) not reliably installable on Windows, and a hand-rolled client would need to re-implement transaction encoding and signing. The official console signs and encodes correctly, so `FiscoAnchor` drives it with `wsl -d oasis-fisco -u root -- bash -c "cd /opt/fisco/console && bash console.sh ..."` (about 7 s per anchor: a send plus a receipt lookup; verify about 3.5 s). Digests are validated as 64 hex characters before reaching the shell. Inside the distro (Linux) the same code runs `bash` directly.

## Run

    tools\fisco\start.ps1     # starts distro keepalive + 4 nodes, deploys contract if none, prints status
    tools\fisco\status.ps1    # nodes 4/4, block number, contract address (exit 0 = healthy)
    tools\fisco\stop.ps1      # stops nodes, releases keepalive, terminates the distro (data kept)

Contract address is stored in the distro at `/opt/fisco/anchor_contract.txt` (override with `OASIS_FISCO_CONTRACT`).

## Verify a transaction hash

    wsl -d oasis-fisco -u root -- bash -c "cd /opt/fisco/console && bash console.sh getTransactionReceipt <0xTX>"
    wsl -d oasis-fisco -u root -- bash -c "cd /opt/fisco/console && bash console.sh call OasisAnchor <CONTRACT> get 0x<DIGEST>"

The receipt shows `blockNumber`, `status 0`, the `Anchored` event topic carrying the digest; `get` returns (timestamp ms, block, sender). A trailing `libproviders.so` message from the console is harmless.

## Live results

Contract `0x6849f21d1e455e9f0712b1e99fa4fcd23758e8f1` (deploy tx `0xaf0030668c5cc67a57bf7286a47dbf9130efe18a714e8c14f61bc199c74d1d67`):
- block 4, tx `0xe30c5a16f517cb7aba9258f42f2562d2e31ee622768b88b4d846cfab04139103` (integration test)
- block 5, tx `0xefa4110aa4848d1f61f047fcde89519a4f1059b2ce25e8ed4b3016e548d15959` (via `make_anchor()`; `verify` returned the same block)

Tests: `tests/test_chain_fisco.py` (hermetic fake console) and `OASIS_FISCO_IT=1 pytest -m fisco` (live).

## Honest limits

Single machine, all 4 nodes on one host: demonstrates the integration, not decentralised trust. The default sender account is the console's auto-generated key. When `OASIS_ANCHOR=fisco`, `World` uses `make_anchor()` (deterministic worlds, tests, the benchmark and the scripted demo always use the local simulation). The proof pack stores the `anchor()` result (tx hash, block, contract); its `anchor_on_chain` check calls `verify(digest)` on the contract and compares the digest and block number. The Proof tab shows the tx hash and block. Each anchored payment costs about 7 s (WSL console).

## Remove everything

    tools\fisco\stop.ps1
    wsl --unregister oasis-fisco
    Remove-Item -Recurse D:\WSL\oasis-fisco

(The one C: side effect of the import is the WSL registry entry for the distro, removed by `--unregister`.)
