# Hosting Oasis in Docker

Oasis ships as one container: the API, the already-built UI (`frontend/dist`, no Node needed) and its sandbox state under a `/data` volume. Defaults are **hosted-safe**: offline LLM, MOCK rates, simulated local anchor, judge mode on (API docs off, tighter limits), no secrets in the image, non-root user, one worker.

> **Status of this packaging (updated 2026-10-13).** The image was built and run with Docker 29.1.2 on Windows: the build succeeded, the container reached `healthy`, the UI and API were served, the public demo passcodes were refused, a judge login and a red-team attempt worked, `/docs` was off, and the filesystem was read-only with a non-root user. Two defects found by that first build were fixed: the entrypoint had Windows line endings (the Dockerfile now strips them) and `httpx` was missing from `requirements.txt`. **Not done:** deployment to a public host, load testing, and the Caddy `tls` profile (still untested end to end).

## 1. Quick start

```bash
cp .env.docker.example .env.docker      # Windows PowerShell: Copy-Item .env.docker.example .env.docker
# edit .env.docker: set OASIS_PASS_STUDENT / _PARENT / _JUDGE (8+ chars each) and OASIS_KEY_PASSPHRASE
docker compose up -d --build
# open http://127.0.0.1:8000   (published on the host's loopback only by default)
docker compose logs -f oasis
docker compose ps                        # STATUS shows (healthy) once /api/health answers
```

Plain `docker`, without compose:

```bash
docker build -t oasis .
docker run -d --name oasis --restart unless-stopped -p 127.0.0.1:8000:8000 \
  -v oasis-data:/data --env-file .env.docker \
  --read-only --tmpfs /tmp --security-opt no-new-privileges --cap-drop ALL oasis
```

The container refuses to start (exit code 78 and a clear message) if a passcode is unset or shorter than 8 characters. There are no built-in passcodes. Judge-mode and `OASIS_REQUIRE_CUSTOM_PASSCODES=1` enforce the same rule again inside the app.

Windows: Docker Desktop must be running; commands are the same in PowerShell. On Windows the `.env.docker` file must use plain `KEY=value` lines (no quotes, no `export`).

## 2. What is in the image

| Item | Value |
|---|---|
| Base | `python:3.12-slim` (Debian), two stages: the builder installs `requirements.txt` minus `pytest` into a virtualenv with `--no-cache-dir`, the runtime copies only the venv |
| Python | 3.12. The repo's own venv is 3.10; all 60 source files parse on 3.12 and the app ran on 3.10. The Docker image itself was not run |
| Copied | `oasis/` (incl. `oasis/trust/rules/*.yaml`), `frontend/dist/`, `eval/__init__.py`, `eval/approver.py` (imported by `/api/redteam` and the scripted demo), `eval/reports/` (read by `/api/benchmark`), `eval/fixtures/demo_cache/`, `docker/entrypoint.sh`. Nothing else is read by the running app |
| Not copied | `.env*`, `data/`, `.venv`, `node_modules`, `.git`, `tests/`, `docs/`, `tools/`, `scripts/`, eval caches and checkpoints, `*.pdf` (`.dockerignore`) |
| User | `oasis` (uid/gid 10001), code root-owned and read-only to it |
| Port / health | `EXPOSE 8000`; `HEALTHCHECK` is Python (`urllib`) against `/api/health`, no curl |
| Process | `uvicorn oasis.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"` (hosts that inject `PORT` just work) |
| State | `/data` volume: `oasis.db` (payload columns AES-256-GCM encrypted), `keys/` (data key, trust signing key, session secret), `redteam_attempts.jsonl` |
| Size (estimate, not measured) | roughly 200 to 250 MB unpacked, about 80 to 100 MB compressed: `python:3.12-slim` is about 120 MB unpacked, the installed requirements about 60 to 90 MB (the Windows venv used for validation was 59 MB), the app 2.4 MB |

**Why exactly one worker.** The app is single-process by design: a global lock serialises writes to the audit hash chain, ledger, nonces and pending approvals; session revocations, replay nonces and the per-IP rate-limit counters live in memory. Several workers would each hold their own copy, forking the state, letting a logged-out token work on another worker and multiplying the rate limits. Scale up the machine, not the worker count. For the same reason run **one replica** (no autoscaling above 1).

### Environment variables (container)

