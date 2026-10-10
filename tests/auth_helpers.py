"""Test helpers for the authenticated API: log in as a role, register a device key, sign approvals like the browser does."""
from fastapi.testclient import TestClient

from oasis.trust.approvals import Device

PASS = {"student": "student-demo", "parent": "parent-demo", "judge": "judge-demo"}


def login(client: TestClient, role: str) -> TestClient:
    r = client.post("/api/auth/login", json={"role": role, "passcode": PASS[role]})
    assert r.status_code == 200, r.text
    return client


def new_client(role: str) -> TestClient:
    from oasis.api import main as api
    return login(TestClient(api.app), role)


class Approver:
    """A role's 'browser': holds the private device key, registers the public key, signs the pending draft."""

    def __init__(self, client: TestClient, role: str):
        self.client, self.role = client, role
        self.device = Device(role)
        r = client.post("/api/device/register", json={"public_key": self.device.public_key})
        assert r.status_code == 200, r.text
        self.key_id = r.json()["key_id"]

    def draft_hash(self, pending_id: str) -> str:
        pend = {p["id"]: p for p in self.client.get("/api/state").json()["pending"]}
        return pend[pending_id]["draft"]["draft_hash"]

    def signature(self, pending_id: str) -> str:
        return self.device.sign(self.draft_hash(pending_id))

    def approve(self, pending_id: str, **over):
        body = {"pending_id": pending_id, "signature": self.signature(pending_id), "key_id": self.key_id}
        body.update(over)
        return self.client.post("/api/approve", json=body)
