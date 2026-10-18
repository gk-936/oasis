"""Build the Security Self-Assessment Report (PDF).

Same page style as the execution-evidence report: single-line border, cover with the Oasis logo and "by Avertix", contents with
page numbers. Black text; colour only marks a status. Figures are read from saved reports where they exist. No model call, no network.

    PYTHONPATH=. python -m eval.build_security_pdf
"""
from __future__ import annotations
import base64
import html
import json
import re
from pathlib import Path

from eval.build_evidence_pdf import LOGO, print_pdf
from eval.pdf_figures import fig_money_lost, fig_outside_sets, fig_payment_path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "Security_Self_Assessment_Report.pdf"
EV = ROOT / "execution_evidence" / "evidence_results.json"
INK, MID, LIGHT = "#111", "#555", "#e4e6e8"
RED, GREEN, AMBER = "#b42318", "#117a3d", "#b7791f"
e = html.escape
TITLE = "Security Self-Assessment Report"
SECTIONS = ["Executive Summary", "Scope, Method and Evidence", "Trust Model", "Permission-Tier Implementation", "Threat Model and Controls",
            "Evidence Results", "Post-Quantum Cryptography", "Known-Risk List", "Out of Scope and Path to Production"]
APPENDICES = ["Hardening History", "How to Reproduce", "Glossary"]

FRAME = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 210 297' preserveAspectRatio='none'>"
         "<rect x='10' y='10' width='190' height='277' fill='none' stroke='black' stroke-width='0.5'/></svg>")
CSS = f"""
@page {{ size: A4; margin: 36mm 22mm 26mm 22mm; background: url("data:image/svg+xml;utf8,{FRAME}") no-repeat; background-size: 210mm 297mm; background-position: -22mm -36mm;
  @top-left {{ content: "Oasis  |  {TITLE}"; font: 8.5pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 15mm; }}
  @top-right {{ content: "Avertix"; font: 8.5pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 15mm; }}
  @bottom-center {{ content: counter(page); font: 9pt Cambria, 'Times New Roman', serif; color:{INK}; vertical-align: top; padding-top: 5mm; }} }}
@page :first {{ margin: 0; background-position: 0 0; @top-left {{ content: none; }} @top-right {{ content: none; }} @bottom-center {{ content: none; }} }}
* {{ box-sizing: border-box; }}
body {{ font: 11pt/1.62 Cambria, 'Times New Roman', serif; font-variant-numeric: lining-nums tabular-nums; color:{INK}; margin: 0; }}
h2 {{ font-size: 16pt; margin: 0 0 12pt; padding-bottom: 5pt; border-bottom: 1pt solid {INK}; break-after: avoid; }}
h3 {{ font-size: 12pt; margin: 18pt 0 5pt; break-after: avoid; break-inside: avoid; }}
section.s {{ break-before: page; }}
p {{ margin: 8pt 0; text-align: justify; }} .small {{ font-size: 8.8pt; color:{MID}; }}
table {{ border-collapse: collapse; width: 100%; font-size: 9.6pt; line-height: 1.45; margin: 9pt 0; }} tr {{ break-inside: avoid; }} thead {{ display: table-header-group; }}
th, td {{ border: 0.7pt solid #8a8f98; padding: 5pt 7pt; text-align: left; vertical-align: top; }} th {{ background: {LIGHT}; }}
td.n, th.n {{ text-align: right; }} td.c, th.c {{ text-align: center; }}
table.tight {{ font-size: 8.8pt; }} table.tight th, table.tight td {{ padding: 3.5pt 6pt; }}
.st {{ font-weight: 700; letter-spacing: .3pt; white-space: nowrap; }}
.notice {{ border: 1pt solid {INK}; padding: 9pt 13pt; margin: 14pt 0; break-inside: avoid; }}
ul {{ margin: 6pt 0 6pt 18pt; padding: 0; }} li {{ margin: 4pt 0; }}
.cover {{ height: 297mm; position: relative; text-align: center; break-after: page; }}
.cover .top {{ position:absolute; top: 62mm; left: 0; right: 0; }} .cover h1 {{ font-size: 28pt; letter-spacing: 2pt; margin: 0; font-weight: 400; }}
.cover .sub {{ font-size: 13pt; margin: 6mm 0 0; text-align: center; color:{MID}; }}
.cover .mid {{ position:absolute; top: 128mm; left: 0; right: 0; }} .cover .mid img {{ width: 118mm; }}
.cover .by {{ font-size: 14pt; margin-top: 5mm; font-style: italic; text-align: center; }}
.toc td {{ border: none; padding: 7pt 0; font-size: 12pt; }} .toc td.n {{ text-align: right; width: 14mm; }}
.toc td.dots {{ border-bottom: 0.7pt dotted {MID}; }}
"""


def ok(t): return f'<span class="st" style="color:{GREEN}">{t}</span>'
def bad(t): return f'<span class="st" style="color:{RED}">{t}</span>'
def warn(t): return f'<span class="st" style="color:{AMBER}">{t}</span>'
SEV = {"High": bad("HIGH"), "Medium": warn("MEDIUM"), "Low": "<span class='st'>LOW</span>"}


def toc_block(pages: dict[str, int]) -> str:
    def row(label, key, extra=""):
        return f'<tr><td style="white-space:nowrap">{e(label)}</td><td class="dots"></td><td class="n">{pages.get(key, "")}</td></tr>'
    rows = [row(f"{i}.  {t}", f"S{i}") for i, t in enumerate(SECTIONS, 1)]
    rows += [row(f"Appendix {chr(64 + i)}.  {t}", f"A{i}") for i, t in enumerate(APPENDICES, 1)]
    return '<h2>Contents</h2><table class="toc">' + "".join(rows) + "</table>"


