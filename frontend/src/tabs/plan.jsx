import React, { useCallback, useEffect, useState } from "react";
import { api, signedApprove, short4, useGuard } from "../api.js";
import { Card } from "../common.jsx";
import { t, tl, tm, tp, useLang } from "../i18n/index.js";
import { announce, approvable, cny, Empty, ErrorBox, fmt, fmtDate, inr, Loading, Mock, Pill, R, Skeleton } from "../ui.jsx";

const short = (v, n = 150) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s.length > n ? s.slice(0, n) + "…" : s; };

function TraceItem({ x }) {
  if (x.type === "tool_call") {
    return <li><b>{t("trace.tool")}</b> <code>{x.tool}({Object.keys(x.args || {}).length ? short(x.args, 90) : ""})</code>
      <span className="muted"> → {short(x.result, 140)}</span></li>;
  }
  if (x.type === "proposal") {
    const v = x.validation;
    const warns = [...new Map(v.warnings.filter((w) => w.code !== "approval_expected").map((w) => [w.code, w])).values()];
    return (
      <li><b>{t("trace.proposal", { n: x.iteration })}</b> <Pill status={v.valid ? "paid" : "rejected"}>{v.valid ? t("status.valid") : tp("trace.errors", v.errors.length)}</Pill>
        {x.rationale && <span className="muted"> · “{short(x.rationale, 160)}”</span>}
        {!v.valid && <ul>{v.errors.slice(0, 5).map((e, i) => <li key={i}><code>{e.code}</code> {e.message}{e.hint && <span className="muted"> {t("trace.hint", { hint: e.hint })}</span>}</li>)}</ul>}
        {v.valid && warns.length > 0 && <ul>{warns.map((w) => <li key={w.code} className="muted"><code>{w.code}</code> {w.message}</li>)}</ul>}
      </li>
    );
  }
  if (x.type === "fallback") return <li><b className="bad">{t("trace.fallback")}</b> {x.reason}. {x.message}</li>;
  if (x.type === "model_error") return <li className="muted"><b>{t("trace.modelerror")}</b> {x.model}: {x.kind} {short(x.message, 200)}</li>;
  return <li className="muted"><b>{t("trace.model")}</b> {short(x.text, 200)}</li>;
}

export function PlanPanel({ plan, onAccept, onRun, pending, onApprove, busy }) {
  if (!plan) return null;
  const v = plan.validation || {};
  const m = v.metrics || {};
  const sts = (plan.step_status || []).reduce((a, x) => ({ ...a, [x.step]: x }), {});
  const sched = v.schedule || [];
  const warns = [...new Map((v.warnings || []).filter((w) => w.code !== "approval_expected").map((w) => [w.code, w])).values()];
  const waiting = pending?.filter((p) => approvable(p.required)) || [];
  return (
    <div className="card inner plan">
      <div className="hd">
        <h4 style={{ margin: 0 }}>{t("plan.title")}</h4><Mock />
        <Pill status={plan.valid ? "paid" : "rejected"}>{plan.valid ? t("status.valid") : t("status.invalid")}</Pill>
        <span className="muted small">{tl("status", plan.status)} · {tm(plan.planner)}{plan.model ? ` (${plan.model})` : ""} · {tp("plan.proposals", plan.iterations)}
          {plan.tokens ? ` · ${t("plan.tokens", { n: fmt(plan.tokens) })}` : ` · ${t("plan.nonet")}`}</span>
      </div>
      <p className="muted">{t("plan.intro")}</p>
      {plan.fell_back && <div className="card inner tripwire"><strong>{t("plan.fellback")}</strong><p>{plan.fallback_reason}</p></div>}
      <h4>{t("plan.why")}</h4>
      <ul>{(plan.why || []).map((w, i) => <li key={i}>{w}</li>)}</ul>
      {plan.rationale && <p className="muted">{t("plan.note", { note: plan.rationale })}</p>}
      <h4>{t("plan.schedule")}</h4>
      <div className="tbl"><table aria-label={t("plan.schedule.aria")}><tbody>{sched.map((x) => (
        <tr key={x.step}><td>{fmtDate(x.date)}</td>
          <td>{x.action === "convert"
            ? t("plan.sched.convert", { inr: inr(x.send_inr), remitter: tl("role", x.remitter), route: tm(x.route), date: fmtDate(x.arrives) })
            : t("plan.sched.pay", { amount: cny(x.amount_cny), id: x.obligation_id, due: fmtDate(x.due) })}</td>
          <td><Pill status={sts[x.step]?.status || "scheduled"} /></td></tr>))}</tbody></table></div>
      {Object.values(sts).filter((x) => x.note).map((x) => <p key={x.step} className="muted">{t("plan.step.note", { n: x.step + 1, note: x.note })}</p>)}
      <p>{R("plan.delivers", { cny: cny(m.delivered_cny), inr: inr(m.total_send_inr), more: cny(m.saved_vs_bank_cny), fees: cny(m.fees_cny), bank: cny(m.bank_fees_cny), met: m.deadlines_met, total: m.obligations })}
        {m.tcs_inr > 0 && ` ${t("plan.tcs", { inr: inr(m.tcs_inr) })}`} <span className="muted">{m.rate_basis}</span></p>
      {warns.map((w) => <p key={w.code} className="muted"><Pill status="held" /> {w.message}</p>)}
      {(v.errors || []).map((e, i) => <p key={i} className="bad">{e.code}: {e.message}</p>)}
      <details><summary>{t("plan.trace", { n: (plan.trace || []).length })}</summary>
        <ol className="trace">{(plan.trace || []).map((x, i) => <TraceItem key={i} x={x} />)}</ol></details>
      {(onAccept || onRun) && (
        <div className="row">
          {onAccept && plan.status === "proposed" && <button disabled={busy} onClick={() => onAccept(plan)}>{t("plan.accept")}</button>}
          {onRun && ["accepted", "executing"].includes(plan.status) && <button disabled={busy} onClick={() => onRun(plan)}>{t("plan.run")}</button>}
        </div>)}
      {plan.parent_consents?.length > 0 && (
        <div className="card inner"><strong>{t("plan.consent.title")}</strong>
          {plan.parent_consents.map((c) => (
            <p key={c.step} className="muted">{t("plan.consent.line", { n: c.step + 1, inr: inr(c.send_inr), date: fmtDate(c.date) })}{" "}
              {c.signed_by ? <span className="sigtag">✔ {t("signed.by", { role: tl("role", "parent") })} <code>{short4(c.signed_by)}</code></span>
                : t("plan.consent.waiting")}</p>))}
        </div>)}
      {waiting.length > 0 && onApprove && (
        <div className="card inner"><strong>{t("plan.waiting")}</strong>
          {waiting.map((p) => <div className="row" key={p.id}><span>{tl("purpose", p.fields?.purpose)} <b className="money">{cny(p.fields?.amount)}</b> {t("out.to", { payee: p.fields?.payee_name })}</span>
            <button disabled={busy} onClick={() => onApprove(p)}>{t("plan.approve")}</button></div>)}</div>)}
    </div>
  );
}

