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


def test_split_payments_first_part_passes_and_held_parts_move_nothing():
    """P6: splitting is only visible from the 2nd part, so the first (below the threshold) pays; held parts leave no trace."""
    case = next(c for c in ee.PROBLEM_CASES if c["id"].startswith("P6"))
    rec = ee.run_case(case, "PROTECTED")
    st = [s["outcome"]["status"] for s in rec["steps"]]
    assert st == ["paid", "held", "held"]
    assert all(not s["ledger_transfers"] for s in rec["steps"][1:])
    assert all(s["outcome"]["rule"] == "R06_corridor" for s in rec["steps"][1:])
    assert rec["parent_topups_cny"] == 3300.0 <= rec["coapproval_threshold_cny"]
    assert {c["account"]: c["change"] for c in rec["ledger_changes"]} == {"acct_student_cny": 3300.0, "acct_parent": -3300.0}
    assert rec["audit_ok"]
    assert ee.verdict(case, rec)["result"] == "PARTLY HELD"
