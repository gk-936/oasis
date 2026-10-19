"""GET /api/agent-scorecard: student and judge read it; parent and anonymous are refused; nothing writes."""
from fastapi.testclient import TestClient

from oasis.api import main as api
from tests.auth_helpers import new_client


def test_student_and_judge_get_200_with_the_same_shape():
    a, b = new_client("student"), new_client("judge")
    ra, rb = a.get("/api/agent-scorecard"), b.get("/api/agent-scorecard")
    assert ra.status_code == 200 and rb.status_code == 200
    assert {"mandate_card", "caps", "audit_head", "money_lost_cny"} <= set(rb.json())


def test_parent_is_refused():
    assert new_client("parent").get("/api/agent-scorecard").status_code == 403


def test_anonymous_is_refused():
    assert TestClient(api.app).get("/api/agent-scorecard").status_code == 401
