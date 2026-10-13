import React, { useCallback, useEffect, useState } from "react";
import { api, signedApprove, useGuard } from "../api.js";
import { t, tl, tm } from "../i18n/index.js";
import { announce, ErrorBox, fmt, fmtDate, Loading, Mock, Pill } from "../ui.jsx";

/* Pay a bill owed in USD or EUR: add a MOCK bill, let the agent plan it over the extra corridors, accept, run, and sign each payment. */
const SYM = { USD: "$", EUR: "€", INR: "₹", CNY: "¥" };
const money = (cur, n, d = 2) => `${SYM[cur] || ""}${fmt(n, d)}`;

export function FxPlan({ s, refresh }) {
  const [plans, setPlans] = useState(null);
  const [kind, setKind] = useState("us");
  const [amount, setAmount] = useState(5000);
  const { busy, err, setErr, run } = useGuard();
  const load = useCallback(() => api("/plans").then((p) => { setPlans(p.filter((x) => x.kind === "fx")); setErr(null); }).catch((e) => { setPlans((x) => x || []); setErr(e); }), [setErr]);
  useEffect(() => { load(); }, [load, s?.now]);
  const bills = (s?.passport?.obligations || []).filter((o) => o.currency && o.currency !== "CNY" && o.status !== "paid");
  const latest = plans?.[plans.length - 1];
  const addBill = () => run(async () => { await api("/fx/demo-obligation", { kind, amount: +amount, days: 38 }); announce(t("fxp.added")); refresh(); });
  const plan = () => run(async () => { await api("/plan/fx", {}); await load(); announce(t("fxp.planned")); refresh(); });
  const accept = (p) => run(async () => { await api(`/plan/${p.id}/accept`, {}); await load(); refresh(); });
  const exec = (p) => run(async () => { await api(`/plan/${p.id}/execute`, {}); await load(); refresh(); });
  const approve = (pd) => run(async () => { await signedApprove("student", pd.id, pd.draft); await load(); refresh(); });
  const sts = (latest?.step_status || []).reduce((a, x) => ({ ...a, [x.step]: x }), {});
  const sched = latest?.validation?.schedule || [];
  const m = latest?.validation?.metrics || {};
  const waiting = (s?.pending || []).filter((p) => p.fields?.currency && p.fields.currency !== "CNY");
  return (
    <div className="card wide" data-testid="fx-plan">
      <div className="hd"><h3>{t("fxp.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p className="muted small">{t("fxp.intro")}</p>
      <div className="row">
        <label>{t("fxp.kind")}<select value={kind} onChange={(e) => setKind(e.target.value)} data-testid="fxp-kind"><option value="us">{t("fxp.kind.us")}</option><option value="eu">{t("fxp.kind.eu")}</option></select></label>
        <label>{t("fxp.amount")}<input type="number" min={1} max={100000} value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="fxp-amount" /></label>
        <button className="ghost" disabled={busy || !(+amount > 0)} onClick={addBill} style={{ alignSelf: "flex-end" }} data-testid="fxp-add">{t("fxp.add")}</button>
      </div>
      {bills.length > 0 && <ul className="feed" data-testid="fxp-bills">{bills.map((o) => <li key={o.id}>{tl("type", o.type)} · <b className="money">{money(o.currency, o.remaining ?? o.amount - (o.amount_paid || 0))}</b> · {fmtDate(o.due)}</li>)}</ul>}
      <div className="row"><button disabled={busy || bills.length === 0} onClick={plan} data-testid="fxp-plan">{t("fxp.plan")}</button>{busy && <Loading>{t("plan.planning")}</Loading>}</div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {latest && <div className="card inner" data-testid="fxp-latest">
        <div className="hd"><h4 style={{ margin: 0 }}>{t("plan.title")}</h4>
          <Pill status={latest.valid ? "paid" : "rejected"}>{latest.valid ? t("status.valid") : t("status.invalid")}</Pill>
          <span className="muted small">{tl("status", latest.status)} · {tm(latest.planner)}</span></div>
        <ul>{(latest.why || []).map((w, i) => <li key={i}>{w}</li>)}</ul>
        <div className="tbl"><table aria-label={t("plan.schedule.aria")}><tbody>{sched.map((x) => (
          <tr key={x.step}><td>{fmtDate(x.date)}</td>
            <td>{x.action === "convert"
              ? t("fxp.sched.convert", { send: money(x.currency, x.send, 0), to: money(x.delivered_currency, x.delivered_worst_case, 0), route: tm(x.route), status: t(`co.price.${x.price_status}`), date: fmtDate(x.arrives) })
              : t("fxp.sched.pay", { amount: money(x.currency, x.amount), id: x.obligation_id, due: fmtDate(x.due) })}</td>
            <td><Pill status={sts[x.step]?.status || "scheduled"} /></td></tr>))}</tbody></table></div>
        {Object.values(sts).filter((x) => x.note).map((x) => <p key={x.step} className="muted">{t("plan.step.note", { n: x.step + 1, note: x.note })}</p>)}
        {(latest.validation?.errors || []).map((e, i) => <p key={i} className="bad">{e.code}: {e.message}</p>)}
        <p className="muted small">{m.rate_basis}</p>
        <div className="row">
          {latest.status === "proposed" && <button disabled={busy} onClick={() => accept(latest)} data-testid="fxp-accept">{t("plan.accept")}</button>}
          {["accepted", "executing"].includes(latest.status) && <button disabled={busy} onClick={() => exec(latest)} data-testid="fxp-run">{t("plan.run")}</button>}
        </div>
        {waiting.length > 0 && <div className="card inner"><strong>{t("plan.waiting")}</strong>
          {waiting.map((p) => <div className="row" key={p.id}><span>{tl("purpose", p.fields?.purpose)} <b className="money">{money(p.fields.currency, p.fields.amount)}</b> {t("out.to", { payee: p.fields?.payee_name })}</span>
            <button disabled={busy} onClick={() => approve(p)} data-testid="fxp-approve">{t("plan.approve")}</button></div>)}</div>}
      </div>}
    </div>
  );
}