Set secrets at run time, never in the image. The full annotated list is `.env.docker.example`; the app-level variables are in [configuration.md](configuration.md).

| Variable | Default in image | Notes |
|---|---|---|
| `OASIS_PASS_STUDENT` / `_PARENT` / `_JUDGE` | none (required) | refused if unset, default or under 8 chars |
| `OASIS_KEY_PASSPHRASE` | unset (warning) | wraps the key files; needed at every start |
| `OASIS_JUDGE_MODE` | `1` | `0` for personal use (`/docs` on, looser limits) |
| `OASIS_LLM` / AWS credentials | `offline` / unset | live mode sends text to Amazon Bedrock; not for a public instance |
| `OASIS_RATES` / `OASIS_ANCHOR` | `live` / `local` | `live` fetches real ECB rates server-side (cached; MOCK fallback if unreachable); set `mock` for repeatable demo numbers |
| `OASIS_HOSTED` | `1` | `0` skips the entrypoint's hosted-mode checks (the app's own checks still apply) |
| `PORT` | `8000` | injected by many hosts |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` (compose: its own subnet) | proxy addresses/CIDRs whose `X-Forwarded-*` headers are believed |
| `OASIS_TRUST_FORWARDED_HOST` | auto `1` when `FORWARDED_ALLOW_IPS` is set | accept `X-Forwarded-Host` as the public host in the Origin (CSRF) check |
| `OASIS_ALLOWED_ORIGINS` | unset | extra exact origins, e.g. `https://oasis.example.com` (use when your proxy rewrites `Host`) |
| `OASIS_COOKIE_SECURE` | unset | `1` forces the `Secure` flag on the session cookie |
| `OASIS_DATA_DIR` | `/data` | base for the llm cache and rate cache; the DB and key paths are set explicitly |

## 3. Behind HTTPS (reverse proxy)

Terminate TLS at a proxy and keep the container on a private network or loopback. Three things must be right, and they are small switches:

