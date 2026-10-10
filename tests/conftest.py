"""Hermetic test environment.

Tests must never reach the network or touch the real data/ directory, even if the developer's shell has
OASIS_LLM=groq and a real GROQ_API_KEY (oasis.config also loads .env with setdefault, so an empty value set
here wins). This runs before any test module imports oasis.config.
"""
import os
import socket

import pytest

os.environ["OASIS_DB"] = ":memory:"          # never touch the real SQLite file
os.environ["OASIS_LLM"] = "offline"
os.environ["OASIS_EXTRACT"] = "deterministic"
os.environ["OASIS_ANCHOR"] = "local"           # never reach for a FISCO chain (WSL) from a test
os.environ["OASIS_PASS_STUDENT"] = "student-demo"      # a developer .env must not change the test passcodes
os.environ["OASIS_PASS_PARENT"] = "parent-demo"
os.environ["OASIS_PASS_JUDGE"] = "judge-demo"
os.environ.pop("OASIS_KEY_PASSPHRASE", None)
os.environ["GROQ_API_KEY"] = ""              # empty but present: .env's setdefault cannot fill it in

from oasis import config  # noqa: E402  (must come after the environment is pinned)


@pytest.fixture(scope="session", autouse=True)
def _hermetic_config(tmp_path_factory):
    """Pin config even if oasis.config was imported earlier (plugin, collection order, IDE runner)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(config, "LLM_PROVIDER", "offline")
    mp.setattr(config, "EXTRACT_MODE", "deterministic")
    mp.setattr(config, "GROQ_API_KEY", "")
    mp.setattr(config, "DB_PATH", ":memory:")
    # GroqLLM's default cache_dir / usage.json and any other data/ default land in a throwaway directory.
    mp.setattr(config, "DATA_DIR", tmp_path_factory.mktemp("oasis_data"))
    yield
    mp.undo()


_LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"}


def _check(address):
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode()
        if host in _LOCAL:
            return
        raise RuntimeError(f"network access blocked in tests: attempted connection to {address!r}")
    # AF_UNIX / non-tuple addresses are local by construction.


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch):
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_create = socket.create_connection

    def connect(self, address):
        _check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(address)
        return real_connect_ex(self, address)

    def create_connection(address, *a, **k):
        _check(address)
        return real_create(address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    yield


@pytest.fixture
def api_session():
    """The real app with a fresh in-memory Session installed for this test only (restored after). Yields the api module."""
    from oasis.api import main as api
    saved = api.S
    api.S = api.Session(":memory:")
    try:
        yield api
    finally:
        api.S = saved


@pytest.fixture
def api_client(api_session):
    """TestClient logged in as the STUDENT (the role that runs intake, plans, the demo ...). Use `as_role` for others."""
    from fastapi.testclient import TestClient
    from auth_helpers import login
    return login(TestClient(api_session.app), "student")


@pytest.fixture
def as_role(api_session):
    """Factory: a separate TestClient (own cookie jar) logged in as the given role, on the same Session."""
    from auth_helpers import new_client
    return new_client
