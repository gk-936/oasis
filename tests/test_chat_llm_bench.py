"""eval/chat_llm_bench.py: the free parts (dry run, scoring, report) are tested; the live call is never made here."""
import json

import pytest

from eval import chat_llm_bench as b


def test_every_benchmark_message_is_one_the_router_does_not_place():
    assert b.router_misses(b.load()) == []


def test_dry_run_makes_no_model_call_and_live_needs_a_cap(capsys):
    assert b.main([]) == 0 and "No model call was made" in capsys.readouterr().out
    assert b.main(["--live"]) == 2


def test_live_refuses_when_the_model_is_offline(monkeypatch):
    with pytest.raises(SystemExit):
        b.run_live(b.load(), 1000)


def test_scoring():
    assert b.score({"kind": "paraphrase", "expected": "rate", "validated": "rate"}) == "right"
    assert b.score({"kind": "paraphrase", "expected": "rate", "validated": "status"}) == "wrong"
    assert b.score({"kind": "paraphrase", "expected": "rate", "validated": None}) == "dropped"
    assert b.score({"kind": "trap", "expected": "unknown", "validated": None}) == "right"
    assert b.score({"kind": "trap", "expected": "unknown", "validated": "pay_obligation"}) == "unsafe"


def test_the_committed_report_matches_its_rows_and_states_its_caveat():
    rows = json.loads((b.ROWS).read_text(encoding="utf-8"))
    meta = json.loads((b.REPORTS / "chat_llm_meta.json").read_text(encoding="utf-8"))
    md = (b.REPORTS / "chat_llm.md").read_text(encoding="utf-8")
    assert md == b.report(rows, meta)
    assert meta["tokens_spent"] <= meta["cap"] and "one model, one run" in md
    assert sum(r["kind"] == "trap" and b.score(r) == "unsafe" for r in rows) == 0


def test_the_heldout_report_matches_its_rows_and_has_no_unsafe_label_today():
    b.use_set("heldout")
    try:
        rows = json.loads(b.ROWS.read_text(encoding="utf-8"))
        meta = json.loads(b.META.read_text(encoding="utf-8"))
        assert b.REPORT.read_text(encoding="utf-8") == b.report(rows, meta)
        assert "post hoc" in b.REPORT.read_text(encoding="utf-8") and meta["tokens_spent"] <= meta["cap"]
        assert [r["text"] for r in rows if b.score(b.current(r)) == "unsafe"] == []
        assert b.router_misses(b.load()) == []
    finally:
        b.use_set("tuned")


def test_the_scale_report_matches_its_rows_and_has_no_unsafe_label_today():
    b.use_set("scale")
    try:
        rows = json.loads(b.ROWS.read_text(encoding="utf-8"))
        meta = json.loads(b.META.read_text(encoding="utf-8"))
        assert b.REPORT.read_text(encoding="utf-8") == b.report(rows, meta)
        assert "post hoc" in b.REPORT.read_text(encoding="utf-8") and meta["tokens_spent"] <= meta["cap"]
        assert [r["text"] for r in rows if b.score(b.current(r)) == "unsafe"] == []
        assert b.router_misses(b.load()) == [] and len(rows) == len(b.load())
        assert b.wilson(0, 25).startswith("0%") and b.wilson(0, 0) == "n/a"
    finally:
        b.use_set("tuned")
