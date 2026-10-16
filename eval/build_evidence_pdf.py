"""Build the Execution Evidence report (PDF) from the generated evidence data.

Bordered, paginated report: cover with the Oasis logo, contents with page numbers, sections with real log output.
Static HTML with inline SVG charts, printed to PDF by headless Edge/Chrome; the contents page numbers are found with a first
pass over the printed PDF and filled in on the second pass (needs `pypdf`). No model call, no network.

    OASIS_LLM=offline PYTHONPATH=. python -m eval.execution_evidence      # refresh the evidence data
    PYTHONPATH=. python -m eval.build_evidence_pdf                        # print the report
"""
from __future__ import annotations
import base64
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "execution_evidence"
LOGO = Path(__file__).resolve().parents[1] / "docs" / "assets" / "oasis-logo-dark.svg"
BROWSERS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe")
INK, MID, LIGHT = "#111", "#555", "#e4e6e8"
RED, GREEN, AMBER, TEAL, NAVY = "#b42318", "#117a3d", "#b7791f", "#00A88F", "#0B1F2A"
e = html.escape
SHORT = {"P1": "P1  Fake landlord, new account", "P2": "P2  Altered tuition invoice", "P3": "P3  Lookalike payee",
         "P4": "P4  Hidden instruction in a document", "P5": "P5  Tool rewrites payment details"}
SECTIONS = ["Executive Summary", "Scope and Method", "Problem Statement", "Scenario Results", "Detailed Case Records",
            "Executor Enforcement Tests", "Cost, Runway and Verified Record", "Wider Benchmark", "Integrity and Reproducibility",
            "Limitations"]
APPENDICES = ["Verification Folder", "Complete Operation Log", "Audit-Chain Entries", "Glossary"]
SOURCES = {
    "P1": "Shanghai municipal government, anti-fraud guidance for international students (2024): fake landlord, new account.",
    "P2": "KU Leuven and UK university notices: fraudsters alter the account number on a genuine tuition invoice.",
    "P3": "Impersonation of a payee with a near-identical name, as described in the public warnings cited in Section 3.",
    "P4": "Published reports on prompt injection: hidden text tells an AI agent to send money elsewhere.",
    "P5": "Published reports on tool poisoning: a compromised tool rewrites the payment details after approval.",
    "P6": "Recognised structuring pattern: one large transfer is split into smaller ones to avoid a review threshold.",
    "P7": "Control. A genuine landlord changes bank account, confirmed through the registry. It must not be blocked.",
    "P8": "Control. Genuine tuition to the verified university must be paid normally."}


def money(x: float) -> str:
    return f"CNY {x:,.2f}"


def cid(c: dict) -> str:
    return c["id"].split("_", 1)[0]


# ---------------------------------------------------------------------------------------------- charts
SVG_DEFS = (f'<defs><pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="5" height="5" fill="#fff"/><line x1="0" y1="0" x2="0" y2="5" stroke="{TEAL}" stroke-width="1.6"/></pattern></defs>')
FONT = "font-family=\"Cambria, 'Times New Roman', serif\""


def fig_losses(cases: list[dict]) -> str:
    """Per scam case: money that reached the attacker, without Oasis (red bar) and with Oasis (green marker, CNY 0)."""
    w, left, rowh, top = 700, 235, 42, 34
    mx = max(max(c["runs"]["UNPROTECTED"]["money_lost_cny"], 1) for c in cases)
    h = top + rowh * len(cases) + 34
    plot = w - left - 120
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" {FONT}>',
         f'<rect x="{left}" y="8" width="13" height="13" fill="{RED}"/><text x="{left+19}" y="19" font-size="11.5">Without Oasis protections</text>'
         f'<rect x="{left+205}" y="8" width="13" height="13" fill="{GREEN}"/><text x="{left+224}" y="19" font-size="11.5">With Oasis</text>']
    for g in range(0, int(mx) + 1, 10000):
        x = left + plot * g / mx
        s.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top-6}" y2="{h-30}" stroke="{LIGHT}"/>'
                 f'<text x="{x:.1f}" y="{h-16}" font-size="10" text-anchor="middle" fill="{MID}">{g:,}</text>')
    for i, c in enumerate(cases):
        y = top + i * rowh
        u, p = c["runs"]["UNPROTECTED"]["money_lost_cny"], c["runs"]["PROTECTED"]["money_lost_cny"]
        uw = plot * u / mx
        s.append(f'<text x="{left-10}" y="{y+25}" font-size="11.5" text-anchor="end">{e(SHORT[cid(c)])}</text>'
                 f'<rect x="{left}" y="{y+4}" width="{max(uw,2):.1f}" height="17" fill="{RED}"/>'
                 f'<text x="{left+uw+7:.1f}" y="{y+17}" font-size="11.5" font-weight="700" fill="{RED}">{u:,.0f}</text>')
        if p == 0:
            s.append(f'<rect x="{left}" y="{y+25}" width="5" height="17" fill="{GREEN}"/>'
                     f'<text x="{left+12}" y="{y+38}" font-size="11.5" font-weight="700" fill="{GREEN}">0  (blocked)</text>')
        else:
            pw = plot * p / mx
            s.append(f'<rect x="{left}" y="{y+25}" width="{pw:.1f}" height="17" fill="{GREEN}"/><text x="{left+pw+7:.1f}" y="{y+38}" font-size="11.5">{p:,.0f}</text>')
    s.append(f'<line x1="{left}" x2="{left}" y1="{top-6}" y2="{h-30}" stroke="{INK}"/>'
             f'<text x="{left+plot/2:.0f}" y="{h-2}" font-size="10.5" text-anchor="middle" fill="{MID}">CNY paid to attacker accounts (simulated)</text></svg>')
    return "".join(s)


