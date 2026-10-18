"""Build the Technical Documentation (PDF): system architecture, core algorithms, security design.

Single-line page border, cover with the OASIS logo and "by Avertix", contents with page numbers. Black text on white; one accent
colour is used only to highlight key terms and figures. Static HTML printed by headless Edge/Chrome; page numbers for the contents
are found with a first pass over the printed PDF (needs `pypdf`). No model call, no network.

    PYTHONPATH=. python -m eval.build_techdoc_pdf
"""
from __future__ import annotations
import base64
import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "Technical_Documentation.pdf"
LOGO = ROOT / "docs" / "assets" / "oasis-logo-dark.svg"
BROWSERS = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe")
INK, MID, LIGHT, ACCENT = "#111", "#555", "#ececec", "#0b5d52"
e = html.escape

KEYNOTES = "Key Notes"
SECTIONS = ["Introduction", "System Architecture", "Core Algorithms", "Security Design", "Evaluation Summary", "Limitations"]
APPENDICES = ["Data Model", "API Surface", "Configuration and Reproducibility", "Repository Layout"]

FRAME = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 210 297' preserveAspectRatio='none'>"
         "<rect x='10' y='10' width='190' height='277' fill='none' stroke='black' stroke-width='0.4'/></svg>")
CSS = f"""
@page {{ size: A4; margin: 28mm 22mm 24mm 22mm; background: url("data:image/svg+xml;utf8,{FRAME}") no-repeat; background-size: 210mm 297mm; background-position: -22mm -28mm;
  @top-left {{ content: "Oasis  |  Technical Documentation"; font: 8.5pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 11mm; }}
  @top-right {{ content: "Avertix"; font: 8.5pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 11mm; }}
  @bottom-center {{ content: counter(page); font: 9pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 5mm; }} }}
@page :first {{ margin: 0; background-position: 0 0; @top-left {{ content: none; }} @top-right {{ content: none; }} @bottom-center {{ content: none; }} }}
* {{ box-sizing: border-box; }}
body {{ font: 10.8pt/1.6 Cambria, 'Times New Roman', serif; font-variant-numeric: lining-nums; color:{INK}; margin: 0; }}
h2 {{ font-size: 17pt; margin: 0 0 12pt; padding-bottom: 5pt; border-bottom: 0.8pt solid {INK}; break-after: avoid; }}
h3 {{ font-size: 12pt; margin: 18pt 0 5pt; break-after: avoid; }}
h4 {{ font-size: 10.8pt; margin: 12pt 0 3pt; break-after: avoid; font-style: italic; }}
section.s {{ break-before: page; }}
p {{ margin: 7pt 0; text-align: justify; }} .small {{ font-size: 8.8pt; color:{MID}; }}
b.k {{ color:{ACCENT}; }}
table {{ border-collapse: collapse; width: 100%; font-size: 9.6pt; margin: 9pt 0; }} tr {{ break-inside: avoid; }} thead {{ display: table-header-group; }}
th, td {{ border: 0.6pt solid #888; padding: 4.5pt 7pt; text-align: left; vertical-align: top; }} th {{ background: {LIGHT}; }}
td.n, th.n {{ text-align: right; }} td.c {{ text-align: center; }}
code {{ font: 8.3pt Consolas, 'Courier New', monospace; }}
pre {{ font: 8pt/1.35 Consolas, 'Courier New', monospace; background: #f6f6f6; border: 0.6pt solid #888; padding: 6pt 9pt; margin: 8pt 0; white-space: pre-wrap; break-inside: avoid; }}
ul, ol {{ margin: 6pt 0 6pt 18pt; padding: 0; }} li {{ margin: 3.5pt 0; }}
.formula {{ text-align: center; font: 10pt Cambria, 'Times New Roman', serif; font-style: italic; border-top: 0.5pt solid #999; border-bottom: 0.5pt solid #999; padding: 7pt 8pt; margin: 8pt 0; break-inside: avoid; }}
.flow {{ list-style: none; margin: 8pt 0; padding: 0; }} .flow li {{ margin: 0; padding: 4pt 8pt; border: 0.6pt solid #888; border-top: none; break-inside: avoid; }} .flow li:first-child {{ border-top: 0.6pt solid #888; }}
.note {{ border: 0.8pt solid {INK}; border-left: 3.5pt solid {ACCENT}; padding: 7pt 12pt; margin: 12pt 0; break-inside: avoid; }} .note p {{ margin: 3pt 0; }}
figure {{ margin: 12pt 0; break-inside: avoid; text-align: center; }} figcaption {{ font-size: 8.8pt; color:{MID}; margin-top: 3pt; }}
.cover {{ height: 297mm; position: relative; text-align: center; break-after: page; }}
.cover .top {{ position:absolute; top: 62mm; left: 0; right: 0; }} .cover h1 {{ font-size: 28pt; letter-spacing: 2pt; margin: 0; font-weight: 400; }}
.cover .sub {{ font-size: 12.5pt; margin: 6mm 0 0; text-align: center; color:{MID}; }}
.cover .mid {{ position:absolute; top: 128mm; left: 0; right: 0; }} .cover .mid img {{ width: 118mm; }}
.cover .by {{ font-size: 14pt; margin-top: 5mm; font-style: italic; text-align: center; }}
.toc td {{ border: none; padding: 6pt 0; font-size: 12pt; }} .toc td.n {{ text-align: right; width: 14mm; }}
.toc td.dots {{ border-bottom: 0.6pt dotted {MID}; }} .toc tr.app td {{ font-size: 11.5pt; }}
"""


def tbl(head: list[str], rows: list[list[str]], widths: list[str] | None = None) -> str:
    w = widths or [""] * len(head)
    th = "".join(f'<th style="width:{x}">{h}</th>' if x else f"<th>{h}</th>" for h, x in zip(head, w))
    return f"<table><tr>{th}</tr>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table>"


def note(body: str) -> str:
    return f'<div class="note">{body}</div>'


def k(t: str) -> str:
    return f'<b class="k">{t}</b>'


