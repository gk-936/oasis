"""The execution-evidence generator: protected runs lose nothing, unprotected runs do, replays match, no secrets leak."""
import json

from eval import execution_evidence as ee


def test_execution_evidence_claims():
    o = ee.collect()
    s = o["summary"]
    assert s["money_lost_cny"]["PROTECTED"] == 0
    assert s["money_lost_cny"]["UNPROTECTED"] > 0
    assert s["attacks_stopped"]["PROTECTED"] == s["attack_cases"]
    assert s["legit_paid"]["PROTECTED"] == s["legit_cases"]
    assert s["executor_blocked"] == s["executor_attacks"] and s["executor_control_paid"]
    assert s["executor_extra_money_moved"] == 0
    assert o["meta"]["problem_cases_replay_identical"] and not o["meta"]["network_used"]
    assert o["redaction"]["ok"]
    assert o["integrity"]["tamper_test"]["intact_verifies"] and not o["integrity"]["tamper_test"]["after_edit_verifies"]
    json.dumps(o, default=str)