def fig_cost(cost: dict) -> str:
    rows = cost["routes"]
    lo, hi = min(r["delivered_cny"] for r in rows) - 40, max(r["delivered_cny"] for r in rows) + 10
    w, left, rowh = 700, 235, 30
    h = 14 + rowh * len(rows) + 30
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" {FONT}>{SVG_DEFS}']
    for i, r in enumerate(rows):
        y = 8 + i * rowh
        bw = (w - left - 100) * (r["delivered_cny"] - lo) / (hi - lo)
        fill = RED if r["typical_bank"] else TEAL
        s.append(f'<text x="{left-10}" y="{y+22}" font-size="11.5" text-anchor="end">{e(r["route"].replace("→", " to "))}</text>'
                 f'<rect x="{left}" y="{y+5}" width="{bw:.1f}" height="24" fill="{fill}"/>'
                 f'<text x="{left+bw+7:.1f}" y="{y+22}" font-size="11.5" font-weight="700">{r["delivered_cny"]:,.2f}</text>')
    s.append(f'<text x="{left}" y="{h-6}" font-size="10.5" fill="{MID}">CNY delivered. Axis begins at CNY {lo:,.0f}, not zero. Red: typical bank route.</text></svg>')
    return "".join(s)


def fig_suite(summary: dict) -> str:
    order = ["baseline", "+verification", "+intents+policy", "full"]
    fills = [RED, AMBER, TEAL, GREEN]
    w, h, base, ch = 700, 250, 200, 150
    s = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" {FONT}>']
    for g in (0, 25, 50, 75, 100):
        y = base - ch * g / 100
        s.append(f'<line x1="70" x2="{w-20}" y1="{y}" y2="{y}" stroke="{LIGHT}"/><text x="62" y="{y+4}" font-size="10.5" text-anchor="end" fill="{MID}">{g}%</text>')
    for i, k in enumerate(order):
        v, x = summary[k], 100 + i * 150
        bh = ch * v["attack_block_rate"]
        s.append(f'<rect x="{x}" y="{base-bh:.1f}" width="90" height="{max(bh,2):.1f}" fill="{fills[i]}"/>'
                 f'<text x="{x+45}" y="{base-bh-7:.1f}" font-size="13" text-anchor="middle" font-weight="700">{v["attack_block_rate"]*100:.1f}%</text>'
                 f'<text x="{x+45}" y="{base+17}" font-size="11.5" text-anchor="middle">{e(k)}</text>'
                 f'<text x="{x+45}" y="{base+32}" font-size="10.5" text-anchor="middle" fill="{MID}">lost CNY {v["money_lost_cny"]:,.0f}</text>')
    s.append("</svg>")
    return "".join(s)


def fig_chain(i: dict) -> str:
    bad, total = i["tamper_test"]["first_broken"], i["tamper_test"]["entries"]
    first = max(0, bad - 2)
    last = min(total - 1, first + 5)
    s = [f'<svg viewBox="0 0 700 112" width="100%" role="img" {FONT}>']
    for k in range(last - first + 1):
        x, idx = 20 + k * 112, first + k
        broken = idx >= bad
        col = RED if broken else GREEN
        dash = ' stroke-dasharray="5 3"' if broken else ""
        s.append(f'<rect x="{x}" y="22" width="92" height="58" fill="{"#fdecea" if broken else "#e8f5ec"}" stroke="{col}" stroke-width="1.6"{dash}/>'
                 f'<text x="{x+46}" y="46" font-size="12" text-anchor="middle" font-weight="700">Entry {idx}</text>'
                 f'<text x="{x+46}" y="66" font-size="11" text-anchor="middle" fill="{col}">{"hash mismatch" if broken else "verified"}</text>')
        if k < last - first:
            s.append(f'<line x1="{x+92}" x2="{x+112}" y1="51" y2="51" stroke="{MID}"/>')
    s.append(f'<text x="20" y="102" font-size="10.5" fill="{MID}">Entry {bad} was altered after the fact. The verifier reports the first broken link.</text></svg>')
    return "".join(s)


# ---------------------------------------------------------------------------------------------- log output
def req_line(text: str) -> str:
    g = {}
    for ln in text.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            g.setdefault(k.strip().lower(), v.strip())
    bits = [f"{lab}={g[k]}" for k, lab in (("payee", "payee"), ("account", "account"), ("amount", "amount"), ("purpose", "purpose")) if k in g]
    extra = []
    if "<!--" in text or "<span" in text:
        extra.append("hidden text")
    if re.search(r"bank details|new account|new card", text, re.I):
        extra.append("new bank details claimed")
    return "  ".join(bits) + (f"   [{'; '.join(extra)}]" if extra else "")