# ---------------------------------------------------------------------------------------------- architecture diagram
def fig_architecture() -> str:
    def box(x, y, w, h, title, sub="", bold=False):
        t = f'<text x="{x + w / 2}" y="{y + 15}" text-anchor="middle" font-size="10.5" font-weight="{700 if bold else 600}">{title}</text>'
        s = "".join(f'<text x="{x + w / 2}" y="{y + 28 + 11 * i}" text-anchor="middle" font-size="8.3" fill="#444">{ln}</text>' for i, ln in enumerate(sub.split("|")) if ln)
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#fff" stroke="#111" stroke-width="1"/>{t}{s}'

    def arrow(x1, y1, x2, y2):
        return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#111" stroke-width="1" marker-end="url(#a)"/>'

    parts = ['<svg viewBox="0 0 640 430" width="100%" font-family="Cambria, Times New Roman, serif">',
             '<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#111"/></marker></defs>',
             # untrusted zone
             '<rect x="8" y="8" width="624" height="132" fill="none" stroke="#777" stroke-dasharray="5 4"/>',
             '<text x="18" y="24" font-size="9" fill="#555">UNTRUSTED: may propose and explain, never decides</text>',
             box(20, 36, 120, 54, "Student / Parent", "React UI, chat|device-key signing"),
             box(160, 36, 140, 54, "Documents", "invoice text, email, image|(hostile until checked)"),
             box(320, 36, 140, 54, "AI model", "Amazon Nova Pro (live)|offline model by default"),
             box(480, 36, 140, 54, "Planner", "tool-calling agent|proposals only"),
             '<text x="320" y="122" text-anchor="middle" font-size="8.5" fill="#444">Extraction, risk score, plan, explanation: all treated as untrusted input</text>',
             # trusted zone
             '<rect x="8" y="152" width="624" height="270" fill="none" stroke="#111" stroke-width="1.4"/>',
             f'<text x="18" y="168" font-size="9" fill="{ACCENT}" font-weight="700">TRUSTED: deterministic code that decides and enforces</text>',
             box(20, 180, 280, 44, "FastAPI + role dependencies", "roles: student, parent, judge, public (read-only)"),
             box(340, 180, 280, 44, "Pipeline (six steps)", "Understand, Plan, Verify, Commit, Execute, Prove"),
             box(20, 244, 130, 66, "Verification", "payee registry|ramp, test payment"),
             box(165, 244, 130, 66, "Policy engine", "R01 to R19|tiers 1, 2, 3"),
             box(310, 244, 150, 66, "Intents and executor", "Ed25519 + ML-DSA-65|exact match, nonce, expiry"),
             box(475, 244, 145, 66, "Corridor rules", "LRS, TCS, SAFE|source and date per rule"),
             box(20, 330, 190, 78, "Mock rails and ledger", "sandbox ledger, payee registry|rates, fees, routes (MOCK)"),
             box(225, 330, 190, 78, "Proof layer", "audit hash chain, proof packs|Trust Pass, anchor"),
             box(430, 330, 190, 78, "Storage", "SQLite, payload AES-256-GCM|keys outside the database"),
             arrow(80, 90, 80, 180), arrow(230, 90, 230, 180), arrow(390, 90, 390, 180), arrow(550, 90, 550, 180),
             arrow(480, 224, 480, 244), arrow(85, 224, 85, 244), arrow(230, 224, 230, 244), arrow(385, 310, 385, 330), arrow(120, 310, 120, 330),
             '</svg>']
    return f'<figure>{"".join(parts)}<figcaption>Figure 1. Components and the trust boundary. Arrows show data flowing into trusted code; nothing flows from the AI model to the executor.</figcaption></figure>'


