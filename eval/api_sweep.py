"""API authorization sweep. OFFLINE, no model, no network.

Run:  OASIS_LLM=offline PYTHONPATH=. python -m eval.api_sweep     (writes eval/reports/api_sweep.{json,md})

Every route of the FastAPI app is called as four identities (none, student, parent, judge) with empty and junk bodies. The allowed
roles are read from each route's `require(...)` dependency, so the sweep checks the code against itself, not against a hand-kept list.
Checks:  (1) an identity outside the declared roles gets 401 (anonymous) or 403, never 2xx;  (2) no call returns a 5xx;
(3) a route with NO role dependency must be on the explicit public list, and a public route must not change state
(audit length, pending drafts, obligations, ledger balances compared before and after).
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ["OASIS_LLM"] = "offline"
os.environ["OASIS_DB"] = ":memory:"
os.environ["OASIS_EXTRACT"] = "deterministic"
os.environ["OASIS_ANCHOR"] = "local"
os.environ["OASIS_PASS_STUDENT"], os.environ["OASIS_PASS_PARENT"], os.environ["OASIS_PASS_JUDGE"] = "student-demo", "parent-demo", "judge-demo"

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from oasis.api import main as api  # noqa: E402

REPORTS = Path(__file__).resolve().parent / "reports"
IDENTITIES = ("none", "student", "parent", "judge")
# Routes that may be called without a session. Anything else without a role dependency is a finding.
PUBLIC = {"/api/health", "/api/auth/config", "/api/auth/login", "/api/auth/passkey/login/finish", "/api/trust/fingerprint",
          "/api/proof/verify", "/api/proof/{intent_id}/verify", "/api/trust-pass/check/{code}", "/api/trust-pass/verify",
          "/api/trust-pass/vc/verify", "/api/evidence-passport/check/{code}", "/api/evidence-passport/verify", "/api/auth/me", "/api/reliability/verify"}
SKIP = {"/api/auth/logout"}                      # would end the sweep's own session; covered by tests/test_auth
BODIES = ({}, {"x": 1, "amount": "NaN", "payee_id": "../../etc/passwd", "text": "A" * 5000})


def roles_of(route: APIRoute):
    """Union of roles in the route's require(...) dependencies; None if it has none."""
    found, stack = None, list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        call = d.call
        if getattr(call, "__qualname__", "") == "require.<locals>.dep" and call.__closure__:
            for cell in call.__closure__:
                if isinstance(cell.cell_contents, tuple):
                    found = (found or set()) | set(cell.cell_contents)
        stack.extend(d.dependencies)
    return found


def state_fingerprint() -> str:
    w = api.S.world
    return json.dumps([len(w.audit.entries), len(api.S.pending), len(w.proofs),
                       [(o.id, o.amount_paid, o.status) for o in w.passport.obligations],
                       sorted((k, round(a.balance, 2)) for k, a in w.ledger.accounts.items())], default=str)


def client_for(role: str) -> TestClient:
    c = TestClient(api.app, raise_server_exceptions=False)
    if role != "none":
        r = c.post("/api/auth/login", json={"role": role, "passcode": os.environ[f"OASIS_PASS_{role.upper()}"]})
        assert r.status_code == 200, r.text
    return c


def call(c: TestClient, method: str, path: str, body):
    url = path.replace("{plan_id}", "x").replace("{jid}", "x").replace("{code}", "x").replace("{intent_id}", "x")
    try:
        r = c.request(method, url, json=body if method in ("POST", "PUT", "PATCH") else None)
        return r.status_code
    except Exception as e:  # noqa: BLE001
        return f"exc:{type(e).__name__}"


def run() -> dict:
    if api.S.world.llm.name != "offline-deterministic":
        raise SystemExit("refusing to run: the model is not offline")
    rows, findings = [], []
    routes = [r for r in api.app.routes if isinstance(r, APIRoute) and r.path.startswith("/api")]
    for route in sorted(routes, key=lambda r: r.path):
        if route.path in SKIP:
            continue
        declared = roles_of(route)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            row = {"path": route.path, "method": method, "roles": sorted(declared) if declared else None, "codes": {}}
            if declared is None and route.path not in PUBLIC:
                findings.append({"path": route.path, "method": method, "problem": "no role dependency and not on the public list"})
            for ident in IDENTITIES:
                codes = []
                for body in BODIES:
                    c = client_for(ident)
                    api.S.reset()
                    c = client_for(ident)
                    before = state_fingerprint()
                    code = call(c, method, route.path, body)
                    after = state_fingerprint()
                    codes.append(code)
                    if isinstance(code, str) or code >= 500:
                        findings.append({"path": route.path, "method": method, "as": ident, "problem": f"server error {code}"})
                    if declared is not None and ident not in declared and ident != "none" and code != 429 and not (isinstance(code, int) and code == 403):
                        findings.append({"path": route.path, "method": method, "as": ident, "problem": f"outside roles {sorted(declared)} got {code}, not 403"})
                    if declared is not None and ident == "none" and code not in (401, 429):
                        findings.append({"path": route.path, "method": method, "as": ident, "problem": f"anonymous got {code}, not 401"})
                    if declared is None and ident == "none" and route.path not in ("/api/auth/login",) and before != after:
                        findings.append({"path": route.path, "method": method, "as": ident, "problem": "a public route changed state"})
                row["codes"][ident] = codes
            rows.append(row)
    api.S.reset()
    return {"meta": {"run": datetime.now().strftime("%Y-%m-%d %H:%M"), "routes": len(rows), "calls": len(rows) * len(IDENTITIES) * len(BODIES),
                     "caveat": "Reads the allowed roles from the code's own require(...) dependencies and checks the responses. It does not "
                               "check that the roles themselves are the right ones; that is the security evidence matrix and a human review."},
            "rows": rows, "findings": findings}


def markdown(rep: dict) -> str:
    m = rep["meta"]
    pub = [r for r in rep["rows"] if r["roles"] is None]
    L = ["# API authorization sweep (offline)", "", f"Run: {m['run']}", "", f"**Caveat.** {m['caveat']}", "", "| Check | Result |", "|---|---|",
         f"| Route/method pairs | {m['routes']} |", f"| Calls made (4 identities, 2 bodies) | {m['calls']} |",
         f"| Routes without a role dependency (public) | {len(pub)} |", f"| Findings | {len(rep['findings'])} |", ""]
    L += ["## Findings", ""] + ([f"- `{f['method']} {f['path']}`" + (f" as {f['as']}" if "as" in f else "") + f": {f['problem']}" for f in rep["findings"]] or ["None."])
    L += ["", "## Public routes seen", ""] + [f"- `{r['method']} {r['path']}`" for r in pub] + [""]
    return "\n".join(L)


def main() -> int:
    rep = run()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "api_sweep.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (REPORTS / "api_sweep.md").write_text(markdown(rep), encoding="utf-8")
    print(markdown(rep))
    return 0 if not rep["findings"] else 1


if __name__ == "__main__":
    sys.exit(main())