def log_block(r: dict, title: str) -> str:
    L = [f"<b>{e(title)}</b>"]
    for n, st in enumerate(r["steps"], 1):
        o = st["outcome"]
        L.append(f"REQUEST {n}   {e(req_line(st['request']))}")
        if st["tool_poison"]:
            L.append(f"TOOL OUTPUT   rewritten at execution: {e(json.dumps(st['tool_poison']))}")
        good = o["status"] in ("rejected", "frozen", "held", "needs_verification")
        L.append(f"OUTCOME   status=<b style='color:{GREEN if good else RED}'>{e(o['status'])}</b>   rule={e(str(o['rule'] or '-'))}   risk={o['risk_score']}")
        for rs in dict.fromkeys(o["reasons"]):
            L.append(f"REASON    {e(rs)}")
        moved = [t for t in st["ledger_transfers"] if t["memo"] != "verification_test"]
        for a in st["audit_entries"]:
            if a["kind"] == "conversion":
                sm = a["summary"]
                L.append(f"CONVERT   INR {sm.get('sent_inr', 0):,.2f} -> CNY {sm.get('delivered_cny', 0):,.2f} into the student's own account (not a payment)")
        for t in moved:
            tag = f" <b style='color:{RED}'>[ATTACKER ACCOUNT]</b>" if t["to_is_attacker"] else ""
            L.append(f"LEDGER    {t['id']}  {e(t['from'])} -> {e(t['to'])}  {t['amount']:,.2f} {t['currency']}{tag}")
        if not moved:
            L.append(f"LEDGER    <b style='color:{GREEN}'>no payment made</b>")
        for a in st["audit_entries"]:
            L.append(f"AUDIT     #{a['i']:<2} {a['kind']:<18} {a['hash'][:24]}...")
    ch = "verified" if r["audit_ok"] else "BROKEN"
    L.append(f"CHAIN     {r['audit_entries']} entries, {ch}, head {r['audit_head'][:24]}...")
    for c in r["ledger_changes"]:
        who = f"<b style='color:{RED}'>attacker account</b>" if c["attacker"] else ("student's own account" if c["owner"] == "student" else e(c["owner"]))
        L.append(f"BALANCE   {e(c['account'])} ({who})  {c['before']:,.2f} -> {c['after']:,.2f}  ({c['change']:+,.2f})")
    if not r["ledger_changes"]:
        L.append("BALANCE   no account changed")
    return "<pre class='log'>" + "\n".join(L) + "</pre>"


def case_record(c: dict) -> str:
    u, p = c["runs"]["UNPROTECTED"], c["runs"]["PROTECTED"]
    vu, vp = c["verdict"]["UNPROTECTED"], c["verdict"]["PROTECTED"]
    col = lambda v: AMBER if v["result"].startswith("PARTLY") else (GREEN if v["good"] else RED)
    return (f'<div class="record"><div class="rhead"><h3>{e(cid(c))}. {e(c["pain"])}</h3>'
            f'<p class="small" style="margin:0 0 3pt"><i>{e(SOURCES[cid(c)])}</i></p>'
            f'<table class="kv"><tr><th></th><th>Without Oasis protections</th><th>With Oasis</th></tr>'
            f'<tr><th>Result</th><td><span class="res" style="color:{col(vu)}">{e(vu["result"])}</span><br>{e(vu["detail"])}</td>'
            f'<td><span class="res" style="color:{col(vp)}">{e(vp["result"])}</span><br>{e(vp["detail"])}</td></tr></table></div>'
            f'{log_block(u, "Log output: without Oasis protections")}{log_block(p, "Log output: with Oasis")}</div>')


def exec_logs(attacks: list[dict]) -> str:
    L = ["<b>Log output: executor tests (each on a fresh account; audit-chain head after the test)</b>"]
    for r in attacks:
        ok = r["blocked"] or r["attack"] == "control"
        verdict = "EXECUTED (control)" if r["attack"] == "control" else ("REFUSED" if r["blocked"] else "NOT REFUSED")
        L.append(f"TEST      {r['attack']:<16} status=<b style='color:{GREEN if ok else RED}'>{r['status']}</b>  result={verdict}  extra_money_moved={r['extra_money_moved']:.2f}")
        L.append(f"REASON    {e('; '.join(r['reasons']))}")
        L.append(f"CHAIN     {'verified' if r['audit_ok'] else 'BROKEN'}, head {r['audit_head'][:24]}...")
    return "<pre class='log'>" + "\n".join(L) + "</pre>"


# ---------------------------------------------------------------------------------------------- page
FRAME = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 210 297' preserveAspectRatio='none'>"
         "<rect x='10' y='10' width='190' height='277' fill='none' stroke='black' stroke-width='0.5'/></svg>")