# ---------------------------------------------------------------------------------------------- content
def build(pages: dict[str, int]) -> str:
    logo = "data:image/svg+xml;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Oasis Technical Documentation</title><style>{CSS}</style></head><body>"]
    h.append(f'<div class="cover"><div class="top"><h1>TECHNICAL DOCUMENTATION</h1><p class="sub">System Architecture, Core Algorithms and Security Design</p></div>'
             f'<div class="mid"><img src="{logo}" alt="OASIS"><p class="by">by Avertix</p></div></div>')

    def row(label, key, cls=""):
        return f'<tr class="{cls}"><td style="white-space:nowrap">{e(label)}</td><td class="dots"></td><td class="n">{pages.get(key, "")}</td></tr>'
    rows = [row(KEYNOTES, "K")] + [row(f"{i}.  {t}", f"S{i}") for i, t in enumerate(SECTIONS, 1)] + [row(f"Appendix {chr(64 + i)}.  {t}", f"A{i}", "app") for i, t in enumerate(APPENDICES, 1)]
    h.append('<section class="s" style="break-before:auto"><h2>Contents</h2><table class="toc">' + "".join(rows) + "</table></section>")

    h.append(f'''<section class="s"><h2>{KEYNOTES}</h2>
<p>Please read these points before using the system.</p>
<ol>
<li><b>Hosted copy and login passcodes (demo roles).</b> Address: <code>https://oasis.koreacentral.cloudapp.azure.com</code>. Passcodes are sent to judges separately by the organisers.</li>
<li><b>The API key has a credit limit.</b> The key supplied with the project has a limited credit budget. When it is reached, the AI features fall back to the deterministic offline path, so every function keeps working.</li>
</ol></section>''')

    def sec(n, body):
        return f'<section class="s"><h2>{n}.&nbsp; {SECTIONS[n - 1]}</h2>{body}</section>'

    def app(n, body):
        return f'<section class="s"><h2>Appendix {chr(64 + n)}.&nbsp; {APPENDICES[n - 1]}</h2>{body}</section>'

    # ------------------------------------------------------------------ 1
    h.append(sec(1, f"""
<p>Oasis is an AI payment assistant for international students and the families who support them. It is submitted to the track <b>AI as a Financial Participant</b>, sub-track <b>Cross-border &amp; Student Finance Assistant</b>. This document describes how it is built: the architecture, the algorithms that make decisions, and the security design that limits what the AI can do.</p>
<h3>1.1 The pain points we are solving</h3>
<p>The failures below come from public sources and from a small set of informal, survey-style conversations we held with 10 people (a convenience sample, not a statistical survey; see "What people told us" below).</p>
{tbl(["Problem", "Evidence", "How Oasis responds"], [
    ["An impostor landlord asks for rent to be sent to a new account", "Shanghai municipal government, anti-fraud guidance for international students (2024). Informal conversations: 2 of the 6 students met a fake landlord while looking for a home and were not scammed, because the landlord refused a live viewing and offered only pictures, and when someone was sent to check in person the house did not exist", "Money goes only to the registry account; a changed account restarts the verification ramp"],
    ["A tuition invoice is altered to show a different bank account", "KU Leuven invoice-fraud warning; UK university notices", "The account on the document is never trusted; a contradiction by the registry is rejected"],
    ["An AI agent is steered by hidden text, or a tool rewrites payment details", "Published reports on prompt injection and tool poisoning", "Escalate-only AI, canaries, and an executor that enforces the signed intent exactly"],
    ["A large transfer is split to avoid the parent's approval", "Recognised structuring pattern", "Split-payment detection and sequence anomaly flags hold the payment"],
    ["Sending money through a bank is expensive", "World Bank, Remittance Prices Worldwide: bank routes are the costliest provider type. Informal conversations: 3 of the 4 parents could not send money because of the exchange-rate steps, some not understanding them, and 3 interning students found the difference between rates high when spending", "Route planner ranks routes on the amount the recipient receives and reports savings"],
    ["Cost-of-living worry; newcomers invisible to lenders", "QS International Student Survey 2023; Statistics Canada 2023", "Forecast and runway triggers; a verified payment record (Trust Pass), not a credit score"]], ["30%", "34%", "36%"])}
<p><b>What people told us.</b> We held informal conversations with 10 people we know: 6 international students and interns abroad (Vietnam, Japan, Germany, Spain and Tanzania) and 4 parents. Two of the students met a fake landlord while looking for a home and were not scammed: the landlord refused a live viewing, offered only pictures, and when someone was sent to check in person the house did not exist. One student had trouble opening a bank account abroad, which delayed rent and other payments. Three of the four parents could not send money because the exchange-rate steps were involved, and some did not understand them. Three interning students found the difference between exchange rates high when spending. These are individual accounts, not measured frequencies.</p>
<h3>1.2 The answer</h3>
<p>A student abroad pays tuition, rent and living costs across borders, often in a second currency, to payees they cannot easily check, under deadlines. Scams (altered tuition invoices, impostor landlords, look-alike payees), hidden fees and late or short transfers cost real money. An AI assistant could help, but only if it can be given a role in the payment process without being able to move money wrongly.</p>
<p>Oasis answers with one principle: {k("the AI proposes, deterministic code decides.")} The AI reads documents, plans payments, labels chat requests and explains risk. It never approves a payment, signs, holds a credential, changes who is trusted, or writes to the audit log. Every payment passes the same verification, policy, signing and enforcement path whether a person or the AI started it.</p>
<p class="small"><b>Supporting design choice.</b> Payments and credit records are signed with both Ed25519 and post-quantum ML-DSA-65 (NIST FIPS 204), and both must verify, so a student's payment history stays checkable for the years a landlord, lender or visa office may need it.</p>
<h3>1.3 What the system covers</h3>
{tbl(["Track need", "Oasis feature"], [
    ["Tuition payments", "Verified-payee tuition flow; altered-invoice defence; invoice intake from text, email and image; duplicate-payment guard"],
    ["Remittances", "Route planner (cheapest on-time route against a typical bank route); FlightPath recovery for delayed, rejected or short-credited transfers; peer netting simulation"],
    ["Multi-currency management", "Six-currency view and 60-day coverage; FX plan for USD and EUR bills; corridor rules (SAFE quota, LRS, TCS); agentic payment plan with a validator"],
    ["Credit building", "Verified payment record and Oasis Trust Pass, with zero-knowledge threshold proofs and a credit-growth plan. A record, not a credit score; records are hybrid post-quantum signed so they remain verifiable long-term"],
    ["Long-lived trust", "Post-quantum hybrid signatures (Ed25519 + ML-DSA-65, both required) on every payment intent and proof, and a hybrid post-quantum TLS key exchange (Section 3.13)"]], ["28%", "72%"])}
<h3>1.4 Main features</h3>
<p>The main features, named as in the application's tabs.</p>
{tbl(["Feature", "What it does"], [
    ["Chat", "Talk to Oasis in English or Chinese: ask about bills, rates and runway, estimate a payment, or ask for a draft. A payment always ends as a draft the student signs."],
    ["Passport", "The student's profile: balances in six currencies, bills, payees and payment history. Plans and checks start from it."],
    ["Plan", "The AI proposes which routes fund which bills in time; the validator checks every amount, deadline and limit, and a plan never skips approval."],
    ["FlightPath", "Follows a sent transfer, says what a delay or short credit means for the bill's deadline, and never resends blindly."],
    ["Twin", "Simulates the rest of the semester and shows the chance of missing each deadline, with mitigations."],
    ["Netting", "Simulation that matches opposite INR and CNY flows at the mid rate to show possible savings. Simulation only."],
    ["Parent", "The parent co-signs larger transfers; the request is shown in English, Tamil, Hindi or Chinese (machine-drafted)."],
    ["Demo", "Two scripted, repeatable runs: a student's semester and an attack story. Each replays to the same audit-chain head."],
    ["Break it", "Judges paste any fraud attempt and watch it run through the real pipeline, or tamper with, replay or forge a signed payment and hand it to the real executor."],
    ["Red team", "Judge-only console for attacking the system. Each judge login gets its own sandbox and attempt log."],
    ["Proof", "Opens a proof pack for a payment and verifies it independently, with a &ldquo;try tampering&rdquo; check."],
    ["Trust Pass", "A credential built from verified payments that the student can share in part, with zero-knowledge threshold proofs. Not a credit score."],
    ["Credit growth", "A read-only milestone plan and what-if view over the payment record; it never suggests extra payments."],
    ["Evidence Passport", "One signed, QR-verifiable bundle that shows a payment reached a registry-verified payee."],
    ["Invoice intake", "Paste text, upload an email or a photo; hidden text is kept as evidence and the account on the document is never trusted."],
    ["Why-cards", "A plain explanation of each hold or refusal, with what is not established and the next step."],
    ["Corridors and FX", "Six corridors with rules for LRS, TCS and the SAFE quota, and foreign-currency plans for USD and EUR bills."],
    ["Numbers", "The committed benchmark results, with their caveats."],
    ["Post-quantum signing", "Every payment intent is signed with two algorithms, one of them post-quantum, and both must verify.", "3.13"]], ["20%", "80%"])}"""))

    # ------------------------------------------------------------------ 2
    h.append(sec(2, f"""
<h3>2.1 Components</h3>
{fig_architecture()}
{tbl(["Component", "Role", "Code"], [
    ["UI", "React 18 and Vite single-page app: chat, Passport, parent view, FlightPath, netting, proof viewer, red-team console. English default, Chinese available (machine-drafted).", "<code>frontend/src</code>"],
    ["API", "FastAPI. Every state-changing route declares a role dependency; public routes are read-only. Security headers on every response.", "<code>oasis/api</code>"],
    ["Agent and planner", "Six-step pipeline; tool-calling planner (offline deterministic, or Amazon Nova Pro); chat router and guarded labeller; recovery drafts.", "<code>oasis/agent</code>"],
    ["Trust layer", "Verification ramp, policy engine, signed intents, executor, canaries, corridor rules, audit chain.", "<code>oasis/trust</code>"],
    ["Mock rails", "Sandbox ledger, payee registry (WeIdentity-style credentials), rates, fees, routes, wallet FX.", "<code>oasis/mock</code>"],
    ["Corridor rules", "Rules as data with source, date and status (INR to CNY and five further corridors).", "<code>oasis/trust/rules</code>"],
    ["Proof layer", "Proof packs, standalone verifier, payment-reliability record, Trust Pass, zero-knowledge thresholds, anchor interface.", "<code>oasis/proof</code>, <code>oasis/chain</code>"],
    ["Storage", "SQLite. Audit log written per entry; state saved as a snapshot after each state-changing request; payload columns AES-256-GCM encrypted.", "<code>oasis/storage.py</code>"]], ["18%", "62%", "20%"])}
<h3>2.2 Trust boundary</h3>
<p>Documents, screenshots, web pages, tool output and every model output are untrusted. The policy engine, intent builder and signer, executor, verification ramp, registry interface and audit log are deterministic code. Only the executor holds the sandbox payment credential.</p>
{tbl(["The AI may", "The AI may never"], [
    ["Read documents and images and extract payment fields", "Hold the payment credential or a signing key"],
    ["Score risk (the score can only escalate a decision)", "Approve a payment or sign an intent"],
    ["Propose a payment plan by calling read-only tools", "Change a payee's verification status or the registry"],
    ["Label a chat message and explain decisions", "Write to or edit the audit log"],
    ["Draft a recovery message to the registry's own contact", "Choose a payee account (only the registry account is paid)"]], ["50%", "50%"])}
<h3>2.3 The path of one payment</h3>
<ol>
<li>{k("Understand.")} The request (typed, pasted, emailed or photographed) is read into fields. A canary scan looks for decoy credentials; the risk scorer adds evidence.</li>
<li>{k("Plan.")} Routes are ranked on the amount the recipient receives; the corridor engine adds costs and warnings.</li>
<li>{k("Verify.")} The payee is looked up in the registry. The account on the request is never trusted; a contradiction rejects the request without touching the genuine record.</li>
<li>{k("Commit.")} Corridor check, then the policy engine decides allow, hold or freeze with a rule ID. Required approvals are device-key signatures over the exact draft hash. An intent is built and signed with two algorithms.</li>
<li>{k("Execute.")} The executor verifies both signatures, exact match, nonce and expiry, re-runs the policy, and only then moves money, to the registry account, in the sandbox ledger.</li>
<li>{k("Prove.")} A proof pack, audit entry, savings receipt and a plain-language why-card (for holds and refusals) are produced.</li>
</ol>
<h3>2.4 Stack and deployment</h3>
<ul>
<li><b>Backend:</b> Python 3.10+, FastAPI, Pydantic v2, SQLite from the standard library. <b>Frontend:</b> React 18 and Vite; the built <code>frontend/dist</code> is committed and served by the API, so Node is needed only to rebuild.</li>
<li><b>Model:</b> an offline deterministic model is the default and the floor for every function. The only live provider is {k("Amazon Nova Pro on Amazon Bedrock")}, through one adapter with a response cache, client-side rate limit, backoff, an on-disk token budget and a deterministic fallback.</li>
<li><b>Hosting:</b> Docker image (non-root, read-only filesystem, refuses to start without explicitly set passcodes). The submitted copy runs on an Azure virtual machine behind Caddy with a Let's Encrypt certificate. The live key is capped by a lifetime token budget; when it is exhausted or unreachable the system falls back to the deterministic path.</li>
<li><b>Post-quantum:</b> signatures are hybrid Ed25519 + ML-DSA-65. TLS with hybrid X25519MLKEM768 was tested with Caddy and an OpenSSL 3.5 client (a classical-only client was refused).</li></ul>
<h3>2.5 Real and simulated</h3>
{tbl(["Real (code that runs as designed)", "Simulated (labelled MOCK)"], [
    ["Six-step pipeline, policy engine, hybrid signed intents, intent-enforcing executor, verification ramp, canaries, corridor rules engine, hash-chained audit log, proof packs and verifier, plan validator, benchmark harness, Bedrock adapter", "Payment rails and balances, route spreads and fees, the payee registry, wallet spending, the clock, simulated humans in benchmarks, anchoring by default (a local hash-linked chain). Mid-market rates are real ECB reference rates when live rates are on, otherwise a snapshot"]], ["50%", "50%"])}"""))

    # ------------------------------------------------------------------ 3
    h.append(sec(3, f"""
<p>Each algorithm is deterministic and reproducible unless noted. Where a model is involved, its output is validated by code before it has any effect.</p>
<h3>3.1 Payee verification ramp</h3>
<p>A payee moves through a fixed set of states. A contradiction by the registry at any point gives <code>REJECTED</code>.</p>
<ol class="flow">
<li><b>1. UNVERIFIED</b>: nothing is known about the payee.</li>
<li><b>2. REGISTRY_CHECKED</b>: the payee and account match a registry credential.</li>
<li><b>3. Test payment</b>: a CNY 1 payment to the registry account succeeds.</li>
<li><b>4. VERIFIED_LOW</b>: payments allowed up to CNY 5,000.</li>
<li><b>5. VERIFIED_FULL</b>: reached after two successful payments.</li></ol>
<p>The registry is looked up by payee ID, falling back to an exact name match. If the account on the request differs from the registry credential the request is rejected and the genuine record is untouched. A registry-confirmed account change resets the payee to unverified and re-runs the ramp. Account numbers are normalised for comparison (NFKC, zero-width and format characters removed, spaces and dashes stripped) and then compared exactly, so normalisation can never turn an attacker's number into a registered one.</p>
<h3>3.2 Policy engine</h3>
<p>Rules are evaluated in a fixed order and the first match decides. Every decision records its rule ID. Each decision belongs to one of three tiers:</p>
{tbl(["Tier", "Meaning", "Decision"], [["1", "The agent may act alone within bounds", "allow"], ["2", "Needs explicit human approval", "hold, or allow once approved"], ["3", "Never; the payment is stopped", "freeze"]], ["10%", "55%", "35%"])}
{tbl(["Rule", "Decision", "Condition"], [
    ["R01", "freeze (3)", "a canary fired"],
    ["R02", "freeze (3)", "amount above the hard limit (CNY 200,000 default)"],
    ["R03", "freeze (3)", "the registry contradicts the recipient"],
    ["R04", "freeze (3)", "risk score at or above 0.85 (escalation only)"],
    ["R04b / R04c", "allow (1) / freeze (3)", "verification test payment: up to CNY 10 to a registry-confirmed recipient, otherwise freeze"],
    ["R15", "hold (2)", "document demands a currency other than CNY; never paid as if it were CNY"],
    ["R05", "hold (2)", "recipient not yet verified; no approval overrides it"],
    ["R18 / R19", "hold (2) / allow (2)", "USD or EUR payment: always holds for the student's signature; allowed only with it, a verified recipient and within limits"],
    ["R17", "hold (2)", "duplicate: same invoice reference, identical document (30 days) or already-paid obligation; no approver is offered, the student must explicitly choose to pay again"],
    ["R06", "hold (2)", "corridor hold: LRS, purpose mismatch, split payments"],
    ["R07", "hold (2)", "amount above the recipient's ramp limit"],
    ["R08", "hold (2)", "risk score at or above 0.5; no approval releases it"],
    ["R09 / R11 / R12", "approvers / hold / allow (2)", "family-support transfers above INR 50,000 need student and parent; missing approvals hold; all approvals present, recipient verified and within limits allows"],
    ["R10", "allow (1)", "recurring payment up to CNY 500 to a verified-full recipient"],
    ["R13 / R14", "allow (1) / allow or hold (2)", "own-balance conversion at a student-set rate target within CNY 5,000; larger conversions need the student"],
    ["R16", "hold (2)", "out-of-band request: a document asking to change approvers or limits, a refund, an unlisted authority's demand, or a message announcing new bank details. No approval path; the student confirms through a registry-verified contact"]], ["14%", "22%", "64%"])}
<h3>3.3 Signed intents and the executor</h3>
<p>An intent is one exact payment: payee, account, amount, currency, route, nonce, expiry and approvals. Its canonical JSON (sorted keys, no whitespace) is signed with {k("Ed25519 and ML-DSA-65")}; both must verify. The signing interface is algorithm-agnostic (an optional SM2/SM3 signer exists), and only hashes are anchored. The executor pays only if both signatures verify, the payload equals the intent exactly, the intent has not expired, the nonce is unused, and the policy, re-evaluated at execution time, still says allow. Any failure freezes the payment. This is what stops tool-poisoning rewrites after approval, and replays.</p>
<h3>3.4 Risk scoring</h3>
<p>A heuristic scorer weighs urgency language, instructions addressed to the assistant, look-alike or partly matching payee names, an account the registry contradicts, unknown payees, amount mismatch and amounts just under an approval threshold. {k("Sequence anomaly flags")} add evidence from payment history: a burst of payments to several payees in 24 hours (+0.30), a third payment to one payee in 24 hours (+0.20), an amount more than three times earlier ones to that payee (+0.25). An optional trained logistic model and a live-model scorer exist; they combine as the maximum, so {k("the score can only escalate")} (hold at 0.5, freeze at 0.85) and a failed model call falls back to the heuristic. Sanctions screening against a public OFAC snapshot is evidence, never an automatic block or a clearance.</p>
<h3>3.5 Route planning and corridor engine</h3>
<p>The amount delivered to the recipient is:</p>
<div class="formula">delivered = (send &minus; fixed_fee) &times; mid &times; (1 &minus; spread) &times; (1 &minus; pct_fee)</div>
<p>Routes that miss the due date are excluded; the rest are ranked by delivered amount, then speed, then reliability, and savings are reported against a typical bank route. The amount to send is found by binary search on the same formula. Oasis has {k("six corridors")} (INR to CNY, CNY to USD, INR to USD, EUR to USD, INR to EUR, CNY to EUR) on one generic engine. The corridor engine reads rules from YAML data with source, retrieval date and status: LRS (USD 250,000 per remitter per financial year), TCS by purpose, the SAFE quota (USD 50,000 per person per calendar year, counted cumulatively), and split-payment detection (two or more payments to one payee within 72 hours, each just under a threshold). Unconfirmed values are shown as such.</p>
<h3>3.6 Agentic planner with a deterministic validator</h3>
<p>The planner is a tool-using agent whose only outputs are proposals. Its tools are read-only (<code>read_passport</code>, <code>list_obligations</code>, <code>get_rates</code>, <code>get_routes</code>, <code>check_corridor</code>, <code>forecast_runway</code>, plus calculators for route choice and SAFE splits) and <code>propose_plan</code>. A plan is a list of convert and pay steps. <code>validate_plan</code> simulates it chronologically and returns concrete errors: wrong payee or amount, late payment, unfunded or duplicated obligation, INR going negative, CNY not yet arrived when spent, SAFE or LRS exceeded. Errors go back to the model as tool results; at most four proposals are allowed. If the model cannot produce a valid plan, hits its token cap, or the API fails, the deterministic plan is used and the fallback is recorded. {k("Trade-offs and questions:")} the plan's explanation sets the chosen route against alternatives for the same INR and asks a clarifying question instead of guessing when there is no open bill or no source of funds. Accepting a plan re-validates it; every payment step then enters the normal pipeline, so a plan never bypasses approval.</p>
<h3>3.7 FX plan and peer netting</h3>
<p>Bills owed in USD or EUR are planned by a separate validator and paid under rules R18/R19, with the signature covering the currency; the ledger refuses a transfer whose currency does not match both accounts. Peer netting is a simulation: opposite INR-to-CNY and CNY-to-INR flows are matched greedily (earliest deadline first) and the matched volume settles at the mid rate. Only verified, already-approved payments with at least two days to the deadline are eligible, value is conserved, and a pool of one saves exactly zero. Real netting would need a licensed counterparty.</p>
<h3>3.8 FlightPath: consequence and recovery</h3>
<p>FlightPath follows a payment after it is sent. A journey state machine (prepared, checks complete, submitted, processing, credited, delayed, rejected) is reconciled against the route time and the required amount. The advice names the bill's deadline using plain arithmetic on held facts: days left, how long waiting is safe, whether a replacement could still arrive, and what is not established. {k("No option ever resends")} while the first transfer is unresolved; a new payment needs a rejection and a confirmed refund and then re-enters policy and approval.</p>
<h3>3.9 Explanations: why-card and rewrite guard</h3>
<p>Every hold or refusal produces a why-card with the reason, what the evidence cannot establish, and the next step. These are added after the audit entry is written, so the audit chain is unaffected. In live mode a model may reword a deterministic explanation, but the {k("rewrite guard")} accepts it only if every number is kept, none is added, and the text is plain (no preface, markdown or list); otherwise the deterministic text is used.</p>
<h3>3.10 Chat router and guarded labeller</h3>
<p>The chat router is deterministic: it normalises and decodes the text, decides security refusals first (bypass requests, registry edits, overpayment), then classifies intent and extracts amounts with deterministic parsers. A message it cannot place may optionally (off by default) be sent to the model, truncated and with no state, to propose a label only. The label is accepted only if it is in a closed list and passes a schema check; a payment label additionally needs the text itself to speak of paying a whole open bill with no amount in the text. A model-labelled payment still becomes a held draft built from the registry that only a device-key signature releases. Five further topics are answer-only intents with their own keyword rules, checked after the security refusals: <b>transfer_issue</b> (a late, short or rejected transfer: FlightPath advice, never a resend), <b>fx_bill</b> (a USD or EUR bill: points to the FX plan, where every foreign payment needs the student's signature), <b>parent_request</b> (the gap between open bills and the CNY balance, and the plan whose parent remittance the parent signs), <b>quota</b> (LRS used and left per remitter, and TCS) and <b>share_record</b> (how to issue the Trust Pass; not a credit score). None creates a draft, signs, converts or moves money, and the labeller may propose the same five labels.</p>
<h3>3.11 Proofs, Trust Pass and credit growth</h3>
<p>A proof pack holds the intent, its hash, verification state, costs, policy decision, audit entry and public keys, hybrid-signed. Because the keys in a pack prove nothing alone, verification reports success only when the key fingerprint matches one pinned out of band, and optionally when the anchor exists on an intact chain. The payment-reliability record lists only payments that completed the full pipeline with a verifying proof pack. The Trust Pass is built from it in the SD-JWT style: each entry gets a random salt and the credential signs only digests, so the holder discloses chosen entries or threshold claims ("at least N") and the verifier learns nothing else. Thresholds can be proved with Pedersen commitments and range proofs without revealing counts. It is a record of payment behaviour, {k("not a credit score")},. The credit-growth plan is read-only guidance over that record.</p>
<h3>3.12 Hash-chained audit log</h3>
<p>Each entry stores:</p>
<div class="formula">hash = SHA-256( canonical{{ i, ts, kind, data, prev }} )</div>
<p>The verifier recomputes the chain and reports the first broken link. Payment tokens are single-use, last 30 seconds, are bound to the intent, and never enter the log. The scripted demo uses a fixed seed, mock data, offline model and simulated clock, so each run reproduces the same chain head.</p>
<h3>3.13 Post-quantum cryptography</h3>
<p>Payment records are meant to be checked for years, so Oasis signs them with two independent algorithms and requires both: <b>Ed25519</b> (classical) and <b>ML-DSA-65</b> (NIST FIPS 204, post-quantum). A signed record stays trustworthy if one algorithm is later broken, which protects against "harvest now, forge later". Both come from maintained libraries; there is no home-made cryptography.</p>
<table><tr><th style="width:24%">Layer</th><th>Mechanism</th></tr>
<tr><td>Signed intents</td><td>The canonical JSON of the intent is signed with a list of algorithms. The executor pays only if every listed signature verifies; removing the ML-DSA-65 signature, or changing one character of the message, is refused.</td></tr>
<tr><td>Other signed records</td><td>The same hybrid signer signs registry credentials, proof packs, the Trust Pass, the payment-reliability record and the Evidence Passport.</td></tr>
<tr><td>Approvals</td><td>The approver signs the draft with Ed25519 in the browser; the draft is bound inside the intent that carries the hybrid signature.</td></tr>
<tr><td>Transport</td><td>TLS 1.3 with the hybrid key exchange X25519MLKEM768, provided by the proxy in front of the application. A classical-only client was refused in the test.</td></tr>
<tr><td>Crypto agility</td><td>The signer takes a list of algorithms, so a scheme can be added or retired without changing the executor or the proof format. An optional SM2/SM3 signer (Chinese national standard) was added this way.</td></tr>
</table>
<p>The measurements, the evidence and the limits of this design are in the Security Self-Assessment (Section 7 and the Known-Risk List).</p>"""))

    # ------------------------------------------------------------------ 4
    h.append(sec(4, f"""
<p>The design assumes that the AI, the documents it reads and every tool it calls can be wrong or hostile, and that safety must hold anyway. The permission tiers, threat model and known-risk list are in the Security Self-Assessment; this section states the design.</p>
<h3>4.1 Invariants</h3>
{tbl(["Invariant", "Enforced by"], [
    ["The AI only proposes and explains. It never approves, signs, holds a credential, changes a verification status or writes to the audit log. Its risk score can only escalate.", "Pipeline structure; escalate-only combination; tests"],
    ["Money goes only to the registry account, never to an account read from a document.", "Verification step and executor payload match"],
    ["The executor enforces the signed intent exactly: signatures, exact match, nonce, expiry, policy re-check. There is no bypass or debug flag.", "<code>executor.py</code>, <code>policy.py</code>, <code>intents.py</code>"],
    ["Every state-changing endpoint uses a role dependency. Public endpoints are read-only and need no secrets.", "<code>api/auth.py</code>; an API sweep over every route and method"],
    ["Approvals need a device-key signature over the exact draft hash. A role string grants nothing.", "Approver registry; browser-held Ed25519 keys"],
    ["A security change needs a test and an entry in the security evidence matrix.", "Repository rule"]], ["72%", "28%"])}
<h3>4.2 Defence in depth</h3>
<ul>
<li><b>Untrusted input:</b> hidden and look-alike characters are normalised and flagged; hidden text in email is kept as evidence; canaries (a fake token, a decoy payee, a decoy account) freeze any payment that touches them.</li>
<li><b>Out-of-band requests (R16):</b> documents that ask for something Oasis never does from a document are held with no approval path.</li>
<li><b>Access control:</b> roles student, parent and judge with signed session cookies (HttpOnly, SameSite=Strict); optional passkey second factor; rate and size limits; a red-team console limited to the judge, in a separate sandbox world.</li>
<li><b>Data protection:</b> AES-256-GCM on payload columns with row-bound data; keys outside the database, optionally passphrase-wrapped; strict response headers (CSP, frame denial, no-referrer).</li>
<li><b>Tamper evidence:</b> hash-chained audit log; hybrid-signed proof packs verifiable without secrets; intent hashes anchored to a labelled local chain, or to a four-node local FISCO BCOS test chain when enabled.</li></ul>
<h3>4.3 Degradation behaviour</h3>
{tbl(["Failure", "Behaviour"], [
    ["Model unreachable, slow (timeout 45 s) or over budget", "Deterministic parser, scorer and planner are used; the fallback and its reason are recorded"],
    ["Model returns unusable or unsafe output", "Validator or guard rejects it; deterministic text or plan is used"],
    ["Image cannot be read reliably", "Low-confidence hold; nothing is paid from a guessed field"],
    ["Live token budget exhausted", "Fallback to the offline path for the rest of the run"],
    ["Any executor check fails", "The payment is frozen, and the failure is audited"]], ["42%", "58%"])}
"""))

    # ------------------------------------------------------------------ 5
    h.append(sec(5, f"""
<p>Offline results are deterministic and reproducible; live results are from Amazon Nova Pro. Reports are in <code>eval/reports/</code>. Caveats are in Section 6.</p>
{tbl(["Evidence", "Result"], [
    ["Test suite", "1766 passed, 2 skipped (live FISCO and live PQ-TLS)"],
    ["Visible benchmark: 32 attacks, 12 genuine changes, four layer configurations", "Attack block rate 6.2% baseline, 68.8% with verification, 100% with intents and policy; money lost CNY 479,000 baseline, 0 with the full system; genuine completion 100%"],
    ["Hidden blind set: 40 cases", "100% blocked and 100% genuine completed after fixes"],
    ["Live extraction, Nova Pro", "Model followed an injection in 0 of 6 cases; full system money lost 0; genuine completion 83.3% (a usability cost)"],
    ["Live poisoned invoices", "0 of 128 changed account, amount or payee; 40 of 40 genuine invoices held for signature exactly as offline; 0 payments released without a signature"],
    ["Live planner (deterministic validator)", "56 of 56 plans valid without fallback; 140 of 140 deadlines met in the pooled run"],
    ["Outside-written sets through the live path", "550 attacks and 170 look-alikes, 0 breaches"],
    ["Offline planner; executor tamper tests", "8 of 8 plans valid, fees about 83% below a typical bank route; 10 of 10 tampered payments refused"],
    ["Audit chain and replay", "Demo reproduces identical chain heads; an edited entry is detected at the first broken link"]], ["34%", "66%"])}"""))

    # ------------------------------------------------------------------ 6
    h.append(sec(6, f"""
{tbl(["Limitation", "Effect and mitigation"], [
    ["Everything financial is simulated", "Rails, rates, fees and the registry are MOCK. Savings are not what a real student would save. A production path needs licensing, real rails, external audit and key management"],
    ["One corridor tested", "Six corridors are implemented; the whole application was tested only on INR to CNY for this demo. The other five were checked at the engine level"],
    ["Tests are largely self-written", "The attack and chat sets were written by the team or by outside AI systems (given only the pitch and API description, frozen before their first run) and then used to fix failures, so final scores are not out of sample; the first-run row of each report is the only out-of-sample number. Stress tests are white-box. The hidden blind set is partly burned. No external human audit"],
    ["Live evidence is small", "One model, one provider, small samples on MOCK data. The chat-label validator rule that removed the one trap label was added after the run and is post hoc. Model calls are not part of the Oasis audit chain: live results are saved report rows, not a provider-side log"],
    ["The keyword router is weak on unseen wording", "On 144 fresh paraphrases it placed 52 correctly, 19 on the wrong intent and 73 as unknown (first run). Security held (no money moved); task completion is what suffers"],
    ["Risk scorers are weaker out of sample", "They only escalate; the deterministic controls carry the guarantee"],
    ["Image reading is unreliable on hard images", "2 of 6 test images failed; limited by the registry-only rule and the student confirming fields"],
    ["Public deployment", "The TLS certificate is classical (only the key exchange is post-quantum); capped live key; not load-tested; credentials are demo-grade shared passcodes plus optional passkeys; not independently audited"],
    ["Languages and research", "Chinese, Tamil and Hindi text is machine-drafted. We held informal conversations with 10 people we know: 6 international students and interns abroad (Vietnam, Japan, Germany, Spain and Tanzania) and 4 parents: a small convenience sample, not a survey; no finance office was interviewed"],
    ["Credit building", "The record is not a credit score and no lender or regulator accepts it"]], ["32%", "68%"])}"""))

    # ------------------------------------------------------------------ appendices
    h.append(app(1, f"""
<p>The <b>Student Financial Passport</b> (Pydantic v2) holds the student (home and host currency, language, budget), balances per currency, obligations (type, payee, amount, currency, due date, status, recurrence), recipients with a verification record, rules (auto limit, co-approval threshold INR 50,000, hard limit, rate targets), approvers, remitted amounts for LRS and TCS, SAFE usage, funding source, expected income, categorised transactions, the autonomy log and the payment reputation.</p>
{tbl(["Object", "Content"], [
    ["Payment intent", "payee, account, amount, currency, route, nonce, not_after, approvals, signatures per algorithm"],
    ["Audit entry", "i, ts, kind, data, prev, hash"],
    ["Proof pack", "intent, hash, verification state, costs, policy decision, audit entry, anchor, public keys, hybrid signature"],
    ["Why-card", "reason, uncertainty, next step, rule ID"],
    ["Plan", "steps, rationale, tool-call trace, validator feedback, fallback flag, per-step status"],
    ["Ledger entry", "sandbox transfer with account, amount, currency, memo"]], ["24%", "76%"])}"""))

    h.append(app(2, f"""
<p>Generated from <code>oasis/api/main.py</code>; interactive documentation is at <code>/docs</code> (off in judge mode). Roles: S student, P parent, J judge, A any logged-in role, Public read-only.</p>
{tbl(["Group", "Endpoints", "Access"], [
    ["Session", "<code>/api/health</code>, <code>/api/auth/config</code>, <code>/api/auth/login|logout|me</code>, passkey routes, <code>/api/device/register</code>", "Public / A / S, P"],
    ["State", "<code>/api/state</code>, <code>/api/reset</code>, <code>/api/audit</code>, <code>/api/audit/verify</code>", "S, J / S / A"],
    ["Intake and payment", "<code>/api/intake</code>, <code>/intake/image</code>, <code>/intake/email</code>, <code>/api/chat</code>, <code>/api/approve</code>, <code>/api/pay-again</code>, <code>/api/recovery/approve</code>", "S (approve: S, P)"],
    ["Planning", "<code>/api/plan</code>, <code>/api/plans</code>, <code>/api/plan/{id}/accept|execute|consent</code>, <code>/api/plan/fx</code>, <code>/api/rate-target</code>, <code>/api/autonomy/tick</code>", "S (consent: P)"],
    ["Corridors and FX", "<code>/api/corridors</code>, <code>/corridors/compare|check</code>, <code>/api/corridor/rules</code>, <code>/api/fx/quote|convert</code>", "A / S"],
    ["FlightPath and netting", "<code>/api/flightpath/*</code>, <code>/api/netting/simulate</code>, <code>/api/netting/benchmark</code>", "S, J"],
    ["Proofs and credit", "<code>/api/proof/{id}</code>, <code>/proof/verify</code>, <code>/api/trust/fingerprint</code>, <code>/api/reliability/*</code>, <code>/api/trust-pass/*</code>, <code>/api/credit-growth/*</code>", "Verification: Public; issue: S"],
    ["Screening and parent", "<code>/api/screen</code>, <code>/api/parent/pending</code>, <code>/api/approvers</code>", "A / P"],
    ["Evaluation and demo", "<code>/api/benchmark</code>, <code>/api/demo/*</code>, <code>/api/redteam</code>, <code>/api/breakit/executor</code>", "S, J (red team: J)"]], ["20%", "56%", "24%"])}"""))

    h.append(app(3, f"""
<h3>C.1 Configuration</h3>
<p>Settings are environment variables loaded from <code>.env</code> (never committed).</p>
{tbl(["Variable", "Effect"], [
    ["<code>OASIS_LLM</code>", "<code>offline</code> (deterministic, no network) or <code>bedrock</code> (Amazon Nova Pro). Offline is forced in tests"],
    ["<code>OASIS_EXTRACT</code>, <code>OASIS_LLM_RISK</code>, <code>OASIS_ML_RISK</code>", "Live extraction, live risk scoring and trained-model scoring; all escalate-only"],
    ["<code>OASIS_RATES</code>", "<code>live</code> ECB reference rates (cached, MOCK fallback) or a mock snapshot"],
    ["<code>OASIS_ANCHOR</code>", "Local simulated chain (default) or <code>fisco</code>"],
    ["<code>OASIS_DB</code>, <code>OASIS_DATA_KEY</code>, <code>OASIS_KEY_PASSPHRASE</code>", "Database path, data key, passphrase wrapping of keys"],
    ["<code>OASIS_PASS_*</code>, <code>OASIS_JUDGE_MODE</code>, <code>OASIS_REQUIRE_PASSKEY</code>", "Role passcodes; judge mode (tighter limits, docs off); passkey second factor"]], ["40%", "60%"])}
<h3>C.2 Reproducibility</h3>
<ul>
<li>Offline mode, fixed seeds, seeded demo keys and nonces, and a simulated clock make the scripted demo repeat exactly; replays reach identical audit-chain heads.</li>
<li>Benchmarks run offline: <code>eval.runner --llm offline</code>, <code>eval.flightpath_bench</code>, <code>eval.netting_bench</code>, <code>eval.tasks_bench</code>. Live runs are checkpointed, token-capped and saved as report rows.</li>
<li>Test suite: <code>pytest -q</code> with an in-memory database and offline model; 1766 passed, 2 skipped.</li>
<li>The execution evidence folder contains a standard-library verifier that recomputes the audit chains and the headline figures from the logs.</li></ul>"""))

    h.append(app(4, """
<pre>oasis/
  agent/      pipeline, planner, plan_exec, recovery, autonomy, chat + nlu router, chat_llm,
              llm + bedrock_llm, risk (heuristic, ml_risk), i18n, localize, duplicates, fx_exec
  api/        FastAPI app, auth, passkeys, rate limits
  trust/      verification, intents, policy, executor, canaries, audit chain, crypto, rules/*.yaml
  planning/   routes, forecast, validator, tools, fxplan, calc
  corridors/  generic corridor engine         flightpath/  journey state machine and advice
  netting/    peer netting simulation         proof/       proof packs, reliability, Trust Pass, zk
  intake/     email, Telegram, IMAP           mock/        ledger, registry, rates, wallet FX
  chain/      anchor interface                market/      live rates
  storage.py  SQLite persistence              demo.py      scripted demo
eval/         benchmarks, scenarios, simulated humans, reports/
frontend/     React + Vite UI (dist committed)
tests/        pytest suite
docs/         technical documentation, security self-assessment, execution evidence notes</pre>"""))
    h.append("</body></html>")
    return "".join(h)


