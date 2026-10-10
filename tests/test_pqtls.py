import os
import re
import subprocess
from pathlib import Path

import pytest

CADDYFILE = Path(__file__).resolve().parent.parent / "tools" / "caddy" / "Caddyfile"


def test_caddyfile_pins_pq_curve_and_tls13():
    text = CADDYFILE.read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert re.search(r"^\s*curves\s+x25519mlkem768\s*$", code, re.M)
    assert "tls1.3" in code
    assert "reverse_proxy 127.0.0.1:8000" in code
    assert "tls internal" in code


def test_caddy_data_stays_off_appdata():
    text = CADDYFILE.read_text(encoding="utf-8")
    assert "AppData" not in text and "C:" not in text


@pytest.mark.pqtls
@pytest.mark.skipif(os.environ.get("OASIS_PQTLS_IT") != "1", reason="needs running Caddy + OpenSSL 3.5 in the distro (OASIS_PQTLS_IT=1)")
def test_live_negotiated_group():
    script = Path(__file__).resolve().parent.parent / "tools" / "caddy" / "verify-pq.ps1"
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    assert "Negotiated TLS1.3 group: X25519MLKEM768" in out
