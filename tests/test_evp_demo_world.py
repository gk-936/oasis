"""QA 2026-10-15: after the scripted demo, issuing an Evidence Passport for a demo payment could not be shared (400)."""


def test_evidence_passport_for_a_demo_payment_verifies_and_shares(api_client):
    c = api_client
    for run in ("legit", "attack", "legit"):          # the demo may have been played before
        c.post("/api/demo/start", json={"run": run, "mode": "offline"})
        for _ in range(8):
            if c.post("/api/demo/next", json={}).json().get("done"):
                break
    pays = c.get("/api/evidence-passport/payments").json()["payments"]
    assert pays
    p = c.post("/api/evidence-passport/issue", json={"intent_id": pays[0]["intent_id"], "outcome": "credited"}).json()
    v = c.post("/api/evidence-passport/verify", json=p).json()
    failed = [k for k, x in v.items() if x is False]
    assert v["ok"], failed
    assert c.post("/api/evidence-passport/share", json={"passport": p}).status_code == 200
