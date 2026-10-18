"""Inline SVG figures shared by the submission PDFs. Every number is read from a file in execution_evidence/ or eval/reports/."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "execution_evidence" / "evidence_results.json"
FIRST = ROOT / "eval" / "reports" / "outside_firstrun.json"
INK, MID, RED, GREEN, AMBER = "#111", "#555", "#9b1c1c", "#1f6f43", "#a86a00"
FONT = 'font-family="Cambria, Times New Roman, serif"'


def _fig(svg: str, caption: str) -> str:
    return f'<figure style="margin:10pt 0;break-inside:avoid">{svg}<figcaption class="small" style="margin-top:3pt">{caption}</figcaption></figure>'


def fig_money_lost(n: int = 1) -> str:
    """Per attack case: CNY that reached an attacker with and without the protections (MOCK money)."""
    d = json.loads(EV.read_text(encoding="utf-8"))
    cases = [c for c in d["cases"] if c["expect"] in ("attacker_blocked",)]
    top = max(1.0, max(c["runs"]["UNPROTECTED"]["money_lost_cny"] for c in cases))
    w, rowh, left = 640, 30, 190
    svg = [f'<svg viewBox="0 0 {w} {len(cases) * rowh + 52}" width="100%" {FONT}>',
           f'<text x="{left}" y="14" font-size="10" fill="{INK}"><tspan fill="{RED}" font-weight="700">&#9632;</tspan> without Oasis protections   <tspan fill="{GREEN}" font-weight="700">&#9632;</tspan> with Oasis</text>']
    for i, c in enumerate(cases):
        y = 28 + i * rowh
        u, p = c["runs"]["UNPROTECTED"]["money_lost_cny"], c["runs"]["PROTECTED"]["money_lost_cny"]
        label = c["id"].split("_", 1)[0] + "  " + c["id"].split("_", 1)[1].replace("_", " ")
        svg.append(f'<text x="{left - 8}" y="{y + 12}" text-anchor="end" font-size="9.5" fill="{INK}">{label[:34]}</text>')
        svg.append(f'<rect x="{left}" y="{y}" width="{max(1, 320 * u / top)}" height="9" fill="{RED}"/><text x="{left + 320 * u / top + 4}" y="{y + 8.5}" font-size="8.5" fill="{INK}">CNY {u:,.0f}</text>')
        svg.append(f'<rect x="{left}" y="{y + 11}" width="{max(1, 320 * p / top)}" height="9" fill="{GREEN}"/><text x="{left + 4 + 320 * p / top}" y="{y + 19.5}" font-size="8.5" fill="{INK}">CNY {p:,.0f}</text>')
    svg.append("</svg>")
    return _fig("".join(svg), f"Figure {n}. Simulated money (MOCK) that reached an attacker account, per attack scenario. Source: execution_evidence/evidence_results.json.")


def fig_outside_sets(n: int = 1) -> str:
    """First-run pass counts per category for the 250-scenario outside set (Codex), with the zero-money-moved result in the title."""
    d = json.loads(FIRST.read_text(encoding="utf-8"))["round2_codex_250"]
    cats = sorted(d["by_category"].items(), key=lambda kv: kv[1][0] / kv[1][1])
    w, rowh, left = 640, 20, 110
    svg = [f'<svg viewBox="0 0 {w} {len(cats) * rowh + 44}" width="100%" {FONT}>',
           f'<text x="0" y="13" font-size="10.5" font-weight="700" fill="{INK}">First run: {d["passed"]} of {d["total"]} scenarios met every expectation. Money moved in any scenario: CNY 0.</text>']
    for i, (k, (p, t)) in enumerate(cats):
        y = 26 + i * rowh
        svg.append(f'<text x="{left - 8}" y="{y + 10}" text-anchor="end" font-size="9.5" fill="{INK}">{k.replace("_", " ")}</text>')
        svg.append(f'<rect x="{left}" y="{y}" width="460" height="12" fill="#e4e6ea"/><rect x="{left}" y="{y}" width="{460 * p / t}" height="12" fill="{AMBER}"/>')
        svg.append(f'<text x="{left + 466}" y="{y + 10}" font-size="9" fill="{INK}">{p} of {t}</text>')
    svg.append("</svg>")
    return _fig("".join(svg), f"Figure {n}. Scenarios written by an outside AI (Codex) from the pitch and the API description only; offline keyword router, no live model. "
                "The score is a first run before any fix; misses are mostly unusual wording the live model is meant to handle. Source: eval/reports/outside_firstrun.json.")


def fig_payment_path(n: int = 1) -> str:
    """Who may do what on the way from a request to money moving."""
    steps = [("Student or\ndocument", "asks"), ("AI model", "proposes and\nexplains only"), ("Policy engine", "rules R01 to R19\nhold or allow"),
             ("Device-key\nsignature", "the human signs the\nexact draft"), ("Executor", "enforces the signed\nintent exactly"), ("Registry\naccount", "the only place\nmoney goes")]
    bw, gap, y = 92, 14, 34
    svg = [f'<svg viewBox="0 0 640 150" width="100%" {FONT}><defs><marker id="pp" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{INK}"/></marker></defs>']
    for i, (title, sub) in enumerate(steps):
        x = 4 + i * (bw + gap)
        trusted = i in (2, 3, 4)
        svg.append(f'<rect x="{x}" y="{y}" width="{bw}" height="62" fill="{"#fff" if trusted else "#f3f4f6"}" stroke="{INK}" stroke-width="{1.4 if trusted else 0.8}"/>')
        for j, ln in enumerate(title.split("\n")):
            svg.append(f'<text x="{x + bw / 2}" y="{y + 16 + 11 * j}" text-anchor="middle" font-size="10" font-weight="700" fill="{INK}">{ln}</text>')
        for j, ln in enumerate(sub.split("\n")):
            svg.append(f'<text x="{x + bw / 2}" y="{y + 42 + 10 * j}" text-anchor="middle" font-size="8.3" fill="{MID}">{ln}</text>')
        if i < len(steps) - 1:
            svg.append(f'<line x1="{x + bw}" y1="{y + 31}" x2="{x + bw + gap}" y2="{y + 31}" stroke="{INK}" marker-end="url(#pp)"/>')
    svg.append(f'<text x="4" y="22" font-size="9" fill="{MID}">grey = untrusted input or proposal</text><text x="{4 + 2 * (bw + gap)}" y="22" font-size="9" fill="{INK}" font-weight="700">bold = deterministic trusted code</text>')
    svg.append(f'<text x="320" y="126" text-anchor="middle" font-size="10" font-weight="700" fill="{INK}">The AI never approves, signs, holds a credential or writes the audit log.</text>')
    svg.append("</svg>")
    return _fig("".join(svg), f"Figure {n}. The payment path and who may act at each step.")