# ---------------------------------------------------------------------------------------------- printing
def find_browser() -> str:
    b = next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("msedge") or shutil.which("chrome")
    if not b:
        raise SystemExit("no Edge/Chrome found to print the PDF")
    return b


def print_pdf(markup: str, out: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "doc.html"
        page.write_text(markup, encoding="utf-8")
        subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={out}", page.as_uri()],
                       check=True, timeout=180, capture_output=True)


def page_map(pdf: Path) -> dict[str, int]:
    from pypdf import PdfReader
    found: dict[str, int] = {}
    for n, t in enumerate((p.extract_text() or "" for p in PdfReader(str(pdf)).pages), 1):
        if n <= 2:
            continue
        flat = re.sub(r"\s+", " ", t)
        if "K" not in found and re.search(r"(^| )Key Notes Please read", flat):
            found["K"] = n
        for i, title in enumerate(SECTIONS, 1):
            if re.search(rf"(^| ){i}\.\s*{re.escape(title)}", flat) and f"S{i}" not in found:
                found[f"S{i}"] = n
        for i, title in enumerate(APPENDICES, 1):
            if re.search(rf"Appendix {chr(64 + i)}\.\s*{re.escape(title)}", flat) and f"A{i}" not in found:
                found[f"A{i}"] = n
    return found


def main() -> Path:
    probe = {"K": 99} | {f"S{i}": 99 for i in range(1, len(SECTIONS) + 1)} | {f"A{i}": 99 for i in range(1, len(APPENDICES) + 1)}
    print_pdf(build(probe), OUT)
    pages = page_map(OUT)
    print_pdf(build(pages), OUT)
    from pypdf import PdfReader
    print(f"wrote {OUT.name}: {len(PdfReader(str(OUT)).pages)} pages; sections at {pages}")
    return OUT


if __name__ == "__main__":
    main()
