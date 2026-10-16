#!/usr/bin/env bash
# Start Oasis for a judge: offline, mock rates, a fresh sandbox database, the already-built UI. No API key, no Node, no network.
# Usage: scripts/start_judge.sh [--port 8000] [--host 127.0.0.1] [--random-passcodes] [--data-dir DIR]
# Contains no secrets and no built-in passcode (fresh random ones are printed at each start). Anyone who has them can log in,
# so keep the host at 127.0.0.1 unless you mean to share it.
set -euo pipefail
PORT=8000; HOST=127.0.0.1; RANDOM_PASS=0
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$ROOT/data/judge_sandbox"
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2;; --host) HOST="$2"; shift 2;;
    --data-dir) DATA_DIR="$2"; shift 2;; --random-passcodes) RANDOM_PASS=1; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
if [ -x "$ROOT/.venv/Scripts/python" ]; then PY="$ROOT/.venv/Scripts/python"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
else PY="$(command -v python3 || command -v python)"; fi
[ -f "$ROOT/frontend/dist/index.html" ] || { echo "frontend/dist is missing (it is committed to the repo); rebuild with: cd frontend && npm ci && npm run build" >&2; exit 1; }

rm -rf "$DATA_DIR"; mkdir -p "$DATA_DIR/keys"          # a fresh sandbox every start
export OASIS_LLM=offline OASIS_EXTRACT=deterministic OASIS_RATES=mock OASIS_ANCHOR=local
export OASIS_DB="$DATA_DIR/oasis.db" OASIS_DATA_KEY="$DATA_DIR/keys/data_key.json" OASIS_TRUST_KEY="$DATA_DIR/keys/trust_key.json"
export OASIS_SESSION_SECRET_FILE="$DATA_DIR/keys/session_secret.json" OASIS_ATTEMPTS_FILE="$DATA_DIR/redteam_attempts.jsonl"
export OASIS_JUDGE_MODE=1 OASIS_FRESH_ON_LOGIN=1 PYTHONPATH="$ROOT"
rnd() { "$PY" -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(16)))"; }
# There are no built-in passcodes. Use the ones already set in the environment, otherwise make fresh random ones for this run.
export OASIS_PASS_STUDENT="${OASIS_PASS_STUDENT:-$(rnd)}" OASIS_PASS_PARENT="${OASIS_PASS_PARENT:-$(rnd)}" OASIS_PASS_JUDGE="${OASIS_PASS_JUDGE:-$(rnd)}"
echo "Oasis judge sandbox (offline, MOCK rates, fresh database in $DATA_DIR)"
echo "  URL:         http://$HOST:$PORT"
echo "  Judge login: role judge, passcode $OASIS_PASS_JUDGE"
echo "  Also:        student $OASIS_PASS_STUDENT, parent $OASIS_PASS_PARENT"
echo "  Judge mode:  API docs off, tighter rate limits, at most 20 isolated red-team sandboxes. Ctrl+C stops."
cd "$ROOT"
exec "$PY" -m uvicorn oasis.api.main:app --host "$HOST" --port "$PORT"
