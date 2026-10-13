#!/bin/sh
# Oasis container entrypoint: validate the environment, then exec the server. Generates and prints no secrets.
set -eu

fail() { echo "oasis: ERROR: $*" >&2; exit 78; }
warn() { echo "oasis: WARNING: $*" >&2; }

# ---- state directory must be writable by the app user ----
DATA="${OASIS_DATA_DIR:-/data}"
mkdir -p "$DATA/keys" 2>/dev/null || true
if ! ( : > "$DATA/.write_test" ) 2>/dev/null; then
  fail "$DATA is not writable by uid $(id -u). Use a named volume, or for a bind mount run: chown -R 10001:10001 <host dir>"
fi
rm -f "$DATA/.write_test"

# ---- hosted-mode checks (OASIS_HOSTED=1 is the image default; set 0 only for local experiments) ----
if [ "${OASIS_HOSTED:-1}" = "1" ]; then
  if [ "${OASIS_ALLOW_DEMO_PASSCODES:-0}" != "1" ]; then
    bad=""
    [ "${OASIS_PASS_STUDENT:-student-demo}" = "student-demo" ] && bad="$bad OASIS_PASS_STUDENT"
    [ "${OASIS_PASS_PARENT:-parent-demo}" = "parent-demo" ] && bad="$bad OASIS_PASS_PARENT"
    [ "${OASIS_PASS_JUDGE:-judge-demo}" = "judge-demo" ] && bad="$bad OASIS_PASS_JUDGE"
    if [ -n "$bad" ]; then
      fail "refusing to start with the PUBLIC demo passcodes (unset or default:$bad). Set your own OASIS_PASS_STUDENT, OASIS_PASS_PARENT and OASIS_PASS_JUDGE (see .env.docker.example), or set OASIS_ALLOW_DEMO_PASSCODES=1 if you accept that anyone who has read the repo can log in."
    fi
    for v in OASIS_PASS_STUDENT OASIS_PASS_PARENT OASIS_PASS_JUDGE; do
      eval "val=\${$v}"
      [ "${#val}" -ge 8 ] || fail "$v is shorter than 8 characters; use a longer passcode"
    done
    export OASIS_REQUIRE_CUSTOM_PASSCODES=1      # the app re-checks and refuses on a default as well
  else
    warn "OASIS_ALLOW_DEMO_PASSCODES=1: the public demo passcodes are accepted; the sandbox is open to anyone who can reach it."
  fi
  [ -n "${OASIS_KEY_PASSPHRASE:-}" ] || warn "OASIS_KEY_PASSPHRASE is not set: key files in $DATA/keys are plaintext, protected only by file permissions."
  if [ "${OASIS_LLM:-offline}" != "offline" ]; then
    warn "OASIS_LLM=${OASIS_LLM}: live-LLM mode sends user text to the model provider. NOT recommended for a public judge instance."
    [ "${OASIS_LLM}" != "bedrock" ] || [ -n "${AWS_ACCESS_KEY_ID:-}${AWS_PROFILE:-}${AWS_ROLE_ARN:-}${AWS_CONTAINER_CREDENTIALS_RELATIVE_URI:-}" ] || fail "OASIS_LLM=bedrock needs AWS credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, AWS_PROFILE or a role), or set OASIS_LLM=offline"
  fi
fi

case "${PORT:-8000}" in ''|*[!0-9]*) fail "PORT must be a number (got '${PORT:-}')";; esac

# A proxy address was declared trusted => its X-Forwarded-Host may name the public host in the Origin/CSRF check.
if [ -n "${FORWARDED_ALLOW_IPS:-}" ] && [ -z "${OASIS_TRUST_FORWARDED_HOST:-}" ]; then
  export OASIS_TRUST_FORWARDED_HOST=1
fi

echo "oasis: starting on port ${PORT:-8000} (judge mode=${OASIS_JUDGE_MODE:-0}, llm=${OASIS_LLM:-offline}, rates=${OASIS_RATES:-mock}, anchor=${OASIS_ANCHOR:-local}, data=$DATA)"
exec "$@"
