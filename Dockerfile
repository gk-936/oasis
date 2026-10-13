# syntax=docker/dockerfile:1
# Oasis: a self-contained, OFFLINE-by-default sandbox (API + the already-built UI in frontend/dist; no Node needed).
#
# Build:  docker build -t oasis .
# Run:    docker run --rm -p 8000:8000 -v oasis-data:/data --env-file .env.docker oasis
# See docs/deployment-docker.md.  The image contains no secrets and no .env; everything secret comes from the environment
# (OASIS_PASS_*, OASIS_KEY_PASSPHRASE, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) at run time, and all state lives in the /data volume.

# ---- stage 1: build the virtualenv (wheels only; no compiler is needed in the final image) ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
# pytest is a dev/test dependency: not needed to serve the app.
RUN grep -viE '^\s*pytest' /tmp/requirements.txt > /tmp/requirements.runtime.txt \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.runtime.txt

# ---- stage 2: runtime ----
FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    HOME=/tmp \
    PORT=8000 \
    # hosted-mode defaults: offline, mock rates, local (simulated) anchor, judge mode on (API docs off, tighter limits)
    OASIS_HOSTED=1 \
    OASIS_LLM=offline \
    OASIS_EXTRACT=deterministic \
    OASIS_RATES=live \
    OASIS_ANCHOR=local \
    OASIS_JUDGE_MODE=1 \
    # everything stateful lives under /data (a volume): database, keys, session secret, red-team attempts log
    OASIS_DATA_DIR=/data \
    OASIS_DB=/data/oasis.db \
    OASIS_DATA_KEY=/data/keys/data_key.json \
    OASIS_TRUST_KEY=/data/keys/trust_key.json \
    OASIS_SESSION_SECRET_FILE=/data/keys/session_secret.json \
    OASIS_ATTEMPTS_FILE=/data/redteam_attempts.jsonl

RUN groupadd --system --gid 10001 oasis \
 && useradd --system --uid 10001 --gid oasis --home-dir /tmp --shell /usr/sbin/nologin oasis \
 && mkdir -p /data/keys \
 && chown -R oasis:oasis /data

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Code stays root-owned and read-only to the app user. Only what the running app reads:
#   oasis/                 the package (incl. oasis/trust/rules/*.yaml)
#   frontend/dist/         the committed, pre-built UI served at /
#   eval/__init__.py, eval/approver.py   imported by /api/redteam and the scripted demo
#   eval/reports/          read by /api/benchmark
#   eval/fixtures/demo_cache/            recorded responses for the Demo tab's replay mode
COPY oasis/ ./oasis/
COPY frontend/dist/ ./frontend/dist/
COPY eval/__init__.py eval/approver.py ./eval/
COPY eval/reports/ ./eval/reports/
COPY eval/fixtures/demo_cache/ ./eval/fixtures/demo_cache/
COPY docker/entrypoint.sh /usr/local/bin/oasis-entrypoint
RUN chmod 0755 /usr/local/bin/oasis-entrypoint

USER oasis
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'), timeout=4).status == 200 else 1)"]

ENTRYPOINT ["oasis-entrypoint"]
# ONE worker on purpose: the app is single-process by design (a global state lock serialises writes to the audit chain and
# ledger; sessions, revocations, nonces, pending approvals and rate-limit counters are in memory). More workers would fork the
# state and make the per-IP limits and logouts per-worker. --proxy-headers + --forwarded-allow-ips make the rate limiter see the
# real client IP and the cookie logic see https behind a TLS-terminating proxy; set FORWARDED_ALLOW_IPS to the proxy's address.
CMD ["sh", "-c", "exec uvicorn oasis.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