CSS = f"""
@page {{ size: A4; margin: 36mm 22mm 26mm 22mm; background: url("data:image/svg+xml;utf8,{FRAME}") no-repeat; background-size: 210mm 297mm; background-position: -22mm -36mm;
  @top-left {{ content: "Oasis  |  Execution Evidence"; font: 8.5pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 15mm; }}
  @top-right {{ content: "Avertix"; font: 8.5pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 15mm; }}
  @bottom-center {{ content: counter(page); font: 9pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 5mm; }} }}
@page :first {{ margin: 0; background-position: 0 0; @top-left {{ content: none; }} @top-right {{ content: none; }} @bottom-center {{ content: none; }} }}
* {{ box-sizing: border-box; }}
body {{ font: 11.5pt/1.7 Cambria, 'Times New Roman', serif; font-variant-numeric: lining-nums tabular-nums; color:{INK}; margin: 0; }}
h2 {{ font-size: 17pt; margin: 0 0 14pt; padding-bottom: 6pt; border-bottom: 1.2pt solid {NAVY}; break-after: avoid; color:{NAVY}; }}
h3 {{ font-size: 12.5pt; margin: 22pt 0 6pt; break-after: avoid; break-inside: avoid; color:{NAVY}; }}
section.s {{ break-before: page; }}
p {{ margin: 9pt 0; text-align: justify; }} .small {{ font-size: 8.8pt; color:{MID}; }}
table {{ border-collapse: collapse; width: 100%; font-size: 10pt; margin: 10pt 0; break-inside: avoid; }} tr {{ break-inside: avoid; }} thead {{ display: table-header-group; }}
table.long {{ break-inside: auto; font-size: 9pt; }} table.long th, table.long td {{ padding: 3.5pt 7pt; }}
th, td {{ border: 0.7pt solid #8a8f98; padding: 6pt 8pt; text-align: left; vertical-align: top; }} th {{ background: {LIGHT}; }}
td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums lining-nums; }} td.c, th.c {{ text-align: center; }}
table.kv {{ table-layout: fixed; }} table.kv th:first-child {{ width: 16%; }}
code {{ font: 7.8pt Consolas, 'Courier New', monospace; word-break: break-all; }}
pre.log {{ font: 7.3pt/1.32 Consolas, 'Courier New', monospace; background: #f4f5f6; border: 0.7pt solid #8a8f98; padding: 3pt 7pt; margin: 3pt 0; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }}
.res {{ font-weight: 700; letter-spacing: .4pt; }}
.notice {{ border: 1pt solid {NAVY}; border-left: 4pt solid {TEAL}; padding: 10pt 14pt; margin: 18pt 0; break-inside: avoid; }}
.record {{ margin: 0 0 10pt; }} section.s .record h3 {{ margin: 4pt 0 2pt; font-size: 12pt; }} .rhead {{ break-inside: avoid; break-after: avoid; }} .rhead table {{ margin: 4pt 0 0; }} .rhead th, .rhead td {{ padding: 3.5pt 8pt; }}
figure {{ margin: 16pt 0; break-inside: avoid; }} figcaption {{ font-size: 8.8pt; margin-top: 3pt; }}
section.compact {{ font-size: 10.8pt; line-height: 1.55; }} section.compact p {{ margin: 5pt 0; }} section.compact h3 {{ margin: 11pt 0 3pt; }} section.compact li {{ margin: 3pt 0; }} section.compact figure {{ margin: 10pt 0; }} section.compact table {{ margin: 6pt 0; }} section.compact th, section.compact td {{ padding: 4.5pt 8pt; }}
ul {{ margin: 8pt 0 8pt 18pt; padding: 0; }} li {{ margin: 8pt 0; }}
.cover {{ height: 297mm; position: relative; text-align: center; break-after: page; }}
.cover .top {{ position:absolute; top: 62mm; left: 0; right: 0; }} .cover h1 {{ font-size: 30pt; letter-spacing: 2pt; margin: 0; font-weight: 400; color:{NAVY}; }}
.cover .sub {{ font-size: 13pt; margin: 6mm 0 0; text-align: center; color:{MID}; }}
.cover .mid {{ position:absolute; top: 128mm; left: 0; right: 0; }} .cover .mid img {{ width: 118mm; }}
.cover .by {{ font-size: 14pt; margin-top: 5mm; font-style: italic; text-align: center; color:{NAVY}; }}
.toc td {{ border: none; padding: 7pt 0; font-size: 12pt; }} .toc td.n {{ text-align: right; width: 14mm; }}
.toc td.dots {{ border-bottom: 0.7pt dotted {MID}; }} .toc tr.app td {{ font-size: 11.5pt; }}
"""


def toc_block(pages: dict[str, int]) -> str:
    def row(label: str, key: str, cls: str = "") -> str:
        return f'<tr class="{cls}"><td style="white-space:nowrap">{e(label)}</td><td class="dots"></td><td class="n">{pages.get(key, "")}</td></tr>'
    rows = [row(f"{i}.  {t}", f"S{i}") for i, t in enumerate(SECTIONS, 1)]
    rows += [row(f"Appendix {chr(64 + i)}.  {t}", f"A{i}", "app") for i, t in enumerate(APPENDICES, 1)]
    return '<h2>Contents</h2><table class="toc">' + "".join(rows) + "</table>"


