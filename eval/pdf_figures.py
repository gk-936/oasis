"""Inline SVG figures shared by the submission PDFs. Every number is read from a file in execution_evidence/ or eval/reports/."""
from __future__ import annotations
import json
import re
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


def _after_fix() -> tuple[dict[str, tuple[int, int]], int, int]:
    """Per-category pass counts and the total for the 250 set on the current router (eval/reports/outside_outside_codex_round2.md)."""
    txt = (ROOT / "eval" / "reports" / "outside_outside_codex_round2.md").read_text(encoding="utf-8")
    total = re.search(r"Passed (\d+) of (\d+)", txt)
    cats = {m[0]: (int(m[1]), int(m[2])) for m in re.findall(r"^\| (\w+) \| (\d+) \| (\d+) \|$", txt, re.M)}
    return cats, int(total[1]), int(total[2])


def _heldout3() -> tuple[int, int]:
    """Team held-out set H (120 phrases, never tuned on; the 'held-out 3' row of router_robust.md), correct answers on the current router."""
    txt = (ROOT / "eval" / "reports" / "router_robust.md").read_text(encoding="utf-8")
    m = re.search(r"router held-out 3[^|]*\| (\d+) \| \d+ > (\d+) \|", txt)
    return int(m[2]), int(m[1])


def fig_outside_sets(n: int = 1) -> str:
    """The 250-scenario outside set (Codex): first run beside the current router, per category, plus team held-out set H."""
    d = json.loads(FIRST.read_text(encoding="utf-8"))["round2_codex_250"]
    after, a_pass, a_tot = _after_fix()
    h3, h3n = _heldout3()
    cats = sorted(d["by_category"].items(), key=lambda kv: kv[1][0] / kv[1][1])
    w, rowh, left, bw = 640, 24, 110, 400
    top = 92
    svg = [f'<svg viewBox="0 0 {w} {top + len(cats) * rowh + 8}" width="100%" {FONT}>',
           f'<text x="0" y="13" font-size="10.5" font-weight="700" fill="{INK}">Scenarios meeting every expectation. Money moved in any scenario: CNY 0.</text>']
    for j, (lab, p, t, col) in enumerate([("250 set, first run", d["passed"], d["total"], AMBER), ("250 set, current router", a_pass, a_tot, GREEN),
                                           ("Team held-out set H, never tuned on", h3, h3n, GREEN)]):
        y = 22 + j * 15
        svg.append(f'<text x="{left + 40}" y="{y + 9}" text-anchor="end" font-size="9.5" fill="{INK}">{lab}</text>')
        svg.append(f'<rect x="{left + 48}" y="{y}" width="{bw}" height="11" fill="#e4e6ea"/><rect x="{left + 48}" y="{y}" width="{bw * p / t}" height="11" fill="{col}"/>')
        svg.append(f'<text x="{left + 48 + bw + 6}" y="{y + 9}" font-size="9" fill="{INK}">{p} of {t} ({100 * p / t:.0f}%)</text>')
    svg.append(f'<text x="0" y="{top - 6}" font-size="9" fill="{MID}">By category (250 set):</text><text x="{left + 48}" y="{top - 6}" font-size="9" fill="{INK}"><tspan fill="{AMBER}" font-weight="700">&#9632;</tspan> first run   <tspan fill="{GREEN}" font-weight="700">&#9632;</tspan> current router</text>')
    for i, (k, (p, t)) in enumerate(cats):
        y = top + i * rowh
        q, qt = after.get(k, (p, t))
        svg.append(f'<text x="{left - 8}" y="{y + 11}" text-anchor="end" font-size="9.5" fill="{INK}">{k.replace("_", " ")}</text>')
        svg.append(f'<rect x="{left}" y="{y}" width="{bw + 48}" height="9" fill="#e4e6ea"/><rect x="{left}" y="{y}" width="{(bw + 48) * p / t}" height="9" fill="{AMBER}"/>')
        svg.append(f'<rect x="{left}" y="{y + 10}" width="{bw + 48}" height="9" fill="#e4e6ea"/><rect x="{left}" y="{y + 10}" width="{(bw + 48) * q / qt}" height="9" fill="{GREEN}"/>')
        svg.append(f'<text x="{left + bw + 54}" y="{y + 8}" font-size="8.5" fill="{INK}">{p} of {t}</text><text x="{left + bw + 54}" y="{y + 18}" font-size="8.5" fill="{INK}">{q} of {qt}</text>')
    svg.append("</svg>")
    return _fig("".join(svg), f"Figure {n}. Scenarios written by an outside AI (Codex) from the pitch and the API description only; offline deterministic router (concept lexicon, context, scam lane), no live model. "
                "Amber is the first run before any fix; green is the same set on the current router, after fixes written while reading it (a development figure). "
                "Team held-out set H was written by our own team before the final fixes and never used for tuning; it is a different set from the ChatGPT-written set 3 of the outside-set table. Sources: eval/reports/outside_firstrun.json, outside_outside_codex_round2.md, router_robust.md.")


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
