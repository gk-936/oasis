#!/usr/bin/env bash
# Router-overhaul gates (ROUTER_OVERHAUL.md section 0 item 6). Offline only. Usage: scripts/router_gates.sh <out-dir>
set -u
O="${1:-.}"; mkdir -p "$O"
export OASIS_LLM=offline OASIS_CHAT_LLM=0 PYTHONPATH=. PYTHONIOENCODING=utf-8
PY=.venv/Scripts/python
OASIS_DB=:memory: $PY -m pytest -q > "$O/pytest.txt" 2>&1; tail -3 "$O/pytest.txt"
$PY -m eval.runner --llm offline > "$O/runner.txt" 2>&1; tail -4 "$O/runner.txt"
$PY -m eval.fuzz_bench > "$O/fuzz.txt" 2>&1; tail -4 "$O/fuzz.txt"
$PY execution_evidence/verify_evidence.py > "$O/verify.txt" 2>&1; tail -3 "$O/verify.txt"
$PY -m eval.frozen_set > "$O/frozen.txt" 2>&1; tail -6 "$O/frozen.txt"