def build(o: dict, bench: dict, bmeta: dict, pages: dict[str, int]) -> str:
    s, m = o["summary"], o["meta"]
    cases = o["cases"]
    scam = [c for c in cases if c["expect"] == "attacker_blocked"]
    c0, run, tr, i = o["cost"], o["runway"], o["trust"], o["integrity"]
    logo = "data:image/svg+xml;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Oasis Execution Evidence</title><style>{CSS}</style></head><body>"]
    h.append(f"""<div class="cover"><div class="top"><h1>EXECUTION EVIDENCE</h1><p class="sub">Simulated-Account and Sandbox Operation Logs</p></div>
<div class="mid"><img src="{logo}" alt="OASIS"><p class="by">by Avertix</p></div></div>""")
    h.append(f'<section class="s" style="break-before:auto">{toc_block(pages)}</section>')

    def sec(n: int, body: str) -> str:
        cls = "s compact" if n in (1, 2, 4, 7, 9) else "s"
        return f'<section class="{cls}"><h2 id="S{n}">{n}.&nbsp; {SECTIONS[n-1]}</h2>{body}</section>'

    ok = lambda t: f'<b style="color:{GREEN}">{t}</b>'
    bad = lambda t: f'<b style="color:{RED}">{t}</b>'
    kp = [("Scam and attack scenarios mitigated", bad(f"{s['attacks_stopped']['UNPROTECTED']} of {s['attack_cases']}"), ok(f"{s['attacks_stopped']['PROTECTED']} of {s['attack_cases']}")),
          ("Simulated money paid to attacker accounts", bad(money(s['money_lost_cny']['UNPROTECTED'])), ok(money(s['money_lost_cny']['PROTECTED']))),
          ("Genuine payments completed", ok(f"{s['legit_paid']['UNPROTECTED']} of {s['legit_cases']}"), ok(f"{s['legit_paid']['PROTECTED']} of {s['legit_cases']}")),
          ("Tampered signed payments refused", "not applicable", ok(f"{s['executor_blocked']} of {s['executor_attacks']}"))]
    kp_rows = "".join(f"<tr><td>{a}</td><td class='c'>{b}</td><td class='c'>{c}</td></tr>" for a, b, c in kp)
    h.append(sec(1, f"""<p>Students who pay tuition and rent abroad are exposed to a small set of costly failures: invoices with altered bank details, impostor
landlords, instructions hidden in documents, and high transfer costs. Oasis is a payment assistant built to prevent these failures. This report
presents the operation logs from a simulated account that test whether it does.</p>
<p>Each situation was run twice on an identical simulated account: once with Oasis's protections switched off, and once with the complete system.
Every request, decision, ledger movement and audit-log entry was recorded, and the log output is reproduced in this report.</p>
<p><b>Verification.</b> Every number in this report can be verified from the files in the folder named <b>execution_evidence</b>, which is submitted with this report. It holds the raw operation log, the results data, the benchmark and demonstration data, and a small program that recomputes the headline figures from the log (see Appendix A).</p>
<table><tr><th>Measure</th><th class="c">Without Oasis protections</th><th class="c">With Oasis</th></tr>{kp_rows}</table>
<p class="small">Mitigated means no payment reached an attacker and no transfer beyond the approval limit went through. In five scenarios no payment was executed at all. In the split-transfer scenario (P6) the first of three CNY 3,300 transfers, which is below the approval limit, was executed and the next two were held for the parent's approval.</p>
<p><b>Conclusion.</b> In the simulated environment, the account without Oasis's protections paid {money(s['money_lost_cny']['UNPROTECTED'])} to attacker accounts across five scam cases.
With Oasis, no attacker account received any payment, the split transfer was stopped after its first part and the rest held for the parent's approval, and both genuine payments completed without
being blocked. Every attempt to alter a signed payment at the final execution step was refused. The audit log is tamper-evident and replays to an identical result.</p>
<div class="notice"><b>Important notice.</b> All results come from a simulation: accounts, rates, fees and the payee registry are MOCK. The report shows the protections working in the sandbox; it makes no claim about real-world fraud rates, real savings or credit scores.</div>"""))

    h.append(sec(2, f"""<h3>2.1  Objective</h3><p>To provide verifiable operation logs from a simulated account showing how Oasis behaves in the situations that cause students to lose money,
and to compare that behaviour against the same account with Oasis's protections removed.</p>
<h3>2.2  Test configurations</h3>
<table><tr><th style="width:24%">Configuration</th><th>Description</th></tr>
<tr><td>Without Oasis protections</td><td>Payee verification, signed intents with a policy engine, and canary tripwires are all disabled. The agent holds a long-lived payment credential. This represents a conventional automated assistant.</td></tr>
<tr><td>With Oasis</td><td>All protections enabled: payee verification against a registry, deterministic policy, device-key approval over the exact payment, an executor that enforces the signed intent, canary tripwires and a hash-chained audit log. The AI model may propose and explain; it cannot approve a payment.</td></tr></table>
<h3>2.3  Conditions</h3><ul><li>Fresh simulated world for every run; fixed seed ({m['seed']}); seeded signing keys and nonces; simulated clock.</li>
<li>Offline deterministic model. No network access and no call to any external model, so the runs consume no model tokens.</li>
<li>Simulated humans approve or decline according to the student's record. They are not an oracle.</li></ul>
<h3>2.4  What was recorded</h3><p>For every operation: the request received; the outcome, rule and reasons; each ledger transfer; the change in every account balance; and each audit-log entry with its hash and the hash of the entry before it.
The log output for every case is shown in Sections 5 and 6, and the complete list of {o.get('log_lines', 30)} operation records is in Appendix B. The raw files are in the verification folder described in Appendix A.</p>
<h3>2.5  Verification of the logs</h3><ul><li>Every case was replayed and produced an identical audit-chain head: <b>{"yes" if m['problem_cases_replay_identical'] else "no"}</b>.</li>
<li>A scan of all evidence for payment tokens and API tokens found: <b>{', '.join(o['redaction']['secrets_found']) or 'none'}</b>.</li>
<li>The audit chain was altered deliberately to confirm that tampering is detected (Section 9).</li></ul>"""))

    h.append(sec(3, """<p>The failures below are described by public sources. The project team has not interviewed students; the evidence is public warnings and surveys, and each has a stated confidence level in the problem-evidence note that accompanies the project.</p>
<table><tr><th>Problem</th><th>Public evidence</th><th>Tested in</th></tr>
<tr><td>An impostor landlord asks for rent to be sent to a new account</td><td>Shanghai municipal government, anti-fraud guidance for international students (2024)</td><td>Case P1</td></tr>
<tr><td>A tuition invoice is altered to show a different bank account</td><td>KU Leuven invoice-fraud warning; UK university notices</td><td>Cases P2, P3</td></tr>
<tr><td>An AI agent is steered by hidden text, or a tool rewrites payment details</td><td>Published reports on prompt injection and tool poisoning</td><td>Cases P4, P5; Section 6</td></tr>
<tr><td>A large transfer is split to avoid the parent's approval</td><td>Recognised structuring pattern</td><td>Case P6</td></tr>
<tr><td>Sending money through a bank is expensive</td><td>World Bank, Remittance Prices Worldwide: bank routes are the costliest provider type</td><td>Section 7</td></tr>
<tr><td>Cost-of-living worry; newcomers invisible to lenders</td><td>QS International Student Survey 2023; Statistics Canada 2023</td><td>Section 7</td></tr></table>
<p class="small">These sources describe the problems. They do not show how often they affect students in China or any other destination.</p>"""))

    rows = "".join(f"<tr><td>{e(cid(c))}</td><td>{e(c['pain'])}</td>"
                   f"<td class='res' style='color:{GREEN if c['verdict']['UNPROTECTED']['good'] else RED}'>{e(c['verdict']['UNPROTECTED']['result'])}</td>"
                   f"<td class='res' style='color:{AMBER if c['verdict']['PROTECTED']['result'].startswith('PARTLY') else (GREEN if c['verdict']['PROTECTED']['good'] else RED)}'>{e(c['verdict']['PROTECTED']['result'])}</td></tr>" for c in cases)
    h.append(sec(4, f"""<p>Figure 1 shows the simulated money that reached attacker accounts in each scam case. The table lists the outcome of all eight cases. Cases P7 and P8 are controls:
genuine payments must still succeed, because a system that blocks everything would also stop every scam.</p>
<figure>{fig_losses(scam)}<figcaption><b>Figure 1.</b> Money paid to attacker accounts, without and with Oasis. Case P6 is not a loss-to-attacker case and appears in the table.</figcaption></figure>
<table><tr><th>Case</th><th>Situation</th><th>Without Oasis protections</th><th>With Oasis</th></tr>{rows}</table>
<p class="small">P6: three CNY 3,300 top-ups were submitted. Without protections all three passed (CNY 9,900.00). With Oasis the first passed (below the approval limit) and two were held, so it is shown as partly held.</p>"""))

    h.append(sec(5, "<p>Each record shows the result and the log output of the run without and with Oasis: request, decision and rule, ledger transfers, audit entries, chain head and balance changes. Hashes are SHA-256, shortened here; full values are in Appendix C.</p><p class='small'>A CONVERT line means the agent converted the student's own INR into CNY on the cheapest route to fund a payment. It moves money only into the student's own account, so that balance rises even when no payment follows. When the executor then refuses a payment, the converted CNY stays in the student's own account. The CNY 0.01 left after a paid case is the rounding margin of that conversion.</p>"
                 + "".join(case_record(c) for c in cases)))

    ex = "".join(f"<tr><td>{e(r['attack'].replace('_', ' '))}</td><td>{e(r['label'].split(' (control')[0])}</td>"
                 f"<td class='res' style='color:{GREEN if (r['blocked'] or r['attack']=='control') else RED}'>{'PAID (control)' if r['attack']=='control' else ('REFUSED' if r['blocked'] else 'NOT REFUSED')}</td><td class='n'>{r['extra_money_moved']:.2f}</td></tr>"
                 for r in o["executor_attacks"])
    h.append(sec(6, f"""<p>A human signs the exact payment with a device key. The executor then enforces that signed intent: signature, exact match of amount and payee, one-time nonce,
expiry and a policy re-check. Each test presents the executor with a different kind of tampering. One honest payment is included as a control to show the executor is not simply refusing everything.</p>
<table><tr><th>Test</th><th>What was attempted</th><th>Result</th><th class="n">Extra CNY moved</th></tr>{ex}</table>
<p><b>Result.</b> {s['executor_blocked']} of {s['executor_attacks']} tampered payments were refused and the honest control payment executed. No additional money moved.</p>{exec_logs(o['executor_attacks'])}"""))

    ct = "".join(f"<tr><td>{e(r['route'].replace('→', ' to '))}</td><td class='c'>{'Yes' if r['typical_bank'] else 'No'}</td><td class='n'>{r['delivered_cny']:,.2f}</td><td class='n'>{r['days']}</td></tr>" for r in c0["routes"])
    cl = tr["claims"]
    trig = "".join(f"<li>{e(t['message'].replace('→', ' to '))}</li>" for t in run["triggers"])
    h.append(sec(7, f"""<h3>7.1  Transfer cost</h3><p>The same INR {c0['send_inr']:,} was quoted through four simulated routes. The cheapest route delivers {money(c0['best_delivered_cny'])} against {money(c0['bank_delivered_cny'])}
by a typical bank route, a difference of {money(c0['saved_cny'])} ({c0['saved_pct']}%).</p>
<figure>{fig_cost(c0)}<figcaption><b>Figure 2.</b> Delivered amount by route for INR {c0['send_inr']:,}. Simulated rates and fees.</figcaption></figure>
<table><tr><th>Route</th><th class="c">Typical bank</th><th class="n">Delivered (CNY)</th><th class="n">Days</th></tr>{ct}</table>
<p class="small">Route fees and rates are simulated. This shows what the tool does in the sandbox, not what a real student would save.</p>
<h3>7.2  Runway and shortfall warning</h3><p>The student starts with INR {run['balances']['INR']:,.0f} against {money(sum(x['amount_cny'] for x in run['pending_obligations']))} of pending tuition, rent and deposit. The simulated runway is {run['runway_months']:.1f} months. The agent raises these warnings before a payment is missed:</p><ul>{trig}</ul>
<h3>7.3  Verified payment record</h3><p>Three payments (tuition, rent and deposit) completed through Oasis produce a record that the student can choose to share: payments on time {cl['on_time_all']['on_time']} of {cl['on_time_all']['of']};
payees verified {cl['verified_payees']['verified']} of {cl['verified_payees']['of']}; current on-time streak {cl['on_time_streak']['count']}. This is a record of verified payments inside Oasis. It is not a credit score, and no lender has accepted it.</p>"""))

    bt = "".join(f"<tr><td>{k}</td><td class='n'>{v['attack_block_rate']*100:.1f}%</td><td class='n'>{money(v['money_lost_cny'])}</td><td class='n'>{v['legit_completion_rate']*100:.0f}%</td><td class='n'>{v['false_block_rate']*100:.0f}%</td></tr>"
                 for k, v in bench.items())
    h.append(sec(8, f"""<p>The wider benchmark applies {bmeta['attacks']} attack scenarios and {bmeta['legit']} genuine account changes to four configurations, adding one protection at a time. The run used the offline deterministic model.</p>
<figure>{fig_suite(bench)}<figcaption><b>Figure 3.</b> Attack block rate as protections are added.</figcaption></figure>
<table><tr><th>Configuration</th><th class="n">Attack block rate</th><th class="n">Money lost (simulated)</th><th class="n">Genuine completed</th><th class="n">False blocks</th></tr>{bt}</table>
<p class="small">These 32 attack scenarios were written by the project team. Independent test sets from ChatGPT and Gemini are described in Section 10. Results show the layering of protections, not performance against unknown attackers.</p>"""))

    heads = "".join(f"<tr><td>{n.title()}</td><td class='n'>{d['entries']}</td><td class='c'>{'Yes' if d['audit_ok'] else 'No'}</td><td class='n'>{d['money_lost_cny']}</td><td><code>{d['audit_head'][:32]}<br>{d['audit_head'][32:]}</code></td><td class='c'>{'Yes' if d['replay_head_identical'] else 'No'}</td></tr>"
                    for n, d in i["demo"].items())
    tt = i["tamper_test"]
    h.append(sec(9, f"""<h3>9.1  Tamper evidence</h3><p>Every audit entry contains the hash of the entry before it. A completed payment was recorded, then one entry was edited (an amount changed). The verifier detected the change and identified the first broken link.</p>
<figure>{fig_chain(i)}<figcaption><b>Figure 4.</b> Audit-chain tamper test. The chain of {tt['entries']} entries verified before the edit and failed at entry {tt['first_broken']} after it.</figcaption></figure>
<pre class="log"><b>Log output: tamper test</b>
VERIFY    before edit   entries={tt['entries']}  intact={tt['intact_verifies']}
EDIT      entry {tt['edited_entry']}  amount changed to 1.0
VERIFY    after edit    intact={tt['after_edit_verifies']}  first_broken={tt['first_broken']}  reason={e(tt['reason'])}</pre>
<h3>9.2  Reproducibility</h3><p>The scripted demonstration was played twice for each run. Identical audit-chain heads confirm that the same inputs always produce the same record.</p>
<table><tr><th>Demonstration run</th><th class="n">Audit entries</th><th class="c">Chain intact</th><th class="n">Money lost</th><th>Audit-chain head (SHA-256)</th><th class="c">Identical on replay</th></tr>{heads}</table>
<h3>9.3  Confidentiality of the logs</h3><p>Payment tokens are single-use, short-lived and never written to the audit log. A scan of all evidence for token and credential patterns found none.</p>"""))

    h.append(sec(10, """<ul><li><b>Simulation only.</b> The ledger, exchange rates, fees and payee registry are simulated. No real bank, account or blockchain was involved.</li>
<li><b>Who wrote the tests.</b> The cases and executor tests in this report were written by the project team. The system was also tested with independent sets written by two outside AI systems, OpenAI's ChatGPT and Google's Gemini, from the public documentation only, without seeing the code. Those sets were used to find and fix failures, so their final scores are not out-of-sample.</li>
<li><b>Cost figures are simulated.</b> The saving depends on mock route fees and is not a measured saving for real students.</li>
<li><b>Deterministic model.</b> These runs use the offline deterministic model. Results with a live language model are reported separately, with their own limits.</li>
<li><b>No user research.</b> No student, parent or university finance office has been interviewed. Public sources describe the problems; the frequency of each is not measured here.</li>
<li><b>No credit claim.</b> The verified-payment record is not a credit score, and no lender or regulator has accepted it.</li>
</ul>"""))

    vf = [("operation_log.jsonl", "The raw operation log: one record per operation with the request, outcome, ledger transfers and audit entries. Sections 5 and 6 and Appendix B are drawn from it."),
          ("evidence_results.json", "All results in structured form: every case, the executor tests, the cost, runway and verified-record data, and the integrity checks."),
          ("evidence_summary.md", "A plain-text summary of the same results."),
          ("benchmark_results.json", "The wider benchmark (Section 8): 32 attacks and 12 genuine changes across four configurations."),
          ("demo_run_log.json", "The two scripted demonstration runs and their audit-chain heads (Section 9)."),
          ("verify_evidence.py", "A short standard-library program. It checks that every audit chain is linked, recomputes the money paid to attacker accounts from the log and compares it with the report, and confirms that the executor tests moved no extra money.")]
    h.append(f'<section class="s"><h2 id="A1">Appendix A.&nbsp; {APPENDICES[0]}</h2><p>The numbers in this report can be verified from the folder named <b>execution_evidence</b>, which is submitted with it. The folder contains:</p>'
             f'<table><tr><th style="width:30%">File</th><th>What it contains</th></tr>' + "".join(f"<tr><td><code>{a}</code></td><td>{b}</td></tr>" for a, b in vf) + "</table>"
             f'<p>To re-check the figures, run the verification program from inside the folder. It needs no network access and prints a pass or fail line for each check. The cases themselves can be regenerated from the project with the offline model, and replay to the same audit-chain heads (Section 9).</p></section>')

    # Appendix A: complete operation log, one row per operation
    rows_a, n = [], 0
    for c in cases:
        for cfg, label in (("UNPROTECTED", "Without protections"), ("PROTECTED", "With Oasis")):
            r = c["runs"][cfg]
            for k, st in enumerate(r["steps"], 1):
                n += 1
                mv = [t for t in st["ledger_transfers"] if t["memo"] != "verification_test"]
                mv_s = "; ".join(f"{t['amount']:,.2f} to {t['to']}" + (" (attacker)" if t["to_is_attacker"] else "") for t in mv) or "none"
                head = st["audit_entries"][-1]["hash"][:16] if st["audit_entries"] else ""
                good = st["outcome"]["status"] in ("rejected", "frozen", "held", "needs_verification") or not any(t["to_is_attacker"] for t in mv)
                rows_a.append(f"<tr><td class='n'>{n}</td><td>{e(cid(c))} step {k}</td><td>{label}</td><td>{e(st['outcome']['status'])}</td>"
                              f"<td style='color:{GREEN if good else RED}'>{e(mv_s)}</td><td><code>{head}</code></td></tr>")
    for r in o["executor_attacks"]:
        n += 1
        rows_a.append(f"<tr><td class='n'>{n}</td><td>executor: {e(r['attack'].replace('_', ' '))}</td><td>With Oasis</td><td>{e(r['status'])}</td>"
                      f"<td style='color:{GREEN}'>extra {r['extra_money_moved']:.2f}</td><td><code>{r['audit_head'][:16]}</code></td></tr>")
    h.append(f'<section class="s"><h2 id="A2">Appendix B.&nbsp; {APPENDICES[1]}</h2><p>One row per recorded operation. The head column is the first 16 characters of the audit-chain hash after the operation.</p>'
             f'<table class="long"><tr><th class="n">#</th><th>Operation</th><th>Configuration</th><th>Status</th><th>Money moved</th><th>Chain head</th></tr>{"".join(rows_a)}</table></section>')

    aud = []
    for c in cases:
        if c["id"].startswith("P2"):
            for cfg, label in (("UNPROTECTED", "Without Oasis protections"), ("PROTECTED", "With Oasis")):
                rows = "".join(f"<tr><td class='n'>{a['i']}</td><td>{e(a['kind'])}</td><td><code>{a['prev'][:32]}<br>{a['prev'][32:]}</code></td><td><code>{a['hash'][:32]}<br>{a['hash'][32:]}</code></td></tr>"
                               for st in c["runs"][cfg]["steps"] for a in st["audit_entries"])
                aud.append(f"<h3>{label}</h3><table><tr><th class='n'>Index</th><th>Kind</th><th>Previous hash</th><th>Entry hash</th></tr>{rows}</table>")
    h.append(f'<section class="s"><h2 id="A3">Appendix C.&nbsp; {APPENDICES[2]}</h2><p>Audit-log entries recorded for case P2 (altered tuition invoice). Each entry hash is computed over its index, time, kind, data and the previous hash.</p>{"".join(aud)}</section>')
    gl = [("Audit chain", "A log in which each entry contains the hash of the previous one, so any later change is detectable."),
          ("Canary", "A decoy credential or account that no honest request would touch; using it signals an attack."),
          ("Device-key approval", "A signature made with the approver's registered device key over the exact payment draft."),
          ("Executor", "The only component that moves money. It enforces the signed intent exactly."),
          ("Intent", "A signed record of one exact payment: payee, account, amount, currency, route, nonce and expiry."),
          ("MOCK", "Simulated data: accounts, rates, fees, registry. Not real."),
          ("Nonce", "A value that may be used once; reuse indicates a replayed payment."),
          ("Registry", "The list of verified payees and their accounts. Money goes only to a registry account."),
          ("Without Oasis protections", "The same account with verification, signed intents and policy, and canaries disabled.")]
    h.append(f'<section class="s"><h2 id="A4">Appendix D.&nbsp; {APPENDICES[3]}</h2><table><tr><th style="width:26%">Term</th><th>Meaning</th></tr>'
             + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in gl) + "</table></section></body></html>")
    return "".join(h)


