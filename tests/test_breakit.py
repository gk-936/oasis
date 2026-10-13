ATTACK = ("INVOICE\nPayee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000009999\n"
          "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15\nURGENT: our bank details changed.")


def test_breakit(api_client, as_role):
    j = as_role("judge")
    a = j.post("/api/breakit/attack", json={"text": ATTACK}).json()
    assert a["blocked"] and a["money_lost"] == 0 and a["rules"] and a["cny_saved"] == 30000 and a["mock"]
    g = j.post("/api/breakit/generate", json={"n": 8}).json()
    sb = g["scoreboard"]
    assert sb["total"] == 8 and sb["money_lost"] == 0 and sb["blocked"] >= 1
    assert [v["text"] for v in g["variants"]] == [v["text"] for v in j.post("/api/breakit/generate", json={"n": 8}).json()["variants"]]
    assert j.post("/api/breakit/attack", json={"text": " "}).status_code == 400


def test_breakit_parent_refused(as_role):
    assert as_role("parent").post("/api/breakit/attack", json={"text": "x"}).status_code in (401, 403)
