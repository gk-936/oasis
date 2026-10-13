"""Static, hermetic checks of the container packaging (no Docker is run) + the small proxy/HTTPS backend switches."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _instructions(text: str) -> list[tuple[str, str]]:
    """(INSTRUCTION, args) with line continuations joined and comment lines dropped."""
    out, buf = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not buf and (not line or line.startswith("#")):
            continue
        if buf and line.startswith("#"):          # a comment line inside a continued instruction
            continue
        buf += (" " if buf else "") + line.rstrip("\\").strip()
        if not raw.rstrip().endswith("\\"):
            kw, _, rest = buf.partition(" ")
            out.append((kw.upper(), rest.strip()))
            buf = ""
    return out


DOCKERFILE = _instructions(_read("Dockerfile"))


def test_dockerfile_non_root_user_is_last_user():
    users = [a for k, a in DOCKERFILE if k == "USER"]
    assert users and users[-1] not in ("root", "0", "0:0")


def test_dockerfile_healthcheck_expose_port_and_workdir():
    kws = {k for k, _ in DOCKERFILE}
    assert "HEALTHCHECK" in kws and "WORKDIR" in kws
    hc = next(a for k, a in DOCKERFILE if k == "HEALTHCHECK")
    assert "/api/health" in hc and "curl" not in hc and "wget" not in hc
    assert ("EXPOSE", "8000") in DOCKERFILE
    assert ("WORKDIR", "/app") in DOCKERFILE


def test_dockerfile_python_base_and_pip_no_cache():
    froms = [a for k, a in DOCKERFILE if k == "FROM"]
    assert froms and all(re.match(r"python:3\.1[12]-slim", f) for f in froms)
    assert any("--no-cache-dir" in a for k, a in DOCKERFILE if k == "RUN" and "pip install" in a)


def test_dockerfile_cmd_honours_port_single_worker_and_proxy_headers():
    cmd = next(a for k, a in DOCKERFILE if k == "CMD")
    assert "uvicorn oasis.api.main:app" in cmd and "${PORT:-8000}" in cmd and "0.0.0.0" in cmd
    assert "--workers 1" in cmd and "--proxy-headers" in cmd and "--forwarded-allow-ips" in cmd


def test_dockerfile_copies_no_secrets_or_state():
    for k, a in DOCKERFILE:
        if k in ("COPY", "ADD"):
            srcs = [t for t in a.split() if not t.startswith("--")][:-1]
            for s in srcs:
                assert not re.search(r"(^|/)\.env", s) and not s.startswith("data") and s not in (".", "./"), a
                assert "keys" not in s and "node_modules" not in s, a
    env = " ".join(a for k, a in DOCKERFILE if k == "ENV")
    for var in ("OASIS_PASS_", "OASIS_KEY_PASSPHRASE", "AWS_SECRET_ACCESS_KEY", "OASIS_ALLOW_DEMO_PASSCODES"):
        assert var not in env, f"{var} must come from the run-time environment, not the image"
    for needed in ("OASIS_LLM=offline", "OASIS_RATES=live", "OASIS_ANCHOR=local", "OASIS_DB=/data/",
                   "OASIS_DATA_KEY=/data/", "OASIS_TRUST_KEY=/data/", "OASIS_SESSION_SECRET_FILE=/data/"):
        assert needed in env
    assert any(k == "VOLUME" and "/data" in a for k, a in DOCKERFILE)


def test_dockerfile_copies_what_the_app_reads():
    copied = " ".join(a for k, a in DOCKERFILE if k == "COPY")
    for p in ("oasis/", "frontend/dist/", "eval/approver.py", "eval/reports/", "docker/entrypoint.sh"):
        assert p in copied
    assert (ROOT / "oasis" / "trust" / "rules" / "inr_cny.yaml").exists() and (ROOT / "frontend" / "dist" / "index.html").exists()
    assert (ROOT / "eval" / "__init__.py").exists() and (ROOT / "eval" / "approver.py").exists()


def test_dockerignore_excludes_secrets_and_junk():
    lines = [ln.strip() for ln in _read(".dockerignore").splitlines() if ln.strip() and not ln.startswith("#")]
    for must in (".env", ".env.*", "data/", ".venv", "node_modules", ".git", "tests/", "tools/", "**/__pycache__", "*.pdf"):
        assert must in lines, must
    # the only .env re-inclusions allowed are the two example files
    assert {ln for ln in lines if ln.startswith("!.env")} <= {"!.env.example", "!.env.docker.example"}
    assert not any(ln.startswith("!data") for ln in lines)


def test_entrypoint_syntax_and_policy():
    ep = ROOT / "docker" / "entrypoint.sh"
    text = ep.read_text(encoding="utf-8")
    assert "\r" not in text and text.startswith("#!/bin/sh")
    for sh in ("sh", "bash"):
        exe = shutil.which(sh)
        if exe:
            r = subprocess.run([exe, "-n", str(ep)], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
    assert "OASIS_ALLOW_DEMO_PASSCODES" in text and "OASIS_REQUIRE_CUSTOM_PASSCODES" in text and 'exec "$@"' in text
    assert not re.search(r"gsk_[A-Za-z0-9]{10,}", text)


def test_compose_has_volume_hardening_and_no_secrets():
    text = _read("docker-compose.yml")
    assert re.search(r"^\s+- oasis-data:/data\s*$", text, re.M) and re.search(r"^volumes:\s*\n\s+oasis-data:", text, re.M)
    assert "env_file: .env.docker" in text and "read_only: true" in text and "no-new-privileges" in text
    assert "restart:" in text and "healthcheck:" in text and "tmpfs:" in text and 'profiles: ["tls"]' in text
    assert not re.search(r"AKIA[A-Z0-9]{12,}|OASIS_PASS_\w+:\s*\S|OASIS_KEY_PASSPHRASE:\s*\S|AWS_SECRET_ACCESS_KEY:\s*\S", text)
    assert "127.0.0.1" in text            # published on loopback by default


def test_env_docker_example_has_no_real_secrets_and_documents_every_variable():
    text = _read(".env.docker.example")
    assert not re.search(r"gsk_[A-Za-z0-9]+", text) and not re.search(r"\bsk-[A-Za-z0-9]{10,}", text)
    for var in ("OASIS_PASS_STUDENT", "OASIS_PASS_PARENT", "OASIS_PASS_JUDGE", "OASIS_KEY_PASSPHRASE", "OASIS_JUDGE_MODE",
                "OASIS_ALLOW_DEMO_PASSCODES", "AWS_SECRET_ACCESS_KEY", "OASIS_LLM", "OASIS_COOKIE_SECURE", "OASIS_ALLOWED_ORIGINS"):
        assert re.search(rf"^{var}=", text, re.M), var
    for var in ("OASIS_PASS_STUDENT", "OASIS_PASS_PARENT", "OASIS_PASS_JUDGE", "OASIS_KEY_PASSPHRASE", "AWS_SECRET_ACCESS_KEY"):
        assert re.search(rf"^{var}=\s*$", text, re.M), f"{var} must ship empty"
    assert re.search(r"^OASIS_LLM=offline\s*$", text, re.M)
    assert "NOT recommended" in text


def test_no_env_files_or_keys_in_build_inputs():
    for p in ("frontend/dist", "oasis", "eval/reports", "docker"):
        for f in (ROOT / p).rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                assert not f.name.startswith(".env") and "trust_key" not in f.name and "data_key" not in f.name, f


# ---------------------------------------------------------------- backend switches (proxy / HTTPS)
@pytest.fixture
def api(monkeypatch):
    from oasis.api import main as m
    for v in ("OASIS_COOKIE_SECURE", "OASIS_ALLOWED_ORIGINS", "OASIS_TRUST_FORWARDED_HOST"):
        monkeypatch.delenv(v, raising=False)
    return m


def _login(c):
    return c.post("/api/auth/login", json={"role": "student", "passcode": "student-demo"})


def test_cookie_not_secure_on_plain_http_by_default(api):
    r = _login(TestClient(api.app))
    assert r.status_code == 200 and "secure" not in r.headers["set-cookie"].lower()


def test_cookie_secure_when_forced_or_https(api, monkeypatch):
    assert "secure" in _login(TestClient(api.app, base_url="https://testserver")).headers["set-cookie"].lower()
    monkeypatch.setenv("OASIS_COOKIE_SECURE", "1")
    assert "secure" in _login(TestClient(api.app)).headers["set-cookie"].lower()


def test_forwarded_host_is_ignored_unless_trusted(api, monkeypatch):
    c = TestClient(api.app)
    _login(c)
    hdr = {"Origin": "https://oasis.example.com", "X-Forwarded-Host": "oasis.example.com"}
    assert c.post("/api/reset", headers=hdr).status_code == 403                  # default: unchanged behaviour
    monkeypatch.setenv("OASIS_TRUST_FORWARDED_HOST", "1")
    assert c.post("/api/reset", headers=hdr).status_code == 200                  # proxy declared trusted
    assert c.post("/api/reset", headers={"Origin": "https://evil.example", "X-Forwarded-Host": "oasis.example.com"}).status_code == 403
    assert c.post("/api/reset", headers={"Origin": "null", "X-Forwarded-Host": "null"}).status_code == 403


def test_allowed_origins_allow_list_is_exact(api, monkeypatch):
    c = TestClient(api.app)
    _login(c)
    monkeypatch.setenv("OASIS_ALLOWED_ORIGINS", "https://oasis.example.com, https://b.example")
    assert c.post("/api/reset", headers={"Origin": "https://oasis.example.com"}).status_code == 200
    assert c.post("/api/reset", headers={"Origin": "https://b.example"}).status_code == 200
    assert c.post("/api/reset", headers={"Origin": "https://oasis.example.com.evil.net"}).status_code == 403
    assert c.post("/api/reset", headers={"Origin": "http://evil.example"}).status_code == 403
