from demo_helpers import status

TUITION = ("Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
           "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15")


def test_state_and_intake_approve_proof_flow(api_client):
    c = api_client
    s = c.get("/api/state").json()
    assert s["mock_note"].startswith("MOCK") and s["passport"]["student"]["name"]
    o = c.post("/api/intake", json={"text": TUITION}).json()
    assert o["status"] == "held" and o["pending_id"]
    r = c.post("/api/approve", json={"pending_id": o["pending_id"], "role": "student"}).json()
    assert r["status"] == "paid" and r["proof_id"]
    assert c.get(f"/api/proof/{r['proof_id']}/verify").json()["ok"]
    assert c.get("/api/audit/verify").json()["ok"]


def test_parent_coapproval_flow(api_client):
    c = api_client
    o = c.post("/api/intake", json={"text": "Payee: Arjun (own CNY account)\nPayee ID: payee_student_self\n"
                                            "Account: acct_student_cny\nAmount: CNY 8,000\nPurpose: family_support",
                                    "remitter": "parent"}).json()
    pid = o["pending_id"]
    assert c.post("/api/approve", json={"pending_id": pid, "role": "student"}).json()["status"] == "waiting"
    pp = c.get("/api/parent/pending").json()
    assert pp["pending"] and pp["pending"][0]["language"] == "ta"
    assert c.post("/api/approve", json={"pending_id": pid, "role": "parent"}).json()["status"] == "paid"


def test_redteam_and_demo(api_client):
    c = api_client
    r = c.post("/api/redteam", json={"text": TUITION.replace("6228480000001234", "6228480000009999")}).json()
    assert r["status"] == "rejected" and r["money_lost_this_attempt"] == 0
    d = c.post("/api/demo/run", json={"run": "attack"}).json()
    assert d["money_lost"] == 0 and d["audit_ok"]
    assert [status(d, k) for k in ("Forged invoice", "rewritten after approval", "Hidden page injection")] ==         ["rejected", "frozen", "frozen"]
    d = c.post("/api/demo/run", json={"run": "legit"}).json()
    assert [status(d, k) for k in ("Tuition to the verified", "Parent co-approves", "Landlord's genuine")] == ["paid"] * 3
    assert c.post("/api/chat", json={"message": "what do I owe?"}).json()["reply"]
