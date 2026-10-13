from eval.netting_bench import cohort, run
from oasis.netting.core import Payment, match, net


def test_conservation_of_value():
    pool = cohort(200)
    r = net(pool)
    side = {"INR_CNY": 0.0, "CNY_INR": 0.0}
    for row in r["payments"]:
        assert abs(row["matched_cny"] + row["residual_cny"] - row["amount_cny"]) < 0.01
        side[row["direction"]] += row["matched_cny"]
    assert abs(side["INR_CNY"] - side["CNY_INR"]) < 0.5
    assert abs(side["INR_CNY"] - r["matched_volume_cny"]) < 0.5


def test_no_match_across_deadline_violation():
    pool = [Payment("a", "INR_CNY", 5000, 1), Payment("b", "CNY_INR", 5000, 10)]
    assert match(pool) == [] and net(pool)["saving_cny"] == 0


def test_unverified_or_unapproved_never_pooled():
    pool = [Payment("a", "INR_CNY", 5000, 7, payee_verified=False), Payment("b", "CNY_INR", 5000, 7),
            Payment("c", "INR_CNY", 5000, 7, approved=False)]
    assert match(pool) == []


def test_pool_of_one_saves_nothing_and_saving_grows():
    assert net(cohort(1))["saving_cny"] == 0
    rows = {x["pool_size"]: x for x in run()["rows"]}
    assert rows[1]["saving_cny"] == 0
    assert rows[1000]["saving_cny"] > rows[50]["saving_cny"] > rows[2]["saving_cny"]


def test_deterministic_and_api(api_client):
    assert match(cohort(50)) == match(cohort(50))
    r = api_client.post("/api/netting/simulate", json={"pool_size": 50})
    assert r.status_code == 200 and r.json()["saving_cny"] > 0
