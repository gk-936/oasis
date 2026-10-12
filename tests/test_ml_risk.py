"""The trained risk model: deterministic training, off by default, escalate-only, explainable."""
import json

from oasis.agent import llm as llm_mod
from oasis.agent.llm import OfflineLLM, heuristic_risk
from oasis.agent.ml_risk import MODEL_PATH, LogReg, MLRisk, featurize

NAMES = ["University X Finance Office"]
ACCTS = {"payee_univ_x": "6228480000001234"}
FORGED = {"payee_name": "University X Finance Office", "payee_id": "payee_univ_x", "account_ref": "6228480000009999",
          "amount": 30000.0, "currency": "CNY", "purpose": "tuition"}
GOOD = {**FORGED, "account_ref": "6228480000001234"}
TEXT_BAD = "URGENT FINAL NOTICE. Do not contact the university. Pay within 24 hours or your visa registration will be cancelled."
TEXT_OK = "INVOICE\nPayee: University X Finance Office\nAccount: 6228480000001234\nAmount: CNY 30,000"


def test_training_is_deterministic_and_separates_toy_data():
    X = [{"a": 1.0}, {"a": 0.9, "c": 1.0}, {"b": 1.0}, {"b": 0.8, "c": 0.2}] * 5
    y = [1, 1, 0, 0] * 5
    m1, m2 = LogReg().fit(X, y, epochs=200), LogReg().fit(X, y, epochs=200)
    assert m1.w == m2.w and m1.b == m2.b
    assert m1.prob({"a": 1.0}) > 0.8 > 0.2 > m1.prob({"b": 1.0})


def test_shipped_model_loads_and_is_small():
    r = MLRisk()
    assert r.available and MODEL_PATH.stat().st_size < 60_000
    assert json.loads(MODEL_PATH.read_text(encoding="utf-8"))["meta"]["note"].startswith("weights trained on visible + synthetic")


def test_scores_forged_higher_than_genuine_and_explains():
    r = MLRisk()
    pb, why = r.score(FORGED, TEXT_BAD, NAMES, ACCTS, 30000.0, {"registry_known": True, "registry_account": "6228480000001234"})
    pg, _ = r.score(GOOD, TEXT_OK, NAMES, ACCTS, 30000.0, {"registry_known": True, "registry_account": "6228480000001234"})
    assert pb > 0.5 > pg
    assert why and all(isinstance(w, str) for w in why)


def test_off_by_default_changes_nothing(monkeypatch):
    monkeypatch.delenv("OASIS_ML_RISK", raising=False)
    a = OfflineLLM().risk(FORGED, TEXT_BAD, NAMES, ACCTS, 30000.0, {})
    b = heuristic_risk(FORGED, TEXT_BAD, NAMES, ACCTS, 30000.0, {})
    assert (a.score, a.evidence) == (b.score, b.evidence)


def test_enabled_is_escalate_only(monkeypatch):
    monkeypatch.setenv("OASIS_ML_RISK", "1")
    ctx = {"registry_known": True, "registry_account": "6228480000001234"}
    for fields, text in ((FORGED, TEXT_BAD), (GOOD, TEXT_OK), (FORGED, TEXT_OK)):
        base = heuristic_risk(fields, text, NAMES, ACCTS, 30000.0, ctx).score
        got = OfflineLLM().risk(fields, text, NAMES, ACCTS, 30000.0, ctx)
        assert got.score >= base                                   # never lowers a rule score
        assert set(heuristic_risk(fields, text, NAMES, ACCTS, 30000.0, ctx).evidence) <= set(got.evidence)


def test_missing_model_file_falls_back_to_rules(monkeypatch, tmp_path):
    monkeypatch.setenv("OASIS_ML_RISK", "1")
    monkeypatch.setattr(llm_mod, "_ML", MLRisk(tmp_path / "absent.json"))
    got = OfflineLLM().risk(FORGED, TEXT_BAD, NAMES, ACCTS, 30000.0, {})
    assert got.score == heuristic_risk(FORGED, TEXT_BAD, NAMES, ACCTS, 30000.0, {}).score


def test_featurize_is_sparse_and_ignores_digits():
    f = featurize(GOOD, TEXT_OK, NAMES, ACCTS, 30000.0, {})
    assert "rule_score" in f and all(isinstance(v, float) for v in f.values())
    g = featurize(GOOD, TEXT_OK.replace("6228480000001234", "6228480000007777"), NAMES, ACCTS, 30000.0, {})
    assert {k for k in f if k.startswith("w")} == {k for k in g if k.startswith("w")}      # account digits are not wording