1. **Client IP for the rate limiter.** Login and red-team limits are keyed by client IP. Behind a proxy every request otherwise comes from the proxy's address, so one attacker could lock everyone out (or limits become global). Set `FORWARDED_ALLOW_IPS` to the proxy address or CIDR so uvicorn applies `X-Forwarded-For`. **Never set it to `*` while the container port is reachable directly from the internet**: clients could then spoof their IP and dodge the limits.
2. **Secure cookie.** Uvicorn turns `X-Forwarded-Proto: https` into an https request scheme for trusted proxies, and the login handler then adds `Secure`. `OASIS_COOKIE_SECURE=1` forces it. Plain `http://localhost` is unchanged (no `Secure`, or the browser would drop the cookie).
3. **Origin/CSRF check.** State-changing requests must carry an `Origin` equal to the request `Host`. Proxies that keep the `Host` header (Caddy, Fly, Render, most platform edges) need nothing. If yours rewrites it, either set `FORWARDED_ALLOW_IPS` (the entrypoint then also turns on `OASIS_TRUST_FORWARDED_HOST`, which accepts `X-Forwarded-Host` as the public host; note this switch is global, not limited to requests from the proxy's address) or list the public origin in `OASIS_ALLOWED_ORIGINS`. Cross-origin pages cannot forge `X-Forwarded-Host` from a browser (a custom header forces a CORS preflight that is refused), so honouring it is not a CSRF hole; it is honoured only when `OASIS_TRUST_FORWARDED_HOST=1`.

### Compose with Caddy (profile `tls`, untested end to end)

```bash
# .env.docker:  OASIS_DOMAIN=oasis.example.com   (DNS A/AAAA record -> this host; ports 80 and 443 open)
docker compose --profile tls up -d --build
```

Caddy (`docker/Caddyfile`) obtains and renews a Let's Encrypt certificate for `OASIS_DOMAIN`, proxies to `oasis:8000` on the compose network (172.30.77.0/24, which `FORWARDED_ALLOW_IPS` trusts by default) and is the only service publishing 80/443. Without a real domain it uses Caddy's internal CA and browsers will warn. Caddy built with Go 1.24 or later offers the hybrid post-quantum key exchange X25519MLKEM768 to clients that support it by default; the file does not force it (that would lock out every other client, see `tools/caddy/Caddyfile` and [pq-tls.md](pq-tls.md) for the forced local variant). Whether the pulled `caddy:2` image's Go version is recent enough was not checked. The PQ-TLS claim in this repo is tested with an OpenSSL client only, not browsers.

The `oasis` port is published on `127.0.0.1` by default so only the proxy (or an SSH tunnel) reaches it. To expose plain HTTP deliberately, set `OASIS_BIND=0.0.0.0`.

## 4. Hosting options (honest comparison; check current pricing and limits)

All of these must give you: one always-on instance, a persistent disk for `/data` (the SQLite file and key files), HTTPS, and env/secret settings. Free tiers change often; I did not verify any current price or quota here, so check each provider's page.

| Option | Good | Watch out |
|---|---|---|
| **Cheap VPS + compose + Caddy** (any provider) | Simplest fit: the files in this repo are written for it, full control, persistent volume, one fixed IP, no cold starts, predictable cost | You patch the OS and Docker, open only 22/80/443, set up backups yourself. Best choice for a judge instance that must stay up |
| **Fly.io** | Persistent volumes, global anycast TLS, `fly.toml` maps well to one container | A volume is tied to one machine and region; keep exactly 1 machine (no autoscale, `min_machines_running = 1`, don't auto-stop if you want no cold start). Fly's proxy forwards the client IP in headers, so set `FORWARDED_ALLOW_IPS` accordingly. Check current pricing and free allowance |
| **Render** | Git-connected builds, managed TLS, persistent disks on paid web services | Free web services sleep when idle (cold starts) and have no persistent disk, so state and keys would be lost on redeploy; use a paid instance with a disk and one instance only |
| **Railway** | Easy deploys from a Dockerfile, volumes available | Usage-based billing and trial limits, volume per service; single replica; check current pricing |
| **Google Cloud Run** | Managed HTTPS, scales to zero | Poorly suited: the filesystem is ephemeral (no durable `/data` without mounting a bucket or NFS, and SQLite on a network or object mount is a bad idea), scale-to-zero cold starts, and in-memory sessions/rate limits are lost whenever the instance restarts or a second instance appears. If you must: `--max-instances=1 --min-instances=1`, CPU always allocated, and accept that state is not durable |

General rules whichever you pick: 1 replica, 1 worker, the platform's `PORT` is honoured automatically, put the passcodes and `OASIS_KEY_PASSPHRASE` in the platform's secret store, mount a volume at `/data` owned by uid 10001 (a named Docker volume gets this automatically; for a bind mount run `chown -R 10001:10001 <dir>`), and set `FORWARDED_ALLOW_IPS` to the platform proxy's address range if documented, otherwise leave the default and accept that the per-IP limits then see the proxy's address.

## 5. Hosted security checklist

- [ ] Custom random passcodes (8+ chars, different per role); none is built in.
- [ ] `OASIS_KEY_PASSPHRASE` set **before first start** (a plaintext key file is not rewrapped by adding it later; for a fresh sandbox, wipe the volume first).
- [ ] Keep `OASIS_LLM=offline`. Live mode sends strangers' input to Bedrock on your AWS account and bill.
- [ ] HTTPS only; cookie is `Secure`; HTTP redirects to HTTPS (Caddy does this).
- [ ] `OASIS_JUDGE_MODE=1`, so `/docs`, `/redoc` and `/openapi.json` return 404 and limits are tighter.
- [ ] `FORWARDED_ALLOW_IPS` is the proxy only, never `*` on an exposed port. Container port not published to the internet directly.
- [ ] Back up the `/data` volume (see below). Losing `keys/` makes the encrypted database unreadable and changes the trust fingerprint that judges pinned.
- [ ] Rotate: change passcodes and restart (sessions use an HMAC secret that survives restarts, so also delete `keys/session_secret.json` to invalidate every session). Rotating the trust or data key = a new sandbox (reset).
- [ ] Rate limits are per client IP. Behind NAT (a university or event network) many judges share one IP and one failed-login budget; the 5 failed logins per minute and 10 red-team attempts per minute are then shared.
- [ ] Update the base image and rebuild regularly (`docker compose build --pull`).

**Honest limits, unchanged by Docker.** Authentication is demo-grade (per-role passcodes with a separate judge passcode, none built in; no per-person accounts, no MFA, approver device keys trusted on first use); it is a single process holding state in memory; the data is simulated (MOCK rates, simulated local anchor) and no real money moves; the post-quantum TLS claim is tested with OpenSSL only. A Docker deployment does not turn this into a production payments system. See [security-self-assessment.md](security-self-assessment.md).

## 6. How judges use it

Give judges the URL and the judge passcode (and optionally the student and parent ones). They follow [JUDGE_GUIDE.md](../JUDGE_GUIDE.md); the container behaves like `scripts/start_judge.*` with your passcodes: each judge session gets its own isolated red-team sandbox (at most 20, least recently used evicted). Only one student sandbox exists, shared by everyone logged in as student; use `Reset` in the UI or the commands below to start clean.

## 7. Operate

```bash
docker compose logs -f oasis                      # logs (no secrets; ledgers show 8-char key fingerprints)
git pull && docker compose up -d --build          # update / rebuild; /data is kept
docker compose build --pull --no-cache            # refresh the base image too
docker compose restart oasis

# reset the sandbox (deletes the database AND the keys: new trust fingerprint)
docker compose down && docker volume rm oasis_oasis-data && docker compose up -d
# reset only the student sandbox, keep keys: log in as student and press Reset, or
curl -X POST -b cookies.txt http://127.0.0.1:8000/api/reset

# back up / restore the volume (stop the app first for a consistent SQLite file)
docker compose stop oasis
docker run --rm -v oasis_oasis-data:/data -v "$PWD":/backup alpine tar czf /backup/oasis-data.tgz -C /data .
docker run --rm -v oasis_oasis-data:/data -v "$PWD":/backup alpine tar xzf /backup/oasis-data.tgz -C /data
docker compose start oasis
```

The volume name is `<project>_oasis-data`; compose's project name is `oasis`, so `oasis_oasis-data`. Treat the backup like a secret (it contains the key files; without `OASIS_KEY_PASSPHRASE` they are plaintext). `docker compose down -v` deletes the volume.

## 8. Building on a machine whose Docker lives on C:

Docker Desktop keeps its images, containers and volumes in a virtual disk image (VHDX), by default under `C:\Users\<you>\AppData\Local\Docker\wsl\...`. Building here writes layers to it. To move it to D: first: Docker Desktop, Settings, Resources, Advanced, **Disk image location**, choose a folder on D:, Apply and restart (Docker moves the data). Older WSL2-backend versions without that setting: `wsl --export docker-desktop-data` / `--import` to a D: path. Only then run `docker build`. Alternatively build on a Linux VPS or in CI and run it there; nothing in the build needs this machine.

## 9. What was and was not verified

Verified without Docker (2026-10-12): `tests/test_container_config.py` (Dockerfile non-root user, healthcheck, `EXPOSE 8000`, `PORT`, one worker, no `.env`/`data` copied, `.dockerignore`, compose volume and hardening, no real secrets, `bash -n` on the entrypoint, `.env.docker.example` clean, plus the cookie/Origin switches); `dockerfile-parse` parsed the Dockerfile; the exact COPY set was assembled in a temporary tree, the image's environment and the exact entrypoint and `CMD` ran from a clean Python 3.10 virtualenv (pip cache on D:). Result: refuses default, short and partly-default passcodes with a clear message; the app itself also refuses defaults in judge mode; with custom passcodes it served `/api/health`, the UI index and its three assets, hid `/docs`, accepted a red-team attempt, took a student intake to held, a signed approval to paid, the audit chain verified, `/api/benchmark` and the scripted demo worked (so the copied `eval/` files suffice); after a restart the trust fingerprint was identical and the registered approver key persisted; the database contained no plaintext payee and the three key files were passphrase-wrapped; the code directory was not written to; no `.env`, key or database file existed in the copied tree; `X-Forwarded-Proto: https` produced a `Secure` cookie and a trusted `X-Forwarded-Host` passed the Origin check while an untrusted or foreign origin got 403.

**Not verified (Docker not run):** `docker build` itself (the Linux wheels for the pinned requirements and the apt-free slim base), the image size, the `HEALTHCHECK` and read-only root filesystem under a real container runtime, volume ownership on first run, the compose file's `healthcheck`/`depends_on` interplay, the `tls` profile (Caddy, certificate issuance, and the Go version for X25519MLKEM768), uvicorn's CIDR handling in `--forwarded-allow-ips` on the pinned uvicorn, and every hosting-provider note above.
