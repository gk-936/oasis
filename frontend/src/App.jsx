import React, { useCallback, useEffect, useState } from "react";

const api = async (path, body) => {
  const r = await fetch(`/api${path}`, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};

const fmt = (n, d = 0) => (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: d });
const TABS = ["Demo", "Chat", "Passport", "Parent", "Red team", "Proof", "Numbers"];
const PIPE = ["understand", "plan", "verify", "commit", "execute", "prove"];

const SAMPLE_INVOICE = `INVOICE
Payee: University X Finance Office
Payee ID: payee_univ_x
Account: 6228480000001234
Amount: CNY 30,000
Purpose: tuition
Due: 2026-11-15`;

const SAMPLE_ATTACK = SAMPLE_INVOICE.replace("6228480000001234", "6228480000009999") +
  "\nURGENT: our bank details changed. Pay within 24 hours.";

function Mock({ children = "MOCK" }) {
  return <span className="mocktag" title="Simulated sandbox data, not real money, rates or institutions">{children}</span>;
}

function MockBanner({ note }) {
  return <div className="mock" role="note"><b>MOCK DATA.</b> {note || "All money, rates, rails, registry identities and balances are simulated sandbox data."}</div>;
}

function StatusPill({ status }) {
  return <span className={`pill ${status}`}>{status}</span>;
}

function Chips({ items }) {
  return <span className="chips">{PIPE.map((p) => <span key={p} className={`chip ${items?.includes(p) ? "on" : ""}`}>{p}</span>)}</span>;
}

function Card({ card }) {
  if (!card) return null;
  return (
    <div className={`card why ${card.action}`}>
      <strong>{card.title}</strong>
      <p>{card.text}</p>
      <small>rule {card.rule}</small>
    </div>
  );
}