# ---------------------------------------------------------------------------------------------- printing
def find_browser() -> str:
    b = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    if not b:
        raise SystemExit("no Edge/Chrome found to print the PDF")
    return b


def print_pdf(markup: str, out: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "report.html"
        page.write_text(markup, encoding="utf-8")
        subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}", page.as_uri()],
                       check=True, timeout=180, capture_output=True)


def page_map(pdf: Path) -> dict[str, int]:
    from pypdf import PdfReader
    texts = [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]
    found: dict[str, int] = {}
    for n, t in enumerate(texts, 1):
        if n <= 2:                       # cover and contents
            continue
        flat = re.sub(r"\s+", " ", t)
        for k, title in enumerate(SECTIONS, 1):
            if re.search(rf"(^| ){k}\.\s*{re.escape(title)}", flat) and f"S{k}" not in found:
                found[f"S{k}"] = n
        for k, title in enumerate(APPENDICES, 1):
            if re.search(rf"Appendix {chr(64 + k)}\.\s*{re.escape(title)}", flat) and f"A{k}" not in found:
                found[f"A{k}"] = n
    return found


def main() -> Path:
    o = json.loads((OUT / "evidence_results.json").read_text(encoding="utf-8"))
    log = OUT / "operation_log.jsonl"
    o["log_lines"] = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    braw = json.loads((OUT / "benchmark_results.json").read_text(encoding="utf-8"))
    bench = {k: braw["summary"][k] for k in ("baseline", "+verification", "+intents+policy", "full")}
    bmeta = braw["meta"]
    out = OUT / "Execution_Evidence_Report.pdf"
    probe = {f"S{k}": 99 for k in range(1, len(SECTIONS) + 1)} | {f"A{k}": 99 for k in range(1, len(APPENDICES) + 1)}
    print_pdf(build(o, bench, bmeta, probe), out)
    pages = page_map(out)
    print_pdf(build(o, bench, bmeta, pages), out)
    again = page_map(out)
    if again != pages:                    # the contents page length is fixed, so this should not happen
        print_pdf(build(o, bench, bmeta, again), out)
    from pypdf import PdfReader
    print(f"wrote {out.name}: {len(PdfReader(str(out)).pages)} pages; sections at {again}")
    return out


if __name__ == "__main__":
    main()
