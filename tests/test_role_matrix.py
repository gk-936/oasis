"""Every endpoint guarded by a role dependency refuses every other role (403) and anonymous callers (401), whatever the body.

Walks the app's real routes, so a new state-changing endpoint without a role dependency, or with a wrong one, is caught."""
import inspect

import pytest

from tests.auth_helpers import new_client

ROLES = ("student", "parent", "judge")


def _guarded():
    from oasis.api import main as api
    out = []
    for r in api.app.routes:
        dep = getattr(r, "dependant", None)
        if dep is None:
            continue
        allowed = None
        stack = list(dep.dependencies)
        while stack:
            d = stack.pop()
            stack.extend(d.dependencies)
            if getattr(d.call, "__qualname__", "") == "require.<locals>.dep":
                allowed = set(inspect.getclosurevars(d.call).nonlocals["roles"])
        if allowed:
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                out.append((m, r.path, allowed))
    return out


GUARDED = _guarded()


def _call(c, method, path):
    url = path.replace("{", "").replace("}", "")      # path params become literal text; the guard runs before any lookup
    return c.request(method, url, json={} if method != "GET" else None)


def test_the_walk_found_the_guarded_endpoints():
    assert len(GUARDED) >= 50
    assert any(m == "POST" and p == "/api/approve" and a == {"student", "parent"} for m, p, a in GUARDED)


@pytest.mark.parametrize("method,path,allowed", GUARDED, ids=[f"{m} {p}" for m, p, _ in GUARDED])
def test_other_roles_and_anonymous_are_refused(api_client, method, path, allowed):
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    anon = _call(TestClient(api.app), method, path)
    assert anon.status_code == 401, (method, path, "anonymous", anon.status_code)
    for role in ROLES:
        if role in allowed:
            continue
        r = _call(new_client(role), method, path)
        assert r.status_code == 403, (method, path, role, r.status_code)


def test_every_state_changing_endpoint_has_a_role_guard_or_is_a_known_public_one():
    from oasis.api import main as api
    guarded = {(m, p) for m, p, _ in GUARDED}
    open_ = sorted(f"{m} {r.path}" for r in api.app.routes if getattr(r, "methods", None) and getattr(r, "dependant", None)
                   for m in r.methods if m in ("POST", "PUT", "PATCH", "DELETE") and (m, r.path) not in guarded)
    # PUBLIC by design: login, and read-only verifiers that check a pasted proof against public keys (no state, no secrets).
    allowed_public = {"POST /api/proof/verify", "POST /api/evidence-passport/verify", "POST /api/reliability/verify",
                      "POST /api/trust-pass/verify", "POST /api/trust-pass/vc/verify"}
    extra = [x for x in open_ if x not in allowed_public and not x.startswith("POST /api/auth/")]
    assert extra == [], extra
