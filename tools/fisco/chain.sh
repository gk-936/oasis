#!/bin/bash
# Runs INSIDE the oasis-fisco WSL distro. Usage: chain.sh start|stop|status|deploy
# Everything lives under /opt/fisco (the distro's vhdx is on D:\WSL\oasis-fisco).
set -u
ROOT=/opt/fisco
NODES=$ROOT/nodes/127.0.0.1
CONSOLE=$ROOT/console
ADDR_FILE=$ROOT/anchor_contract.txt
SRC="$(cd "$(dirname "$0")" && pwd)/contracts/OasisAnchor.sol"

nodes_up() { pgrep -c -f 'fisco-bcos' || true; }

case "${1:-status}" in
  start)
    if [ "$(nodes_up)" -lt 4 ]; then (cd "$NODES" && bash start_all.sh >/dev/null 2>&1); sleep 6; fi
    echo "nodes running: $(nodes_up)/4"
    ;;
  stop)
    (cd "$NODES" && bash stop_all.sh >/dev/null 2>&1)
    echo "nodes running: $(nodes_up)/4"
    ;;
  deploy)
    cp "$SRC" "$CONSOLE/contracts/solidity/OasisAnchor.sol"
    out=$(cd "$CONSOLE" && bash console.sh deploy OasisAnchor 2>&1)
    addr=$(echo "$out" | sed -n 's/.*contract address: *\(0x[0-9a-fA-F]\{40\}\).*/\1/p' | head -1)
    [ -n "$addr" ] || { echo "deploy failed:"; echo "$out" | tail -5; exit 1; }
    echo "$addr" > "$ADDR_FILE"; echo "deployed OasisAnchor at $addr"
    ;;
  status)
    n=$(nodes_up); echo "nodes running: $n/4"
    bn=$(cd "$CONSOLE" && bash console.sh getBlockNumber 2>&1 | grep -E '^[0-9]+$' | head -1)
    echo "block number: ${bn:-unreachable}"
    echo "contract: $(cat "$ADDR_FILE" 2>/dev/null || echo none)"
    [ "$n" -ge 4 ] && [ -n "${bn:-}" ]
    ;;
esac
