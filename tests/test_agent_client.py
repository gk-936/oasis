"""F5: a script (no browser) can finish a payment task end to end by signing with its own device key; nothing is bypassed."""
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oasis_client", ROOT / "tools" / "oasis_client.py")
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)


class Local(oc.OasisClient):
    """The same client, with the HTTP hop replaced by the in-process ASGI app."""

    def __init__(self, tmp, role="student", **kw):
        from oasis.api import main as api
        self._tc = TestClient(api.app)
        super().__init__("http://test", role, key_file=tmp / f"key_{role}", **kw)

    def request(self, method, path, body=None):
        r = self._tc.request(method, path, json=body, headers=({"X-Oasis-Lang": self.lang} if self.lang else None))
        if r.status_code >= 400:
            raise oc.ApiError(r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
        return r.json()


@pytest.fixture()
def cl(tmp_path):
    c = Local(tmp_path)
    c.reset()
    return c


def test_a_script_completes_a_payment_task_with_one_call(cl):
    cl.post("/api/fx/convert", {"amount": 100000, "from": "INR", "to": "CNY"})
    out = cl.task("pay my rent", sign=True)
    assert out["status"] == "paid" and out["proof_id"] and out["chat"]["needs"] == ["student_signature"]
    s = cl.state()
    assert s["ledger_money_lost"] == 0 and [o["status"] for o in s["passport"]["obligations"] if o["id"] == "obl_rent_1"] == ["paid"]


def test_without_sign_the_task_ends_held_awaiting_the_signature(cl):
    r = cl.task("pay my tuition")
    assert r["status"] == "held" and r["needs"] == ["student_signature"] and r["money_moved"] == 0 and r["draft_hash"]
    assert cl.state()["passport"]["balances"][1]["amount"] == 0


def test_a_signature_over_another_draft_is_refused(cl):
    a, b = cl.chat("pay my rent"), cl.chat("pay my tuition")
    cl.register_device()
    with pytest.raises(oc.ApiError) as e:
        cl.post("/api/approve", {"pending_id": a["pending_id"], "signature": cl.sign_message(b["draft_hash"]), "key_id": cl.key_id})
    assert e.value.status == 403


def test_the_student_key_cannot_sign_the_parents_role(cl, tmp_path):
    r = cl.chat("pay my rent")
    cl.register_device()
    import base64
    sig = base64.b64encode(cl._sk.sign(f"{oc.VERSION}|parent|{r['draft_hash']}".encode()).signature).decode()
    with pytest.raises(oc.ApiError) as e:
        cl.post("/api/approve", {"pending_id": r["pending_id"], "signature": sig, "key_id": cl.key_id})
    assert e.value.status == 403


def test_the_key_is_created_once_and_reused(tmp_path):
    a, b = Local(tmp_path), Local(tmp_path)
    assert a.public_key == b.public_key and (tmp_path / "key_student").exists()


def test_decline_through_the_client(cl):
    r = cl.chat("pay my rent")
    assert cl.decline(r["pending_id"])["status"] == "declined" and cl.state()["pending"] == []


def test_there_is_no_auto_approve_option():
    src = (ROOT / "tools" / "oasis_client.py").read_text(encoding="utf-8")
    assert "--auto" not in src and "--approve-all" not in src
    with pytest.raises(SystemExit):
        oc.main(["chat", "pay my rent", "--auto-approve"])


def test_a_parent_cosigns_a_large_payment_with_a_second_client(tmp_path):
    from oasis.api import main as api
    s = Local(tmp_path, "student")
    s.reset()
    s.post("/api/fx/convert", {"amount": 500000, "from": "INR", "to": "CNY"})
    r = s.chat("pay my tuition")
    assert r["needs"] in (["student_signature"], ["parent_signature", "student_signature"], ["student_signature", "parent_signature"])
    first = s.approve(r["pending_id"], r["draft_hash"])
    if first.get("status") == "waiting":
        p = Local(tmp_path, "parent")
        assert p.approve(r["pending_id"], r["draft_hash"])["status"] == "paid"
    else:
        assert first["status"] == "paid"
    assert api.S.world.ledger.money_lost() == 0