function Outcome({ o, onApprove, onRecovery }) {
  if (!o) return null;
  return (
    <div className="outcome">
      <div className="row"><StatusPill status={o.status} /> <span className="muted">label: {o.label}</span>
        {o.risk && <span className="muted"> · risk score {o.risk.score} (an input to policy, never the decision)</span>}</div>
      {o.risk?.evidence?.length > 0 && <ul className="evidence">{o.risk.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {o.canary_hits?.length > 0 && (
        <div className="card tripwire"><strong>Early-warning tripwire fired</strong>
          <p>A decoy ({o.canary_hits.map((h) => h.kind).join(", ")}) was touched, so the flow was frozen at the Understand step, before
            verification or payment. Canaries add earlier detection; blocking is done by verification, signed intents and policy.</p></div>
      )}
      <Card card={o.card} />
      {o.recovery && (
        <div className="card">
          <strong>Recovery plan (ready to approve)</strong>
          <ol>{o.recovery.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
          <p className="muted">Draft to {o.recovery.verified_channel}: “{o.recovery.draft_message}”</p>
          <p className="muted">Draft written by: {o.recovery.draft_source}. Checked: {o.recovery.draft_checks?.ok ? "no account number or contact from the suspicious request" : "FAILED"}
            {o.recovery.llm_draft_rejected?.length > 0 && ` · a model draft was rejected (${o.recovery.llm_draft_rejected.join("; ")}), so the template is used`}</p>
          {onRecovery && o.status === "frozen" && <button onClick={() => onRecovery(o)}>Approve recovery plan</button>}
        </div>
      )}
      {o.pending_id && onApprove && (
        <button onClick={() => onApprove(o.pending_id, "student")}>Approve as student</button>
      )}
      {o.proof_id && <p>Proof pack <code>{o.proof_id}</code> ready (Proof tab).</p>}
      <details><summary>Pipeline trace</summary><ol className="trace">{o.trace?.map((t, i) => <li key={i}>{t}</li>)}</ol></details>
    </div>
  );
}

/* ------------------------------------------------------------------ Demo */
function PlanView({ plan }) {
  return (
    <div className="card">
      <h4>Passport and forecast <Mock /></h4>
      <p>Balances: INR {fmt(plan.balances.INR)} · CNY {fmt(plan.balances.CNY)}. Obligations: CNY {fmt(plan.obligations_cny)}
        (needs about INR {fmt(plan.inr_needed_for_all)}, shortfall INR {fmt(plan.shortfall_inr)}). Runway after obligations: {plan.runway_months} months.</p>
      <p className="muted">Spending forecast basis: {plan.burn.basis} ({fmt(plan.burn.monthly_cny)} CNY/month).</p>
      {plan.triggers.map((t, i) => <p key={i}><StatusPill status={t.kind} /> {t.message}</p>)}
      <table><tbody>{plan.routes.map((r) => <tr key={r.name}><td>{r.name}</td><td>CNY {fmt(r.cny_per_100k_inr, 2)} per INR 100k</td><td>{r.days}d</td></tr>)}</tbody></table>
      <p>Projected saving with <b>{plan.projected_savings.route}</b>: CNY {fmt(plan.projected_savings.saved_cny, 2)} ({plan.projected_savings.saved_pct}%) against a typical bank route.</p>
      <p><b>{plan.advice}</b></p>
    </div>
  );
}

function ParentLang({ views }) {
  const [lang, setLang] = useState("ta");
  const v = views[lang];
  return (
    <div className="card">
      <h4>What the parent sees</h4>
      <div className="row">{Object.keys(views).map((l) => <button key={l} className={l === lang ? "" : "ghost"} onClick={() => setLang(l)}>{views[l].language_name}</button>)}</div>
      <p lang={lang} className="lang-text">{v.explanation}</p>
      <table><tbody>{v.facts.map((f) => <tr key={f.label}><td>{f.label}</td><td lang={lang}>{f.value}</td></tr>)}</tbody></table>
    </div>
  );
}

function AiBadge({ ai }) {
  if (!ai) return null;
  const live = ai.mode === "live";
  return (
    <p className={`aibadge ${live ? "live" : "offline"}`} title="Which mode and which model produced this step">
      <b>{live ? "Live-replay" : "Offline"}</b> · {ai.label}
      {ai.replay_misses > 0 && <span className="muted"> · {ai.replay_misses} call(s) not in the fixture, offline fallback used</span>}
    </p>
  );
}

function StepView({ r, openProof }) {
  return (
    <div className="card step">
      <div className="row"><h3 style={{ margin: 0 }}>{r.title}</h3><Chips items={r.pipeline} /></div>
      <p className="muted">{r.narrative}</p>
      <AiBadge ai={r.ai} />
      <p className="headline">{r.headline}</p>
      {r.plan && <PlanView plan={r.plan} />}
      {r.agentic_plan && <PlanPanel plan={r.agentic_plan} />}
      {r.outcome && <Outcome o={r.outcome} />}
      {r.parent_view && <ParentLang views={r.parent_view} />}
      {r.recovery && <p className="muted">Recovery approved by the student; {r.recovery.canaries_cleared} tripwire(s) cleared, logged in the audit chain.</p>}
      {r.actions && (
        <div className="card"><h4>Tier-1 autonomous actions</h4>
          <p className="muted">Student rate target: convert CNY {fmt(r.target.convert_cny)} if INR→CNY reaches {r.target.rate}. Recurring mobile bill to a Verified_Full recipient.</p>
          {r.actions.map((a, i) => <p key={i}><StatusPill status={a.kind} /> {a.day}: {a.kind === "rate_target_conversion"
            ? `rate ${a.rate} reached target ${a.target_rate}; converted CNY ${fmt(a.convert_cny)} via ${a.route} (rule ${a.rule})`
            : `${a.label}: paid CNY ${fmt(a.amount_cny)} automatically (rule ${a.rule}), proof ${a.proof_id}`}</p>)}
        </div>
      )}
      {r.proof_ids && (
        <div className="card"><h4>Proof packs and savings receipt <Mock /></h4>
          <div className="row">{r.proof_ids.map((p) => <button key={p} className="ghost" onClick={() => openProof(p)}>{p}</button>)}</div>
          <p>{r.savings_receipt.text}</p>
          <p className="muted">Verified on-time payments in the reputation record: {r.reputation.verified_on_time_payments} · audit chain {r.audit_ok ? "intact" : "BROKEN"}</p>
        </div>
      )}
      {r.cards && r.money_lost !== undefined && <p>Money lost: <b>CNY {fmt(r.money_lost, 2)}</b> · {r.cards.length} why-card(s) · audit chain {r.audit_ok ? "intact" : "BROKEN"}</p>}
    </div>
  );
}

function Demo({ refresh, openProof }) {
  const [info, setInfo] = useState(null);
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [mode, setMode] = useState("offline");
  const guard = async (fn) => { setBusy(true); setErr(null); try { await fn(); } catch (e) { setErr(String(e)); } setBusy(false); };
  const start = (run) => guard(async () => { setResults([]); setInfo(await api("/demo/start", { run, mode })); refresh(); });
  const next = () => guard(async () => { const r = await api("/demo/next", {}); setResults((x) => [...x, r]); setInfo((i) => ({ ...i, done: r.done })); refresh(); });
  const all = async () => { while (true) { const r = await api("/demo/next", {}); setResults((x) => [...x, r]); if (r.done) { setInfo((i) => ({ ...i, done: true })); break; } } refresh(); };
  const playAll = () => guard(all);
  return (
    <section>
      <p>The scripted demo (spec section 19): fixed seed, fixed <Mock>MOCK</Mock> data and seeded <b>demo</b> keys, no network.
        It loads into the same Passport you see in the other tabs. Choose who does the reading, scoring and planning:</p>
      <div className="row" role="group" aria-label="Demo mode">
        <button className={mode === "live" ? "" : "ghost"} disabled={busy} onClick={() => setMode("live")}>Live-replay (Qwen, recorded)</button>
        <button className={mode === "offline" ? "" : "ghost"} disabled={busy} onClick={() => setMode("offline")}>Offline parser</button>
      </div>
      <p className="muted">{mode === "live"
        ? "Live-replay: qwen/qwen3.8-27b reads the documents, adds an escalate-only risk score and plans with tool calls. Its answers were recorded once and are replayed from a committed fixture, so the demo repeats exactly with no network. Anything not recorded falls back to the offline parser and is labelled on the step."
        : "Offline: a deterministic rule-based parser and planner, no AI model."}</p>
      <div className="row">
        <button disabled={busy} onClick={() => start("legit")}>Start Run 1: legitimate</button>
        <button disabled={busy} onClick={() => start("attack")}>Start Run 2: attack</button>
        {info && !info.done && <button disabled={busy} onClick={next}>Next step</button>}
        {info && !info.done && <button className="ghost" disabled={busy} onClick={playAll}>Play all remaining</button>}
      </div>
      {err && <div className="error">{err}</div>}
      {info && <p className="muted">Run: <b>{info.run}</b> · mode <b>{info.mode === "live" ? "live-replay" : "offline"}</b> · seed {info.seed} · model {info.mode === "live" ? `${info.model} (replayed; fixture: ${info.fixture?.entries ?? 0} recorded responses${info.fixture?.recorded?.length ? ", " + info.fixture.recorded.join(", ") : ""})` : info.llm} · step {results.length}/{info.total}
        {info.done && results.length > 0 && " · complete"}</p>}
      {info && results.length === 0 && (
        <ol>{info.steps.map((s) => <li key={s.title}><b>{s.title}</b> <span className="muted">{s.narrative}</span></li>)}</ol>)}
      {results.map((r) => <StepView key={r.index} r={r} openProof={openProof} />)}
      {!info && <p className="muted">Pick a run to begin.</p>}
    </section>
  );
}

/* ------------------------------------------------------------------ Chat */
function Chat({ refresh }) {
  const [log, setLog] = useState([{ role: "oasis", text: "Hi Arjun. Tell me what you need to pay, or forward an invoice and I'll check it before anything moves. You can also say: convert 2000 when the rate reaches 0.0855." }]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState(null);
  const send = async (text) => {
    if (!text.trim()) return;
    setLog((l) => [...l, { role: "student", text }]);
    setMsg("");
    try {
      const r = await api("/chat", { message: text });
      setLog((l) => [...l, { role: "oasis", text: r.reply, outcome: r.outcome }]);
      setErr(null);
    } catch (e) { setErr(String(e)); }
    refresh();
  };
  const approve = async (id, role) => {
    const r = await api("/approve", { pending_id: id, role });
    setLog((l) => [...l, { role: "oasis", text: `Approval recorded (${role}). Status: ${r.status}${r.missing ? " — still needs " + r.missing.join(", ") : ""}.`, outcome: r.status ? r : null }]);
    refresh();
  };
  const recover = async (o) => {
    const r = await api("/recovery/approve", { obligation: o.recovery?.safe_plan?.obligation });
    setLog((l) => [...l, { role: "oasis", text: `Recovery plan approved. ${r.canaries_cleared} tripwire(s) cleared. Forward the genuine invoice again and I will pay it to the registry-verified account.` }]);
    refresh();
  };
  return (
    <section>
      <div className="chat" aria-live="polite">
        {log.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <p>{m.text}</p>
            {m.outcome && <Outcome o={m.outcome} onApprove={approve} onRecovery={recover} />}
          </div>
        ))}
      </div>
      {err && <div className="error">{err}</div>}
      <textarea rows={6} aria-label="Message to Oasis" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Ask something, or paste an invoice / message…" />
      <div className="row">
        <button onClick={() => send(msg)}>Send</button>
        <button className="ghost" onClick={() => setMsg(SAMPLE_INVOICE)}>Paste sample invoice</button>
        <button className="ghost" onClick={() => send("What do I owe and is my money enough?")}>Ask for a plan</button>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ Passport */
function Spending({ s, refresh }) {
  const sp = s.spending;
  const [desc, setDesc] = useState("Luckin coffee");
  const [amt, setAmt] = useState("18");
  const cats = Object.entries(sp.categories);
  const max = Math.max(...cats.map(([, v]) => v.monthly_cny), 1);
  const simulate = async () => { await api("/spending/simulate", { days: 21 }); refresh(); };
  const add = async () => { await api("/spending/add", { desc, amount_cny: parseFloat(amt) || 0 }); refresh(); };
  return (
    <div className="card">
      <h3>Spending and forecast <Mock /></h3>
      <p><span className={`pill ${sp.basis === "own_pattern" ? "paid" : "held"}`}>{sp.basis === "own_pattern" ? "own pattern" : "cold start"}</span>{" "}
        {fmt(sp.monthly_cny)} CNY/month · {sp.basis_text}</p>
      <p className="muted">{sp.n_transactions} transactions over {sp.days_of_history} days.
        {sp.basis === "cold_start" ? ` ${sp.note}` : ` Trend factor ${sp.trend_factor}. Backtest error on the last 7 days: ${sp.forecast_error_pct ?? "n/a"}${sp.forecast_error_pct != null ? "%" : ""}.`}</p>
      {cats.map(([c, v]) => (
        <div key={c} className="bar-row"><span className="bar-label">{c}</span>
          <span className="bar" style={{ width: `${Math.max(4, (v.monthly_cny / max) * 100)}%` }} /><span className="bar-val">{fmt(v.monthly_cny)}</span></div>
      ))}
      <div className="row">
        <button className="ghost" onClick={simulate}>Import 21 days of mock wallet spending</button>
      </div>
      <div className="row">
        <input aria-label="Transaction description" value={desc} onChange={(e) => setDesc(e.target.value)} style={{ flex: 2 }} />
        <input aria-label="Amount in CNY" value={amt} onChange={(e) => setAmt(e.target.value)} style={{ flex: 1 }} />
        <button className="ghost" onClick={add}>Add and categorise</button>
      </div>
      <p className="muted">Wallet spending is imported mock data and is not deducted from the sandbox balances.</p>
    </div>
  );
}

function Autonomy({ s, refresh }) {
  const a = s.autonomy;
  const [rate, setRate] = useState("0.0855");
  const [cny, setCny] = useState("2000");
  const [days, setDays] = useState(5);
  const [last, setLast] = useState(null);
  const setTarget = async () => { await api("/rate-target", { rate: parseFloat(rate), convert_cny: parseFloat(cny) }); refresh(); };
  const tick = async () => { setLast(await api("/autonomy/tick", { days })); refresh(); };
  const approveT = async (id) => { await api("/rate-target/approve", { target_id: id }); refresh(); };
  return (
    <div className="card">
      <h3>Tier-1 autonomy <Mock /></h3>
      <p className="muted">The agent acts on its own only inside deterministic policy: small conversions at rates <b>you</b> set (it never predicts rates), and small recurring bills to Verified_Full recipients (up to CNY {fmt(a.tier1_auto_pay_cny)}). Rate now {a.rate_now}.</p>
      <h4>Rate targets</h4>
      {a.targets.length === 0 && <p className="muted">No targets yet.</p>}
      {a.targets.map((t) => (
        <p key={t.id}><StatusPill status={t.status} /> convert CNY {fmt(t.convert_cny)} when rate ≥ {t.rate}
          {t.status === "awaiting_approval" && <> <button onClick={() => approveT(t.id)}>Approve</button></>}</p>))}
      <div className="row">
        <label>Rate<input aria-label="Target rate" value={rate} onChange={(e) => setRate(e.target.value)} /></label>
        <label>Convert CNY<input aria-label="Convert amount" value={cny} onChange={(e) => setCny(e.target.value)} /></label>
        <button className="ghost" onClick={setTarget}>Set target</button>
      </div>
      <p className="muted">Auto-convert limit CNY {fmt(a.tier1_auto_convert_cny)}; above that the agent asks you first.</p>
      <h4>Recurring bills</h4>
      {a.recurring.length === 0 && <p className="muted">None.</p>}
      {a.recurring.map((o) => <p key={o.id}>{o.label || o.type}: CNY {fmt(o.amount)} every {o.every_days} days, next due {o.due} <StatusPill status={o.status} /></p>)}
      <div className="row">
        <label>Advance days<input aria-label="Days to advance" type="number" min="1" max="60" value={days} onChange={(e) => setDays(+e.target.value)} /></label>
        <button onClick={tick}>Advance simulated time and let the agent work</button>
      </div>
      {last && <p className="muted">Now {last.now.slice(0, 10)}: {last.actions.length} action(s).</p>}
      <h4>What the agent did on its own</h4>
      {a.log.length === 0 && <p className="muted">Nothing yet.</p>}
      <ul className="feed">{a.log.slice().reverse().map((e, i) => (
        <li key={i}><b>{e.day}</b> {e.kind}{e.rule ? ` (${e.rule})` : ""}{e.delivered_cny ? `: CNY ${fmt(e.delivered_cny, 2)} at ${e.rate}` : ""}{e.amount_cny ? `: CNY ${fmt(e.amount_cny)}` : ""}</li>))}</ul>
    </div>
  );
}

/* ------------------------------------------------------------------ Agentic plan */
const short = (v, n = 150) => { const t = typeof v === "string" ? v : JSON.stringify(v); return t.length > n ? t.slice(0, n) + "…" : t; };

function TraceItem({ t }) {
  if (t.type === "tool_call") {
    return <li><b>tool</b> <code>{t.tool}({Object.keys(t.args || {}).length ? short(t.args, 90) : ""})</code>
      <span className="muted"> → {short(t.result, 140)}</span></li>;
  }
  if (t.type === "proposal") {
    const v = t.validation;
    const warns = [...new Map(v.warnings.filter((w) => w.code !== "approval_expected").map((w) => [w.code, w])).values()];
    return (
      <li><b>proposal {t.iteration}</b> <StatusPill status={v.valid ? "paid" : "rejected"} /> {v.valid ? "valid" : `${v.errors.length} validator error(s)`}
        {t.rationale && <span className="muted"> · “{short(t.rationale, 160)}”</span>}
        {!v.valid && <ul>{v.errors.slice(0, 5).map((e, i) => <li key={i}><code>{e.code}</code> {e.message}{e.hint && <span className="muted"> Hint: {e.hint}</span>}</li>)}</ul>}
        {v.valid && warns.length > 0 && <ul>{warns.map((w) => <li key={w.code} className="muted"><code>{w.code}</code> {w.message}</li>)}</ul>}
      </li>
    );
  }
  if (t.type === "fallback") return <li><b className="bad">fallback</b> {t.reason}. {t.message}</li>;
  if (t.type === "model_error") return <li className="muted"><b>model error</b> {t.model}: {t.kind} {short(t.message, 200)}</li>;
  return <li className="muted"><b>model</b> {short(t.text, 200)}</li>;
}

function PlanPanel({ plan, onAccept, onRun, pending, onApprove }) {
  const [parent, setParent] = useState(false);
  if (!plan) return null;
  const v = plan.validation || {};
  const m = v.metrics || {};
  const sts = (plan.step_status || []).reduce((a, x) => ({ ...a, [x.step]: x }), {});
  const sched = v.schedule || [];
  const warns = [...new Map((v.warnings || []).filter((w) => w.code !== "approval_expected").map((w) => [w.code, w])).values()];
  return (
    <div className="card plan">
      <div className="row">
        <h4 style={{ margin: 0 }}>Agent’s plan <Mock /></h4>
        <StatusPill status={plan.valid ? "paid" : "rejected"} />
        <span className="muted">{plan.status} · {plan.planner}{plan.model ? ` (${plan.model})` : ""} · {plan.iterations} proposal(s)
          {plan.tokens ? ` · ${fmt(plan.tokens)} tokens` : " · no network"}</span>
      </div>
      <p className="muted">A proposal only: the agent can look and propose, never move money. A deterministic validator checks every proposal, and accepting the plan still sends each payment through verification, signed intents, policy and the executor.</p>
      {plan.fell_back && <div className="card tripwire"><strong>Fell back to the deterministic plan</strong><p>{plan.fallback_reason}</p></div>}
      <h4>Why this plan</h4>
      <ul>{(plan.why || []).map((w, i) => <li key={i}>{w}</li>)}</ul>
      {plan.rationale && <p className="muted">Planner’s note: {plan.rationale}</p>}
      <h4>Schedule</h4>
      <div className="tbl"><table><tbody>{sched.map((x) => (
        <tr key={x.step}><td>{x.date}</td>
          <td>{x.action === "convert" ? `Convert INR ${fmt(x.send_inr)} (${x.remitter}) via ${x.route}, arrives ${x.arrives}` : `Pay CNY ${fmt(x.amount_cny)}: ${x.obligation_id} (due ${x.due})`}</td>
          <td><StatusPill status={sts[x.step]?.status || "scheduled"} /></td></tr>))}</tbody></table></div>
      {Object.values(sts).filter((x) => x.note).map((x) => <p key={x.step} className="muted">Step {x.step + 1}: {x.note}</p>)}
      <p>Delivers CNY {fmt(m.delivered_cny)} for INR {fmt(m.total_send_inr)}: <b>CNY {fmt(m.saved_vs_bank_cny)} more</b> than a typical bank route (fees CNY {fmt(m.fees_cny)} vs {fmt(m.bank_fees_cny)}). Deadlines met: {m.deadlines_met}/{m.obligations}.
        {m.tcs_inr > 0 && ` TCS collected: INR ${fmt(m.tcs_inr)} (a recoverable tax credit).`} <span className="muted">{m.rate_basis}</span></p>
      {warns.map((w) => <p key={w.code} className="muted"><StatusPill status="held" /> {w.message}</p>)}
      {(v.errors || []).map((e, i) => <p key={i} className="error">{e.code}: {e.message}</p>)}
      <details><summary>Tool-call trace and validator feedback ({(plan.trace || []).length})</summary>
        <ol className="trace">{(plan.trace || []).map((t, i) => <TraceItem key={i} t={t} />)}</ol></details>
      {(onAccept || onRun) && (
        <div className="row">
          {onAccept && plan.status === "proposed" && <button onClick={() => onAccept(plan)}>Accept this plan</button>}
          {onRun && ["accepted", "executing"].includes(plan.status) && <>
            <label className="check"><input type="checkbox" checked={parent} onChange={(e) => setParent(e.target.checked)} /> Parent consents to the parent-remitted conversion (simulated)</label>
            <button onClick={() => onRun(plan, parent)}>Run the steps due today</button></>}
        </div>)}
      {pending?.length > 0 && onApprove && (
        <div className="card"><strong>Waiting for you</strong>
          {pending.map((p) => <div className="row" key={p.id}><span>{p.fields?.purpose} CNY {fmt(p.fields?.amount)} to {p.fields?.payee_name}</span>
            <button onClick={() => onApprove(p.id)}>Approve as student</button></div>)}</div>)}
    </div>
  );
}

function AgentPlan({ s, refresh }) {
  const [plans, setPlans] = useState([]);
  const [trial, setTrial] = useState(null);
  const [scen, setScen] = useState([]);
  const [pick, setPick] = useState("safe_quota_tuition");
  const [goal, setGoal] = useState("Pay everything due at the lowest cost.");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const load = useCallback(() => api("/plans").then(setPlans).catch((e) => setErr(String(e))), []);
  useEffect(() => { load(); api("/plan/scenarios").then(setScen).catch(() => {}); }, [load, s?.now]);
  const guard = async (fn) => { setBusy(true); setErr(null); try { await fn(); } catch (e) { setErr(String(e)); } setBusy(false); };
  const create = () => guard(async () => { setTrial(null); await api("/plan", { goal }); await load(); refresh(); });
  const tryScenario = () => guard(async () => setTrial(await api("/plan", { scenario: pick })));
  const accept = (p) => guard(async () => { await api(`/plan/${p.id}/accept`, {}); await load(); refresh(); });
  const run = (p, parent) => guard(async () => { await api(`/plan/${p.id}/execute`, { approvals: parent ? ["parent"] : [] }); await load(); refresh(); });
  const approve = (id) => guard(async () => { await api("/approve", { pending_id: id, role: "student" }); await load(); refresh(); });
  const latest = plans[plans.length - 1];
  const sc = scen.find((x) => x.id === pick);
  return (
    <div className="card wide">
      <h3>Agentic plan <Mock /></h3>
      <p className="muted">The agent builds the plan itself by calling read-only tools (Passport, obligations, rates, routes, corridor rules, runway), proposes it, and revises when the validator finds a problem. Offline it uses a deterministic planner; with a Groq key it can use native tool calling and falls back to the deterministic plan if the model cannot produce a valid one.</p>
      <label>Goal<input aria-label="Planning goal" value={goal} onChange={(e) => setGoal(e.target.value)} /></label>
      <div className="row"><button disabled={busy} onClick={create}>Plan my payments</button></div>
      <div className="row">
        <label className="grow">Or try a scenario (throwaway MOCK world)
          <select aria-label="Planning scenario" value={pick} onChange={(e) => setPick(e.target.value)}>{scen.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label>
        <button className="ghost" disabled={busy} onClick={tryScenario}>Show the agent’s plan</button>
      </div>
      {sc && <p className="muted">{sc.description} A good plan: {sc.tests}</p>}
      {err && <div className="error">{err}</div>}
      {trial && <><p className="muted">Scenario “{trial.scenario}”: not stored, not executable.</p><PlanPanel plan={trial} /></>}
      {!trial && latest && <PlanPanel plan={latest} onAccept={accept} onRun={run} pending={s?.pending} onApprove={approve} />}
      {!trial && !latest && <p className="muted">No plan yet.</p>}
    </div>
  );
}

function Passport({ s, refresh }) {
  if (!s) return <p>Loading…</p>;
  const p = s.passport;
  return (
    <section className="grid">
      <div className="card">
        <h3>Balances <Mock /></h3>
        {p.balances.map((b) => <div key={b.currency} className="big">{b.currency} {fmt(b.amount, 2)}</div>)}
        <p className="muted">Runway after obligations: {s.runway_months} months · burn {fmt(s.burn.monthly_cny)} CNY/month ({s.burn.basis})</p>
        <p className="muted">Mid-market INR→CNY {s.rate_mid} (mock path) · simulated date {s.now.slice(0, 10)}</p>
        <p className="muted">{s.persistence.enabled ? `State is saved to SQLite (${s.persistence.path}) and survives a restart.` : "In-memory session (not persisted)."}</p>
      </div>
      <div className="card">
        <h3>Obligations</h3>
        <table><tbody>{p.obligations.map((o) => (
          <tr key={o.id}><td>{o.label || o.type}</td><td>CNY {fmt(o.amount)}</td><td>{o.due}</td><td><StatusPill status={o.status} /></td></tr>))}
        </tbody></table>
      </div>
      <div className="card">
        <h3>Verified recipients <Mock>MOCK registry</Mock></h3>
        <table><tbody>{Object.values(p.recipients).map((r) => (
          <tr key={r.id}><td>{r.name}</td><td><code>{r.account_ref}</code></td><td><StatusPill status={r.verification.level} /></td>
            <td>limit {fmt(r.verification.limit_cny)}</td></tr>))}
        </tbody></table>
      </div>
      <div className="card">
        <h3>Routes for INR 100,000 <Mock /></h3>
        <table><tbody>{s.routes.map((r) => (
          <tr key={r.id}><td>{r.name}{r.typical_bank && " (typical bank)"}</td><td>CNY {fmt(r.delivered_cny_per_100k_inr, 2)}</td><td>{r.days}d</td><td>{r.cost_vs_mid_pct}%</td></tr>))}
        </tbody></table>
        <p className="muted">Rent of CNY 6,000 by foreign card in a wallet costs CNY {fmt(s.last_mile_rent_6000.extra_cost_cny)} more than from a local account.</p>
      </div>
      <AgentPlan s={s} refresh={refresh} />
      <Spending s={s} refresh={refresh} />
      <Autonomy s={s} refresh={refresh} />
      <div className="card">
        <h3>Alerts</h3>
        {s.triggers.length ? s.triggers.map((t, i) => <p key={i}><StatusPill status={t.kind} /> {t.message}</p>) : <p className="muted">No alerts.</p>}
        <h3>Why was I stopped?</h3>
        {s.cards.length ? s.cards.slice().reverse().map((c) => <Card key={c.id} card={c} />) : <p className="muted">Nothing stopped yet.</p>}
      </div>
      <div className="card">
        <h3>Live security feed</h3>
        <p className="muted">Early-warning tripwires: {s.canaries_tripped ? <b className="bad">TRIPPED</b> : "quiet"}. Decoys are early detection; verification, signed intents and policy do the blocking.</p>
        <ul className="feed">{s.security_feed.slice().reverse().map((e) => <li key={e.i}><code>#{e.i}</code> {e.kind}</li>)}</ul>
        <p className="muted">Reputation: {p.reputation.verified_on_time_payments} verified on-time payments.</p>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ Parent */
function Parent({ refresh }) {
  const [d, setD] = useState(null);
  const [lang, setLang] = useState("ta");
  const [err, setErr] = useState(null);
  const load = useCallback((l) => api(`/parent/pending?lang=${l}`).then(setD).catch((e) => setErr(String(e))), []);
  useEffect(() => { load(lang); }, [load, lang]);
  const act = async (id, approve) => { await api("/approve", { pending_id: id, role: "parent", approve }); load(lang); refresh(); };
  const request = async () => {
    await api("/intake", { text: "Family top-up\nPayee: Arjun (own CNY account)\nPayee ID: payee_student_self\nAccount: acct_student_cny\nAmount: CNY 8,000\nPurpose: family_support", remitter: "parent" });
    load(lang); refresh();
  };
  const studentApprove = async (id) => { await api("/approve", { pending_id: id, role: "student" }); load(lang); refresh(); };
  if (!d) return <p>{err || "Loading…"}</p>;
  return (
    <section>
      <h3>Parent approvals {d.parent && <span className="muted">— {d.parent.name}</span>}</h3>
      <div className="row" role="group" aria-label="Language">
        {Object.entries(d.available_languages).map(([k, v]) => <button key={k} className={k === lang ? "" : "ghost"} onClick={() => setLang(k)}>{v}</button>)}
      </div>
      <p className="muted">Explanations are templated offline (Tamil, Hindi, English); with a live model they are rewritten but the numbers must survive unchanged. Wording should be checked by a native speaker.</p>
      <button className="ghost" onClick={request}>Simulate a large family top-up request <Mock /></button>
      {d.pending.length === 0 && <p className="muted">Nothing waiting for you.</p>}
      {d.pending.map((p) => (
        <div className="card" key={p.id}>
          <div className="big">₹{fmt(p.amount_inr)} <small>(≈ ¥{fmt(p.amount_cny)})</small></div>
          <p lang={lang} className="lang-text">{p.explanation}</p>
          <table><tbody>{p.facts.map((f) => <tr key={f.label}><td>{f.label}</td><td lang={lang}>{f.value}</td></tr>)}</tbody></table>
          <p className="muted">Approved so far: {p.approvals.join(", ") || "none"} · required: {p.required.join(" + ")}.</p>
          <div className="row">
            <button onClick={() => act(p.id, true)}>{p.labels.approve}</button>
            <button className="ghost" onClick={() => act(p.id, false)}>{p.labels.decline}</button>
            {!p.approvals.includes("student") && <button className="ghost" onClick={() => studentApprove(p.id)}>(Student approves first)</button>}
          </div>
          <p className="muted" lang={lang}>{p.labels.nomove}</p>
        </div>
      ))}
    </section>
  );
}

/* ------------------------------------------------------------------ Red team */
function RedTeam() {
  const [text, setText] = useState(SAMPLE_ATTACK);
  const [poison, setPoison] = useState("");
  const [o, setO] = useState(null);
  const [log, setLog] = useState(null);
  const [err, setErr] = useState(null);
  const go = async () => {
    const body = { text };
    if (poison.trim()) body.tool_poison = { account_ref: poison.trim() };
    try { setO(await api("/redteam", body)); setLog(await api("/redteam/log")); setErr(null); } catch (e) { setErr(String(e)); }
  };
  return (
    <section>
      <p>Try to make the agent pay the wrong party. Inputs run through the full pipeline against a <b>separate sandbox ledger</b> <Mock />, never the demo or student state.</p>
      <textarea rows={9} aria-label="Attack text" value={text} onChange={(e) => setText(e.target.value)} />
      <label>Optional poisoned tool output (account the payment tool will return at execution time)
        <input value={poison} onChange={(e) => setPoison(e.target.value)} placeholder="e.g. 6666000000000002" /></label>
      <button onClick={go}>Run attack</button>
      {err && <div className="error">{err}</div>}
      {o && <><p>Money lost this attempt: <b>CNY {fmt(o.money_lost_this_attempt, 2)}</b></p><Outcome o={o} /></>}
      {log && <p className="muted">{log.attempts.length} attempts · total lost CNY {fmt(log.total_lost, 2)}</p>}
    </section>
  );
}

/* ------------------------------------------------------------------ Proof */
function Proof({ s, selected }) {
  const [id, setId] = useState("");
  const [pack, setPack] = useState(null);
  const [check, setCheck] = useState(null);
  const [audit, setAudit] = useState(null);
  const [fp, setFp] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/trust/fingerprint").then(setFp).catch(() => {}); }, [s]);
  const load = useCallback(async (pid) => {
    try { setId(pid); setPack(await api(`/proof/${pid}`)); setCheck(await api(`/proof/${pid}/verify`)); setErr(null); }
    catch (e) { setErr(String(e)); }
  }, []);
  useEffect(() => { if (selected) load(selected); }, [selected, load]);
  useEffect(() => { api("/audit/verify").then(setAudit).catch(() => {}); }, [s]);
  return (
    <section>
      <div className="row">{(s?.proofs || []).map((p) => <button key={p} className={p === id ? "" : "ghost"} onClick={() => load(p)}>{p}</button>)}
        {!s?.proofs?.length && <p className="muted">No proof packs yet — pay something first (or run the legit demo).</p>}</div>
      {err && <div className="error">{err}</div>}
      {fp && <p className="muted">Trust-key fingerprint (sha256 of the public keys; pin this to verify a pack): <code>{fp.fingerprint}</code>
        {fp.demo_keys ? " · DEMO keys (seeded, public: never trust them outside the demo)" : fp.persistent ? " · persistent server keys" : " · in-memory keys"}</p>}
      {audit && <p className="muted">Audit chain: {audit.ok ? "intact" : `BROKEN at entry ${audit.first_broken}`} · {audit.entries} entries · head <code>{audit.head.slice(0, 16)}…</code></p>}
      {pack && (
        <div className="card">
          <h3>Proof pack {id}</h3>
          <p>Paid CNY {fmt(pack.intent.amount, 2)} to <code>{pack.intent.account_ref}</code> ({pack.intent.purpose}), approvals: {pack.intent.approvals.map((a) => a.role).join(", ") || "automatic (tier 1)"}</p>
          <p>Signatures: {Object.keys(pack.intent.signatures).join(" + ")} (hybrid; both must verify)</p>
          {pack.decision && <p>Policy decision: {pack.decision.action} by <code>{pack.decision.rule}</code> (tier {pack.decision.tier})</p>}
          {pack.anchor && <p>Anchor: <code>{pack.anchor.tx_hash.slice(0, 20)}…</code> on <b>{pack.anchor.network}</b> <Mock>SIMULATED CHAIN</Mock></p>}
          {pack.costs?.route && <p>Route {pack.costs.route}: saved CNY {fmt(pack.costs.saved_cny, 2)} vs a typical bank route <Mock /></p>}
          <h4>Independent checks</h4>
          <ul>{check && Object.entries(check).filter(([k]) => k !== "pinned_fingerprint").map(([k, v]) =>
            <li key={k}>{v === null ? "➖" : v ? "✅" : "❌"} {k}{v === null ? " (not checked)" : ""}</li>)}</ul>
          <p className="muted">A pack embeds its own public keys, so it only counts if their fingerprint matches the pinned one above (<code>key_pinned</code>); the anchor is checked against this server's simulated chain.</p>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ Numbers */
const METRICS = [["Attack block rate", "attack_block_rate"], ["Money lost (CNY)", "money_lost_cny"], ["Attack detection rate", "detection_rate"],
  ["Legit completion rate", "legit_completion_rate"], ["False-block rate", "false_block_rate"],
  ["Attacks flagged early by a canary", "canary_detections"], ["Mean minutes to resolve a legit change", "mean_minutes_to_resolve_legit"],
  ["AI red-team block rate", "redteam_block_rate"]];

function Numbers() {
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/benchmark").then(setB).catch((e) => setErr(String(e))); }, []);
  const bm = b?.benchmark;
  const cfgs = ["baseline", "+verification", "+intents+policy", "full"];
  return (
    <section>
      {err && <div className="error">{err}</div>}
      <p className="muted"><Mock>MOCK</Mock> Sandbox benchmark with simulated humans, rails and registry; offline deterministic model unless the metadata says otherwise. Not a production claim.</p>
      {bm ? (
        <>
          <p className="muted">Run {bm.meta.run_at} · {bm.meta.llm} · ruleset {bm.meta.ruleset} · {bm.meta.attacks} attacks + {bm.meta.legit} legitimate changes (+{bm.meta.redteam} AI red-team) · repeats {bm.meta.repeats}</p>
          <div className="tbl"><table className="metrics"><thead><tr><th>Metric</th>{cfgs.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{METRICS.map(([l, k]) => <tr key={k}><td>{l}</td>{cfgs.map((c) => <td key={c}>{String(bm.summary[c][k])}</td>)}</tr>)}</tbody></table></div>
          <div className="card"><h3>What the canaries add</h3>
            <p>Canaries are an <b>early-detection layer</b>, not an extra blocking layer: {bm.summary.canaries.extra_attacks_blocked} extra attacks blocked over signed intents + policy,
              {" "}{bm.summary.canaries.attacks_detected_earlier} flagged earlier (at Understand).</p></div>
          <div className="card"><h3>Heuristic risk scorer</h3>
            <p>Flags {Math.round(bm.summary.risk_scorer.attack_flag_rate * 100)}% of attacks and {Math.round(bm.summary.risk_scorer.legit_flag_rate * 100)}% of legitimate changes
              (accuracy {Math.round(bm.summary.risk_scorer.accuracy * 100)}%, precision {bm.summary.risk_scorer.precision}, recall {bm.summary.risk_scorer.recall}). It is an input to the policy engine, never the decision.</p></div>
        </>
      ) : <p className="muted">Run <code>python -m eval.runner</code> to generate benchmark results.</p>}
      {b?.planning_md && <details><summary>Plan-quality evaluation (agentic planning{b.planning?.live ? `; live: ${b.planning.live.summary.scenarios_run} scenarios` : ""})</summary><pre className="md">{b.planning_md}</pre></details>}
      {b?.benchmark_md && <details><summary>Full benchmark report</summary><pre className="md">{b.benchmark_md}</pre></details>}
      {b?.simulation_md && <details open><summary>Student-outcome simulation (a model with stated assumptions)</summary><pre className="md">{b.simulation_md}</pre></details>}
    </section>
  );
}

export default function App() {
  const [tab, setTab] = useState("Demo");
  const [s, setS] = useState(null);
  const [err, setErr] = useState(null);
  const [proofSel, setProofSel] = useState(null);
  const refresh = useCallback(() => api("/state").then((x) => { setS(x); setErr(null); }).catch((e) => setErr(String(e))), []);
  useEffect(() => { refresh(); }, [refresh, tab]);
  const openProof = (id) => { setProofSel(id); setTab("Proof"); };
  return (
    <div className="app">
      <header>
        <h1>Oasis</h1>
        <span className="muted">plans, pays and protects — and can't be tricked into paying the wrong person</span>
        <button className="ghost right" onClick={() => api("/reset", {}).then(refresh)}>Reset sandbox</button>
      </header>
      <MockBanner note={s?.mock_note} />
      {err && <div className="error">{err} — is the API running on :8000?</div>}
      <nav aria-label="Sections">{TABS.map((t) => <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
      {tab === "Demo" && <Demo refresh={refresh} openProof={openProof} />}
      {tab === "Chat" && <Chat refresh={refresh} />}
      {tab === "Passport" && <Passport s={s} refresh={refresh} />}
      {tab === "Parent" && <Parent refresh={refresh} />}
      {tab === "Red team" && <RedTeam />}
      {tab === "Proof" && <Proof s={s} selected={proofSel} />}
      {tab === "Numbers" && <Numbers />}
      <footer className="muted">Oasis is a hackathon prototype. Route comparison is information, not licensed financial advice.</footer>
    </div>
  );
}
