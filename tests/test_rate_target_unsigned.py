"""A role string is not an approval: a student session must not release a rate-target conversion above the Tier-1 limit."""


def _balances():
    import oasis.api.main as api
    p = api.S.world.passport
    return p.balance("CNY"), p.balance("INR")


def test_unsigned_rate_target_above_the_auto_limit_cannot_be_released(api_client):
    import oasis.api.main as api
    mid = api.S.world.rates.mid(api.S.world.day_index)
    lim = api.S.world.passport.rules.tier1_auto_convert_cny
    r = api_client.post("/api/rate-target", json={"rate": mid * 0.9, "convert_cny": lim + 1})
    tid = r.json().get("id", "rt_01")
    api_client.post("/api/autonomy/tick", json={"days": 5})
    before = _balances()      # after the tick: recurring bills legitimately move money on their own
    ap = api_client.post("/api/rate-target/approve", json={"target_id": tid})
    assert r.status_code == 400 and "chat" in r.json()["detail"] and "sign" in r.json()["detail"]
    assert ap.status_code == 409 and "sign" in ap.json()["detail"]
    assert _balances() == before
    assert not any(t["status"] == "done" for t in api.S.world.passport.rules.rate_targets)


def test_approve_endpoint_releases_nothing_even_for_a_target_awaiting_approval(api_client):
    import oasis.api.main as api
    api.S.agent.set_rate_target(api.S.world.rates.mid(api.S.world.day_index) * 0.9, 20000)   # created behind the API
    api_client.post("/api/autonomy/tick", json={"days": 5})
    tid = api.S.world.passport.rules.rate_targets[0]["id"]
    before = _balances()
    assert api_client.post("/api/rate-target/approve", json={"target_id": tid}).status_code == 409
    assert _balances() == before


def test_a_target_within_the_limit_is_still_created(api_client):
    import oasis.api.main as api
    lim = api.S.world.passport.rules.tier1_auto_convert_cny
    mid = api.S.world.rates.mid(api.S.world.day_index)
    assert api_client.post("/api/rate-target", json={"rate": mid, "convert_cny": lim}).status_code == 200