def build(pages: dict[str, int]) -> str:
    ev = json.loads(EV.read_text(encoding="utf-8"))["summary"]
    logo = "data:image/svg+xml;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Oasis {TITLE}</title><style>{CSS}</style></head><body>"]
    h.append(f"""<div class="cover"><div class="top"><h1>SECURITY SELF-ASSESSMENT</h1><p class="sub">Permission Tiers and Known-Risk List</p></div>
<div class="mid"><img src="{logo}" alt="OASIS"><p class="by">by Avertix</p></div></div>""")
    h.append(f'<section class="s" style="break-before:auto">{toc_block(pages)}</section>')

    def sec(n, body): return f'<section class="s"><h2 id="S{n}">{n}.&nbsp; {SECTIONS[n-1]}</h2>{body}</section>'

    # 1 -------------------------------------------------------------------------------------------------------------
    h.append(sec(1, f"""<p>Oasis is an AI assistant for international students: it plans remittances and tuition payments, reads invoices, answers in chat and explains risk. This report is the project team's own assessment of how that assistant is kept from doing harm with money. It covers two things the organisers asked for: how the <b>permission tiers</b> are implemented, and the <b>known-risk list</b>.</p>
<p><b>The design in one sentence.</b> The AI model proposes and explains; deterministic code decides; a human signs with a device key; one component, the executor, moves money, and only the exact payment that was signed.</p>
<p class="small"><b>Supporting design choice.</b> Payments and credit records are signed with both Ed25519 and post-quantum ML-DSA-65 (NIST FIPS 204), and both must verify, so a student's payment history stays checkable for the years a landlord, lender or visa office may need it.</p>
<table><tr><th style="width:30%">Question</th><th>Answer</th></tr>
<tr><td>Can the AI approve a payment?</td><td>No. Approval needs an Ed25519 signature from the student's or parent's registered device key over the exact draft. A role name grants nothing.</td></tr>
<tr><td>Can the AI send money to an account it read in a document or message?</td><td>No. Money goes only to the account in the payee registry. An account typed in chat or printed on an invoice is never a destination.</td></tr>
<tr><td>Can the AI hold a credential or write to the audit log?</td><td>No. Only the executor mints a single-use, 30-second payment token. The audit log is appended by code, not by the model.</td></tr>
<tr><td>Can the AI lower a risk score or release a hold?</td><td>No. Its risk score is combined with the heuristic score by maximum, so it can only escalate.</td></tr>
<tr><td>What did the simulated attack tests show?</td><td>{ev['attacks_stopped']['PROTECTED']} of {ev['attack_cases']} scam scenarios mitigated with Oasis against {ev['attacks_stopped']['UNPROTECTED']} without; CNY {ev['money_lost_cny']['PROTECTED']:,.0f} reached attackers against CNY {ev['money_lost_cny']['UNPROTECTED']:,.0f}; {ev['executor_blocked']} of {ev['executor_attacks']} tampered signed payments refused (Section 6).</td></tr>
</table>"""))

    # 2 -------------------------------------------------------------------------------------------------------------
    h.append(sec(2, """<h3>2.1  What was assessed</h3>
<p>The assessment covers the Oasis backend (API, agent, trust layer, executor, audit log), the browser-side approval keys, the live-model paths (Amazon Nova Pro on Amazon Bedrock is the only live provider) and the public deployment on one Azure virtual machine. It does not cover real banks, real regulators or the registry itself, which is a mock.</p>
<h3>2.2  Method</h3>
<ul><li><b>Code inspection</b> of the policy engine, executor, intent signing, approvals, authentication and storage against the claims in this report.</li>
<li><b>Automated tests.</b> The offline suite (1766 passed, 2 skipped) runs with no network and forced offline mode. Each security claim maps to named tests in the security evidence matrix.</li>
<li><b>Authorization sweep.</b> A script calls every route and method as four identities (no session, student, parent, judge) with two request bodies and compares each response with the roles the code declares.</li>
<li><b>Benchmarks and attack sets.</b> A 32-attack and 12-genuine scenario benchmark run four ways (protections added one layer at a time), stress and fuzz runs, and three attack sets written by other AI assistants from the project description only.</li>
<li><b>Live-model checks</b> on saved report rows, run with a token cap.</li></ul>
<h3>2.3  How to read the evidence</h3>
<table><tr><th style="width:24%">Evidence type</th><th>Meaning here</th></tr>
<tr><td>Automated test</td><td>A hermetic test in the repository that the team wrote and runs on every change.</td></tr>
<tr><td>Saved report</td><td>Output of a benchmark or live run, kept as a file.</td></tr>
</table>"""))

    # 3 -------------------------------------------------------------------------------------------------------------
    h.append(sec(3, """<h3>3.1  Trust boundary</h3>
<table><tr><th style="width:18%">Zone</th><th>Contents</th></tr>
<tr><td>Untrusted</td><td>Every document, email, screenshot, chat message, web page and tool output the agent reads, and every model output: transcriptions, risk scores, plan proposals, chat labels and explanation rewrites.</td></tr>
<tr><td>Trusted</td><td>Policy engine, intent builder and signer, executor, payee registry interface, verification ramp, hash-chained audit log, approval verification.</td></tr>
<tr><td>Human</td><td>The student and, for large family transfers, the parent. They approve by signing the exact draft in the browser; their private keys never reach the server.</td></tr></table>
""" + fig_payment_path(1) + """<h3>3.2  Invariants</h3>
<p>These hold in every code path and are not configurable. A change that would weaken one needs a test and an entry in the evidence matrix.</p>
<ol style="margin-left:18px">
<li>The AI model only proposes and explains. It never approves a payment, holds a credential, changes a verification status or writes to the audit log. Its risk score may only escalate a decision.</li>
<li>Money goes only to the registry account for a verified payee, never to an account read from a document or message.</li>
<li>The executor enforces the signed intent exactly: signature, exact field match, nonce, expiry and a policy re-check at execution time. There is no bypass or debug flag.</li>
<li>Every state-changing endpoint declares the roles allowed to call it. Public endpoints are read-only and need no secret.</li>
<li>An approval is a device-key signature over the exact draft hash. A role string grants nothing.</li>
<li>When a model path fails or times out, the deterministic result is used. Failure never loosens a control.</li></ol>
<h3>3.3  Degradation behaviour</h3>
<p>Live model calls have a 45-second timeout, per-call token budgets and a lifetime budget of 3,000,000 tokens on the deployed key. If the budget is spent, the key is missing, the provider is unreachable or its filter refuses, the deterministic path is used and the fallback is recorded.</p>"""))

    # 4 -------------------------------------------------------------------------------------------------------------
    h.append(sec(4, """<h3>4.1  Roles and what each can reach</h3>
<p>Four identities exist. The student, parent and judge roles are established by a signed session; the fourth is anonymous access to public routes. Counts are from the running application's route table in this build.</p>
<table><tr><th style="width:15%">Role</th><th>Can do</th><th class="n" style="width:17%">Routes only this role reaches</th></tr>
<tr><td>Student</td><td>Intake, chat, plans, route and corridor tools, approve as student, register a device key, run the scripted demo, reset the sandbox, issue proofs and the Trust Pass.</td><td class="n">44 (38 state-changing)</td></tr>
<tr><td>Parent</td><td>Approve as parent, sign plan-conversion consent and the earned-autonomy step, see own pending list and own proofs. Cannot use student endpoints.</td><td class="n">2</td></tr>
<tr><td>Judge</td><td>Red-team console on its own private sandbox, plus read-only views of state, audit and plans. Cannot call any state-changing student endpoint.</td><td class="n">2</td></tr>
<tr><td>Public</td><td>Health, login, trust fingerprint and five proof or pass verifiers. Read-only, no secret, no state change.</td><td class="n">14 routes</td></tr></table>
<p class="small">Shared routes: 12 are open to all three signed-in roles (for example state, audit verification, signature screening), 19 to judge and student, 5 to parent and student (approval and device registration). In total 84 role-guarded route and method pairs plus 14 public routes in this build. The authorization sweep below covered 94 routes in an earlier run; the role-matrix test walks the live route table on every run, so new routes are covered automatically.</p>
<h3>4.2  How the roles are enforced</h3>
<ul><li><b>One mechanism.</b> Each route declares its allowed roles through a single dependency. A missing or invalid session gives 401; a valid session with the wrong role gives 403.</li>
<li><b>A test walks the real routes.</b> It calls every guarded route as every other role and anonymously and expects 403 and 401. A new state-changing route with no guard, or a wrong guard, fails the suite.</li>
<li><b>Authorization sweep.</b> 94 route and method pairs, 752 calls, 14 public routes, <b>0 findings</b>. Scope: it verifies that responses match the roles the code declares; it does not judge whether those roles are the right ones. That is covered by review and the evidence matrix.</li>
<li><b>Sessions.</b> Passcode login gives a signed (HMAC-SHA256), one-hour, HttpOnly, SameSite=Strict session that can be revoked on logout. Passcode comparison is constant-time; ten failed logins from one address lock it for a minute. Every state-changing request also passes an Origin check and a 2 MB body cap.</li>
<li><b>Passcodes.</b> None is built into the code. If the operator sets none, random ones are generated at start-up. Judge mode refuses generated passcodes and gives each login a private in-memory sandbox.</li></ul>
<h3>4.3  Approvals: why a role string grants nothing</h3>
<p>An approval is an Ed25519 signature over the text <i>role, draft hash</i>, where the draft hash covers payee, account, amount, currency, purpose, route, expiry and a nonce. The approver's private key is generated in the approver's browser and stays there; the server holds only public keys, so a stolen database or a compromised server cannot forge an approval. The policy engine is shown only roles whose signature verified against that role's registered key. The executor verifies again, and the approvals are stored in the signed intent and the proof pack, which a verifier re-checks. A changed amount, a different payment, a forged or missing signature, and an unregistered or retired device key are all refused. A correction in chat voids the old draft and issues a new nonce, so the old signature stops working.</p>
<h3>4.4  Autonomy tiers and the policy engine</h3>
<p>The policy engine evaluates a fixed rule order (ruleset 2026.10.2). The same inputs always give the same decision, and each decision is logged with its rule identifier and version. Tier 1 means the agent may act alone within bounds, tier 2 means explicit human approval, tier 3 means never (the payment is frozen).</p>
<table class="tight"><tr><th style="width:11%">Tier</th><th style="width:30%">What the agent may do</th><th>Rules and bounds</th></tr>
<tr><td>1  Alone</td><td>Small, recurring and tightly bounded actions that move money only to a fully verified payee or into the student's own balance.</td><td>R10: recurring bill up to CNY 500 to a fully verified recipient (not family support). R13: conversion into the student's own balance at a student-set rate target, up to CNY 5,000. R04b: verification test payment up to CNY 10, only to a registry-confirmed recipient.</td></tr>
<tr><td>2  Needs a human</td><td>Everything else that is legitimate: the student, and for large family support the parent as well, signs the exact draft.</td><td>R05 unverified recipient (the verification ramp must finish first). R06 corridor rule hold (LRS, purpose mismatch, split payments). R07 amount above the recipient's ramp limit. R09 family transfer above INR 50,000 needs student and parent. R11 and R12 approvals missing or present. R14 conversion above the auto limit.</td></tr>
<tr><td>2  Hold that approval cannot release</td><td>Surface the problem and wait for action outside the app.</td><td>R08: risk score at or above 0.5 (confirm out of band and re-submit). R15: document demands a currency other than CNY. R16: a document asks to change an approver or limit, refund or reverse, pay an authority not in the Passport, or change a payee's bank details. R17: duplicate payment; only an explicit, separately signed "pay again" releases it.</td></tr>
<tr><td>3  Never</td><td>Freeze the payment.</td><td>R01: a canary tripwire fired. R02: amount above the hard limit of CNY 200,000. R03: the registry contradicts the recipient. R04: risk score at or above 0.85. R04c: a test payment to an unconfirmed recipient.</td></tr></table>
<p class="small">A foreign-currency payment is never automatic: it always needs the student's signature, and the same freeze rules apply.</p>
<h3>4.5  The executor</h3>
<p>The executor is the only component that moves money. Before any transfer it checks that (1) the hybrid signature is valid, with both Ed25519 and ML-DSA-65 required to verify; (2) the payload matches the signed intent exactly, including payee, account, amount, currency and route; (3) the intent has not expired and its nonce has not been used; (4) every approval inside the intent is a valid device-key signature for that role; and (5) the policy decision, re-evaluated at execution time, is allow. Any failure freezes the payment. The payment credential is a per-execution token that expires in 30 seconds, works once and is bound to the intent, so a leaked token is worth little.</p>
<h3>4.6  Where the model sits in each tier</h3>
<table class="tight"><tr><th style="width:30%">Model task</th><th>Why it cannot exceed its permission</th></tr>
<tr><td>Transcribe an invoice (text or image)</td><td>The registry supplies the account. Unreadable or runaway values are held and the student is asked for text.</td></tr>
<tr><td>Label a chat message</td><td>A validator checks the label. Model slot values are never used. A payment label only creates a draft that needs the student's signature, and is dropped when the message gives instructions about labels or JSON.</td></tr>
<tr><td>Propose a payment plan</td><td>A validator recomputes amounts, routes, deadlines and limits. Failure falls back to the deterministic plan.</td></tr>
<tr><td>Score risk</td><td>Combined by maximum with the heuristic score; it can only raise a hold.</td></tr>
<tr><td>Reword an explanation</td><td>Shown only if every number is kept, none added and the text is plain; otherwise the template stands.</td></tr></table>"""))

    # 5 -------------------------------------------------------------------------------------------------------------
    threats = [
        ("Forged invoice, swapped bank details", "Registry verification: request details are treated as forgeable and the registry account is paid.", "Executor exact-match check", "Benchmark; executor tests"),
        ("Impostor landlord or university with a new account", "Verification ramp: registry check, test payment, low limit, then full limit. A genuine change is resolved, not blocked.", "Parent or student approval", "Cases P1, P7"),
        ("Altered tuition invoice", "Registry account replaces the account printed on the invoice.", "Risk evidence, duplicate rule R17", "Cases P2, P8"),
        ("Look-alike payee names", "Registry identity match is exact. No fuzzy name resolution.", "Risk evidence; sanctions screening raises review only", "Case P3; 170 look-alikes"),
        ("Hidden prompt injection in a document, image or email", "The model cannot approve, sign or pick the destination. Registry-only payment.", "Canary tripwire; risk hold", "Case P4; 128 live invoices"),
        ("Poisoned tool output rewrites payment details", "Intent binding: the executor refuses any change after signing.", "Canary scan of the payload", "Case P5; executor tests"),
        ("Split payments to dodge a limit", "Corridor split-pattern flag sends the hold to the parent; sequence flags raise the risk score.", "Policy hold R06", "Case P6"),
        ("Replay of an old approval or intent", "Single-use nonce and expiry.", "Audit log", "Executor tests"),
        ("Expired or forged approval; role swap; unsigned intent", "Device-key signature over the exact draft; role string grants nothing; hybrid signature required.", "Executor re-verifies", "Security tests; sweep"),
        ("Rewrite after approval", "Any changed field changes the draft hash, so the signature no longer verifies.", "Executor exact match", "Security tests"),
        ("Duplicate payment of a paid invoice", "Rule R17 holds it; only an explicit, signed pay-again releases it.", "Recipient limit R07", "Duplicate-payment tests"),
        ("Chat manipulation: bypass approval, reveal secrets, role abuse", "Security categories are decided first on a normalised copy of the text; refusals are audited and move CNY 0; replies pass a redaction filter.", "Draft always needs a signature", "Chat security tests; stress runs"),
        ("Label manipulation of the chat model", "Validator drops model slot values and meta-instruction labels; a payment is accepted only as a whole open bill.", "Draft always needs a signature", "Live trap set"),
        ("Cross-site or malformed requests", "Origin check, body cap, strict request models, security headers.", "SameSite=Strict cookie", "Judge-attack tests"),
        ("Forged proof pack with fresh keys", "Verification pins the server's key fingerprint and checks the anchor and chain.", "Local anchor only", "Review-fix tests"),
        ("Audit tampering", "Hash chain re-verified after decrypt at start-up; encrypted rows are bound to their row.", "Proof packs", "Audit tests"),
    ]
    trs = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td><td>{e(d)}</td></tr>" for a, b, c, d in threats)
    h.append(sec(5, f"""<p>Each threat has a primary control, a backup, and the evidence that exercises it. A forged request never changes the genuine recipient's registry record, so an attacker cannot lock a legitimate payee out.</p>
<table class="tight"><tr><th style="width:23%">Threat</th><th style="width:38%">Primary control</th><th style="width:21%">Backup</th><th>Evidence</th></tr>{trs}</table>
<p class="small">The matching test names and commands are in the security evidence matrix. Cases P1 to P8 are the execution-evidence scenarios.</p>"""))

    # 6 -------------------------------------------------------------------------------------------------------------
    h.append(sec(6, f"""<h3>6.1  Scam scenarios and tampered payments (offline, deterministic, MOCK)</h3>
<table><tr><th>Measure</th><th class="c">Without Oasis protections</th><th class="c">With Oasis</th></tr>
<tr><td>Scam scenarios mitigated</td><td class="c">{bad(f"{ev['attacks_stopped']['UNPROTECTED']} of {ev['attack_cases']}")}</td><td class="c">{ok(f"{ev['attacks_stopped']['PROTECTED']} of {ev['attack_cases']}")}</td></tr>
<tr><td>Simulated money paid to attacker accounts</td><td class="c">{bad(f"CNY {ev['money_lost_cny']['UNPROTECTED']:,.0f}")}</td><td class="c">{ok(f"CNY {ev['money_lost_cny']['PROTECTED']:,.0f}")}</td></tr>
<tr><td>Genuine payments completed</td><td class="c">{ev['legit_paid']['UNPROTECTED']} of {ev['legit_cases']}</td><td class="c">{ok(f"{ev['legit_paid']['PROTECTED']} of {ev['legit_cases']}")}</td></tr>
<tr><td>Tampered signed payments refused by the executor</td><td class="c">not applicable</td><td class="c">{ok(f"{ev['executor_blocked']} of {ev['executor_attacks']}")}</td></tr></table>
<p>The split-transfer case (P6) is mitigated rather than fully blocked: the first of three CNY 3,300 transfers, below the approval limit, executed and two were held for the parent. The benchmark's layered run shows where the protection comes from: attack block rate 6.2% for the baseline, 68.8% with registry verification, and 100% once signed intents and policy are added, with legitimate completion 100% throughout. Canaries block nothing extra; they flag 3 attacks earlier.</p>
{fig_money_lost(2)}
<h3>6.2  Live-model path (Amazon Nova Pro, MOCK data)</h3>
<table><tr><th>Check</th><th class="n">Result</th></tr>
<tr><td>Poisoned invoices: model changed the account, amount or payee</td><td class="n">0 of 128</td></tr>
<tr><td>Payments released without a signature, to a non-registry account, money lost</td><td class="n">0 / 0 / 0</td></tr>
<tr><td>Genuine invoices held for the student's signature exactly as offline</td><td class="n">40 of 40</td></tr>
<tr><td>Genuine invoices where the AI scorer raised the score (false escalation)</td><td class="n">0 of 40</td></tr>
<tr><td>AI risk scorer: scored / raised / unusable / malformed JSON salvaged</td><td class="n">168 / 36 / 0 / 2</td></tr>
<tr><td>Outside-written attack sets run through the live path: breaches</td><td class="n">0 of 550 attacks, 0 of 170 look-alikes</td></tr>
<tr><td>Chat labeller: manipulation messages that received a payment label</td><td class="n">1 of 25 as run; 0 of 25 after a validator rule added later (post hoc)</td></tr></table>
<h3>6.3  Task completion under the router</h3>
<p>Security held where completion did not. On 144 fresh paraphrases, before any change, the keyword router placed 52 correctly, 19 on the wrong intent and left 73 unknown; money moved in none. On three outside-written sets the live path completed 96 of 120, 129 of 150 and 140 of 150 tasks, with every attack refused. Wording the router does not know is the weakest measured part of the product, and it costs convenience, not safety.</p>
<p>Two sets written by an outside AI (Codex) from the pitch and the API description alone were run offline. In none of the 330 scenarios did money move. Task completion on unusual wording is the weak spot: 106 of 250 met every expectation on the first run, 86 of the misses being messages the offline keyword router could not place. The live model is meant to cover part of that and has not been measured on these sets.</p>
{fig_outside_sets(3)}
<h3>6.4  Stress and fuzz (offline)</h3>
<p>A generated run of 92,076 chat messages (60,000 attacks across obfuscations) and 29,053 end-to-end conversations found <b>0 hard breaches</b> (no money moved outside the registry, no secret revealed, no unsigned payment, no server error). 65 soft findings (a false refusal or an attack that was not refused) remain; 99.05% of attacks were refused when lossy encodings such as reversed words and leetspeak are excluded. A mutation fuzz of 6,615 messages and 300 random walks found no invariant breach.</p>"""))

    # 7 PQC ---------------------------------------------------------------------------------------------------------
    h.append(sec(7, """<p>Oasis signs every payment with two independent algorithms, one classical and one post-quantum, and requires both. This section states what that gives the project, what was measured in this build, and what it does not cover.</p>
<h3>7.1  What Oasis does</h3>
<table><tr><th style="width:27%">Layer</th><th>Mechanism</th></tr>
<tr><td>Signed payment intents</td><td>Hybrid signature: Ed25519 (classical) and ML-DSA-65 (NIST FIPS 204, post-quantum). Verification passes only if <b>every</b> listed signature is valid.</td></tr>
<tr><td>Other signed records</td><td>The same hybrid signer is used for registry credentials, proof packs, the Trust Pass, the payment-reliability record and the Evidence Passport.</td></tr>
<tr><td>Standalone verification</td><td>Anyone holding the public keys can verify a proof pack with a small verifier and no access to the server.</td></tr>
<tr><td>Transport</td><td>Hybrid post-quantum key exchange X25519MLKEM768 over TLS 1.3, with classical-only clients refused when the proxy is configured that way.</td></tr>
<tr><td>Crypto agility</td><td>The signer takes a list of algorithms. An optional SM2/SM3 signer (the Chinese national standard) was added without changing the executor, and reproduces the standard test vector.</td></tr></table>
<h3>7.2  Why this is a strength</h3>
<ul><li><b>Protects against harvest now, forge later.</b> A signed payment record and its proof pack are meant to be checked for years. Signatures made today with a post-quantum algorithm stay trustworthy if large quantum computers arrive, which Ed25519 alone would not.</li>
<li><b>Belt and braces.</b> Both signatures must verify, so a break in either algorithm alone does not let an attacker forge a payment record. The newer algorithm cannot weaken the proven one.</li>
<li><b>Standard algorithms, no home-made cryptography.</b> ML-DSA-65 is the NIST FIPS 204 standard through a maintained library; Ed25519 is used the same way. The key exchange is the hybrid ML-KEM group built into current browsers and TLS libraries.</li>
<li><b>Security compliance, unauthorized operations.</b> An attacker who strips or forges either signature cannot get a payment executed (Section 7.3: ML-DSA-65 signature removed, refused).</li>
<li><b>Fits the track.</b> A verified payment history is only useful to a lender if it can still be checked later and cannot be re-signed; long-lived records are exactly where post-quantum signatures matter first.</li>
<li><b>Replaceable.</b> Because algorithms are a list, a future scheme can be added or one retired without redesigning the executor or the proof format.</li></ul>
<h3>7.3  Measured in this build (offline, seeded demo keys)</h3>
<table><tr><th>Check</th><th class="n">Result</th></tr>
<tr><td>Signature sizes: Ed25519 / ML-DSA-65</td><td class="n">64 bytes / 3,309 bytes</td></tr>
<tr><td>Public key sizes: Ed25519 / ML-DSA-65</td><td class="n">32 bytes / 1,952 bytes</td></tr>
<tr><td>Honest payment message, both signatures</td><td class="n">""" + ok("verifies") + """</td></tr>
<tr><td>Same signatures, message altered by one character</td><td class="n">""" + ok("refused") + """</td></tr>
<tr><td>Valid Ed25519 signature with the ML-DSA-65 signature removed</td><td class="n">""" + ok("refused") + """</td></tr>
<tr><td>Executor tests: tampered, replayed, expired and forged signed payments</td><td class="n">""" + ok("refused") + """, in the offline suite</td></tr>
<tr><td>Post-quantum TLS handshake: hybrid client / classical-only client</td><td class="n">""" + ok("X25519MLKEM768 negotiated") + """ / """ + ok("refused") + """</td></tr></table>
<p class="small">The signature checks were run for this report on the project's own signer. Handshake evidence is the saved recorded run: Caddy 2.11.7 with an OpenSSL 3.5.9 client, a Go reference server, and Chrome 155.</p>"""))

    # 8 -------------------------------------------------------------------------------------------------------------
    risks = [
        ("High", "Self-written evidence and small live samples; no external audit", "Tests and attack sets were largely written by the team. Three outside AI sets exposed failures that were then fixed, so final scores are not out-of-sample. Live checks used one model and our own texts (128 poisoned and 40 genuine invoices, three outside sets; some sets were not run live), are small samples and are not a robustness claim. Nova calls are not in the Oasis audit chain: saved rows are the record, not a provider-side log. Stress and fuzz runs are white-box, written by the team. No human penetration test or certification.", "Open", "Independent audit, a human red team and larger live runs. The deterministic layers carry the guarantee regardless of model results."),
        ("High", "Everything is simulated", "Rails, rates, fees, the payee registry and the humans in the benchmark are mocks. A compromised or wrong registry would defeat verification.", "Accepted for the sandbox", "Real rails, a licensed partner and a governed registry (Section 9)."),
        ("Medium", "Chat labeller accepted a payment label on a trap", "1 of 25 manipulation messages got a payment label as run. A validator rule now gives 0 of 25, measured after the fact.", "Mitigated (post hoc)", "A payment label only creates a draft for a signature. Re-test on a fresh set."),
        ("Medium", "Keyword router weak on unseen wording", "52 right, 19 wrong, 73 unknown of 144 fresh paraphrases. Security held; task completion suffers.", "Open", "Broaden coverage; consider the optional model label with its validator."),
        ("Medium", "Risk scorers weaker out of sample", "The heuristic was tuned on the benchmark, and neither scorer can see poisoned tool output (0 of 6). The trained model is modest (AUC 0.80 against 0.75).", "Accepted; escalate-only", "Executor and intent binding carry the guarantee. Sequence flags raised split-payment scores to 0.636."),
        ("Medium", "Authentication is demo-grade", "Per-role passcodes, no per-person accounts, no MFA. Device-key enrolment is trust on first use: whoever holds a role's passcode can register a new key, which retires the old one. The login throttle is per address, so it can lock out the real user behind it.", "Open", "Per-user accounts, out-of-band device enrolment or WebAuthn. An optional passkey second factor exists, off by default and untested on a hardware key."),
        ("Medium", "Public virtual machine with a live key", "One small Azure VM behind Caddy and Let's Encrypt, a live model key on a lifetime budget of 3,000,000 tokens with deterministic fallback. Not load-tested; requests run one at a time. SSH exposure and key rotation after judging are still to do.", "Open", "Rotate the key after judging, restrict SSH, load-test and add a second host."),
        ("Medium", "Keys held as local files", "The data key and trust signing key are plaintext files protected by OS permissions unless a passphrase is set; on Windows file mode does not restrict access. Anyone who can read them can decrypt the database.", "Open", "A key vault or hardware module. The judge start scripts set a random passphrase."),
        ("Medium", "Model reading and output failures", "2 of 6 live images failed (an invented payee on a Chinese-language invoice, a runaway value on a blurry one). The provider's filter blocked one answer, and 2 of 168 risk answers were malformed JSON.", "Mitigated; partly open", "A runaway-value guard holds bad readings; the deterministic parse and a salvaged escalate-only score were used. The registry-only payment rule and the student confirming fields limit the harm."),
        ("Low", "First part of a split payment executes", "Splitting is only visible from the second payment, so with three parts of CNY 3,300 against a CNY 3,498 co-approval threshold the first is paid to the student's own registry account and the other two are held (rule R06, no ledger entry). The execution evidence shows this as partly held.", "Accepted by design", "Loss is capped at one below-threshold amount to a registry payee; a test pins the behaviour."),
        ("Low", "Sandbox simplifications", "Converted funds stay in the student's own account if the executor refuses a payment. Draft expiry uses a simulated clock. Signed intents carry floats (ledger balances use exact fen arithmetic). One fixed USD/INR of 88.0 is used in some checks. Demo keys are seeded and public, so a pack forged with them would verify while the demo runs.", "Accepted for the sandbox", "Wall clock, decimal money, a rate service and vault keys in production. The fingerprint endpoint reports demo mode."),
        ("Low", "Post-quantum, anchoring and TLS limits", "The TLS certificate is classical: only the key exchange is post-quantum, so an attacker who can break classical signatures could still impersonate the server. TLS is provided by the proxy; the live-handshake test is skipped by default, the evidence is a recorded manual run (Caddy with OpenSSL 3.5, Chrome 155) and the deployed VM's handshake was not recorded. The approver's own signature is Ed25519 only, protected because the draft is bound inside the hybrid-signed intent. ML-DSA comes from a general-purpose library (the hybrid rule limits a flaw; none found). SM2 uses a pure-Python library that is not constant-time and not audited. The anchor is a local simulation by default; FISCO BCOS is a four-node test chain on one host. No independent cryptographic review has been done.", "Disclosed", "A post-quantum certificate when available, a multi-host chain and an independent cryptographic review."),
        ("Low", "Unvalidated inputs and channels", "Regulatory figures are not confirmed by a bank or counsel, and sanctions screening is one public list. Chinese, Tamil and Hindi text is machine-drafted. We held informal conversations with 10 people we know: 6 international students and interns abroad (Vietnam, Japan, Germany, Spain and Tanzania) and 4 parents: a small convenience sample, not a survey; no finance office was interviewed. Telegram and IMAP were tested only against fake servers.", "Disclosed", "Confirm figures with a dealer bank and counsel, native review, user research and real-account tests."),
    ]
    rr = "".join(f"<tr><td class='n'>{i}</td><td>{SEV[s]}</td><td><b>{e(t)}</b><br>{e(d)}</td><td>{e(st)}</td><td>{e(m)}</td></tr>" for i, (s, t, d, st, m) in enumerate(risks, 1))
    h.append(sec(8, f"""<p>Severity is the authors' judgement of the harm if the risk were exploited in a real deployment, not a score from a standard. Status says what has been done in this build. Findings from earlier adversarial reviews that were fixed (races on approval, non-finite amounts, cross-origin posts, duplicate payment, proof-pack forgery and others) are in Appendix A.</p>
<table class="tight"><tr><th class="n" style="width:4%">#</th><th style="width:10%">Severity</th><th style="width:47%">Risk</th><th style="width:12%">Status</th><th>Mitigation or next step</th></tr>{rr}</table>"""))

    # 8 -------------------------------------------------------------------------------------------------------------
    h.append(sec(9, """<h3>9.1  Out of scope</h3>
<ul><li>Compromise of the host machine or of the signing keys.</li><li>Compromise of the registry itself.</li><li>Real banking integration.</li><li>Production key management.</li><li>Denial of service and load.</li><li>The correctness of regulatory figures beyond the stated research.</li></ul>
<h3>9.2  Path to production</h3>
<table><tr><th style="width:28%">Gap</th><th>What is needed</th></tr>
<tr><td>Licensing and real rails</td><td>A licensed payment partner and real bank integrations. Oasis is a sandbox; it is not a licensed financial service and gives no financial advice.</td></tr>
<tr><td>Independent assurance</td><td>External penetration test and code audit, then a human red team of students, parents and fraud investigators.</td></tr>
<tr><td>Identity and keys</td><td>Per-user accounts, MFA or passkeys, out-of-band device enrolment, and keys held in a vault or hardware module.</td></tr>
<tr><td>Data and compliance</td><td>Counsel-confirmed corridor rules, a governed payee registry, privacy review for personal data, and decimal money end to end.</td></tr>
<tr><td>Operations</td><td>Load testing, a second host, rotated and scoped credentials, monitoring and an incident process.</td></tr></table>"""))

    # appendices ------------------------------------------------------------------------------------------------------
    hist = [("Round 1", "Role guards and signed one-hour sessions", "Least privilege per role; 401 and 403 behaviour; failed-login limit."),
            ("Round 2", "Device-key approvals", "Ed25519 over the exact draft hash, keys kept in the approver's browser."),
            ("Round 3", "Encryption at rest", "AES-256-GCM per payload column with row-bound data; hash chain re-verified after decrypt."),
            ("Round 4", "Short-lived tool tokens", "30-second, single-use token bound to the intent; the baseline keeps a static credential on purpose."),
            ("Round 5", "Judge review fixes", "Serialised requests and atomic audit appends (approval race); non-finite and fractional-fen amounts refused; strict request models; Origin check and body cap; risk hold no longer offers an approval that cannot release it; expired drafts retired with 410; proof verification never raises; duplicate-payment rule R17; text caps; clear key-file errors."),
            ("Round 6", "Proof-pack forgery found by external review", "Verification now pins the server's key fingerprint and checks the anchor and chain."),
            ("Round 7", "Security headers, passkey second factor, inbound channel rules, sanctions screening, zero-knowledge threshold proofs", "Content-Security-Policy and related headers; optional WebAuthn; email and chat provenance as evidence only; OFAC list snapshot raising review."),
            ("Round 8", "Chat tasks", "Deterministic intent router with security categories first; payments built from the registry, never from text; audited refusals and a redaction filter; corrections void the old draft; over-the-bill refusal."),
            ("Round 9", "Live evidence rounds", "Large live invoice, chat and outside-set runs with a token cap; vision guard; tolerant JSON parsing; lifetime token budget."),
            ("Round 10", "Sequence flags and FlightPath", "Payment-burst, third-payment and large-amount flags raise risk (escalate only); recovery advice never resends; why-cards state uncertainty; rewrite guard.")]
    ht = "".join(f"<tr><td style='white-space:nowrap'>{d}</td><td><b>{e(t)}</b><br>{e(x)}</td></tr>" for d, t, x in hist)
    h.append(f'<section class="s"><h2 id="A1">Appendix A.&nbsp; {APPENDICES[0]}</h2><p>Dated hardening rounds, replacing the earlier review log. Each change has a regression test.</p><table class="tight"><tr><th>Round</th><th>Change</th></tr>{ht}</table></section>')
    h.append(f"""<section class="s"><h2 id="A2">Appendix B.&nbsp; {APPENDICES[1]}</h2>
<p>All commands run offline and make no model call. Run them from the repository root.</p>
<table class="tight"><tr><th style="width:34%">Purpose</th><th>Command</th></tr>
<tr><td>Offline test suite (expect 1766 passed, 2 skipped)</td><td><code>OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. python -m pytest -q</code></td></tr>
<tr><td>Role matrix only</td><td><code>OASIS_LLM=offline PYTHONPATH=. python -m pytest -q tests/test_role_matrix.py</code></td></tr>
<tr><td>Offline benchmark</td><td><code>OASIS_LLM=offline PYTHONPATH=. python -m eval.runner --llm offline</code></td></tr>
<tr><td>Rebuild this report</td><td><code>PYTHONPATH=. python -m eval.build_security_pdf</code></td></tr></table>
<p class="small">Live-model results are saved report rows; reproducing them needs the owner's approval and a capped key.</p></section>""")
    gl = [("Audit chain", "A log in which each entry contains the hash of the previous one, so any later change is detectable."),
          ("Canary", "A decoy credential or account no honest request would touch; using it signals an attack."),
          ("Device-key approval", "A signature made with the approver's registered device key over the exact payment draft."),
          ("Executor", "The only component that moves money; it enforces the signed intent exactly."),
          ("Intent", "A signed record of one exact payment: payee, account, amount, currency, route, nonce and expiry."),
          ("MOCK", "Simulated data. Not real."),
          ("Nonce", "A value that may be used once; reuse indicates a replay."),
          ("Registry", "The list of verified payees and their accounts. Money goes only to a registry account."),
          ("Validator", "Deterministic code that checks everything the model proposes before it is used."),
          ("Tier", "Autonomy level: 1 the agent acts alone within bounds, 2 a human approves, 3 never (freeze).")]
    h.append(f'<section class="s"><h2 id="A3">Appendix C.&nbsp; {APPENDICES[2]}</h2><table><tr><th style="width:26%">Term</th><th>Meaning</th></tr>'
             + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in gl) + "</table></section></body></html>")
    return "".join(h)


def page_map(pdf: Path) -> dict[str, int]:
    from pypdf import PdfReader
    found: dict[str, int] = {}
    for n, pg in enumerate(PdfReader(str(pdf)).pages, 1):
        if n <= 2:
            continue
        flat = re.sub(r"\s+", " ", pg.extract_text() or "")
        for k, t in enumerate(SECTIONS, 1):
            if re.search(rf"(^| ){k}\.\s*{re.escape(t)}", flat) and f"S{k}" not in found:
                found[f"S{k}"] = n
        for k, t in enumerate(APPENDICES, 1):
            if re.search(rf"Appendix {chr(64 + k)}\.\s*{re.escape(t)}", flat) and f"A{k}" not in found:
                found[f"A{k}"] = n
    return found


def main() -> Path:
    probe = {f"S{k}": 99 for k in range(1, len(SECTIONS) + 1)} | {f"A{k}": 99 for k in range(1, len(APPENDICES) + 1)}
    print_pdf(build(probe), OUT)
    pages = page_map(OUT)
    print_pdf(build(pages), OUT)
    from pypdf import PdfReader
    print(f"wrote {OUT.name}: {len(PdfReader(str(OUT)).pages)} pages; sections at {pages}")
    return OUT


if __name__ == "__main__":
    main()