export function AgentPlan({ s, refresh }) {
  const { lang } = useLang();
  const [plans, setPlans] = useState(null);
  const [trial, setTrial] = useState(null);
  const [scen, setScen] = useState([]);
  const [pick, setPick] = useState("safe_quota_tuition");
  const [goalEdit, setGoalEdit] = useState(null);       // null = the default goal in the current language
  const { busy, err, setErr, run } = useGuard();
  const goal = goalEdit ?? t("plan.goal.default");
  const load = useCallback(() => api("/plans").then((p) => { setPlans(p); setErr(null); }).catch((e) => { setPlans((x) => x || []); setErr(e); }), [setErr]);
  useEffect(() => { load(); api("/plan/scenarios").then(setScen).catch(() => {}); }, [load, s?.now, lang]);
  const create = () => run(async () => { setTrial(null); await api("/plan", { goal }); await load(); announce(t("plan.created")); refresh(); });
  const tryScenario = () => run(async () => setTrial(await api("/plan", { scenario: pick })));
  const accept = (p) => run(async () => { await api(`/plan/${p.id}/accept`, {}); await load(); refresh(); });
  const exec = (p) => run(async () => { await api(`/plan/${p.id}/execute`, {}); await load(); refresh(); });
  const approve = (pd) => run(async () => { await signedApprove("student", pd.id, pd.draft); await load(); refresh(); });
  const latest = plans?.filter((x) => x.kind !== "fx").slice(-1)[0];
  const sc = scen.find((x) => x.id === pick);
  return (
    <div className="card wide">
      <div className="hd"><h3>{t("plan.agentic.title")}</h3><Mock /></div>
      <p className="muted">{t("plan.agentic.intro")}</p>
      <label>{t("plan.goal")}<input value={goal} onChange={(e) => setGoalEdit(e.target.value)} /></label>
      <div className="row"><button disabled={busy} onClick={create}>{t("plan.create")}</button>{busy && <Loading>{t("plan.planning")}</Loading>}</div>
      <div className="row">
        <label className="grow">{t("plan.scenario.label")}
          <select value={pick} onChange={(e) => setPick(e.target.value)}>{scen.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}</select></label>
        <button className="ghost" disabled={busy || !scen.length} onClick={tryScenario} style={{ alignSelf: "flex-end" }}>{t("plan.scenario.show")}</button>
      </div>
      {sc && <p className="muted">{t("plan.scenario.line", { description: sc.description, tests: sc.tests })}</p>}
      <ErrorBox error={err} onRetry={load} onDismiss={() => setErr(null)} />
      {trial && <><p className="muted">{t("plan.scenario.trial", { name: trial.scenario })}</p><PlanPanel plan={trial} /></>}
      {!trial && latest && <PlanPanel plan={latest} onAccept={accept} onRun={exec} pending={s?.pending} onApprove={approve} busy={busy} />}
      {!trial && plans === null && <Skeleton rows={3} />}
      {!trial && plans && !latest && <Empty title={t("plan.empty.title")}>{t("plan.empty.text")}</Empty>}
    </div>
  );
}
