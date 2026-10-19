"""Write the scripted-demo evidence (eval/reports/demo.json and demo.md): both runs, step titles and
headlines, money lost, audit-chain verification and the audit-chain head hash. Offline, no network.

    PYTHONPATH=. python -m eval.demo_log
"""
from __future__ import annotations
import json
from pathlib import Path

from oasis.demo import play

REPORTS = Path(__file__).parent / "reports"


def main() -> None:
    runs = {name: play(name) for name in ("legit", "attack", "autonomy")}
    again = {name: play(name)["audit_head"] for name in runs}
    out = {n: {"audit_head": r["audit_head"], "audit_entries": r["audit_entries"], "audit_ok": r["audit_ok"],
               "money_lost_cny": r["money_lost"], "llm": r["llm"], "network_used": r["network_used"], "seed": r["seed"],
               "replay_head_identical": again[n] == r["audit_head"],
               "steps": [{"title": s["title"], "headline": s.get("headline", "")} for s in r["steps"]]}
           for n, r in runs.items()}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "demo.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    md = ["# Scripted demo log (MOCK data, offline model, seeded DEMO keys)", "",
          "Each run is replayed twice; the audit-chain head must be identical. Regenerate: `PYTHONPATH=. python -m eval.demo_log`.", ""]
    for n, r in out.items():
        md += [f"## Run: {n}", "",
               f"- Audit entries: {r['audit_entries']}; chain verifies: {r['audit_ok']}; money lost (sandbox CNY): {r['money_lost_cny']}",
               f"- Audit-chain head (SHA-256): `{r['audit_head']}`; identical on replay: {r['replay_head_identical']}",
               f"- Model: {r['llm']}; network used: {r['network_used']}; seed {r['seed']}", ""]
        md += [f"{i}. **{s['title']}** {s['headline']}" for i, s in enumerate(r["steps"], 1)]
        md.append("")
    (REPORTS / "demo.md").write_text("\n".join(md), encoding="utf-8")
    print("wrote", REPORTS / "demo.md")


if __name__ == "__main__":
    main()
