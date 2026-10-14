"""docs/openapi.json is the evaluator-facing API reference (the live /docs is off in judge mode). It must match the app."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "tools" / "export_openapi.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_committed_openapi_file_matches_the_app():
    t = _tool()
    assert json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8")) == json.loads(t.build()), \
        "run: OASIS_LLM=offline OASIS_DB=:memory: PYTHONPATH=. python tools/export_openapi.py"


def test_it_documents_the_task_endpoints_and_leaks_no_secret():
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    for path in ("/api/auth/login", "/api/chat", "/api/approve", "/api/state", "/api/reset", "/api/device/register", "/api/proof/verify"):
        assert path in spec["paths"], path
    chat = spec["components"]["schemas"]["ChatOut"]["properties"]
    assert {"reply", "intent", "status", "pending_id", "draft_hash", "needs", "money_moved", "proof_id"} <= set(chat)
    text = json.dumps(spec)
    for secret in ("student-demo", "parent-demo", "judge-demo", "OASIS_PASS", "BEGIN PRIVATE KEY"):
        assert secret not in text
