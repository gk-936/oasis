import React, { useCallback, useEffect, useState } from "react";
import { api, useGuard } from "../api.js";
import { t } from "../i18n/index.js";
import { announce, ErrorBox, fmtDate, Loading, Mock, Pill } from "../ui.jsx";

/* Credit growth: plan, opportunities, what-if. Read-only guidance over the Trust Pass record; never a score or a lender prediction. */
const missingText = (m) => t(`cg.missing.${m.code}`, { type: m.type ? t(`type.${m.type}`) : "", have: m.have ?? 0, need: m.need ?? 0 });

export function CreditGrowth() {
  const [plan, setPlan] = useState(null);
  const [opps, setOpps] = useState(null);
  const [sim, setSim] = useState(null);
  const [form, setForm] = useState({ on_time_months: 6, late_payments: 0, starter_product: false, budget_safe: true });
  const { busy, err, setErr, run } = useGuard();
  const load = useCallback(() => Promise.all([api("/credit-growth/plan"), api("/credit-growth/opportunities")])
    .then(([p, o]) => { setPlan(p); setOpps(o); }).catch(setErr), [setErr]);
  useEffect(() => { load(); }, [load]);
  const go = () => run(async () => { setSim(await api("/credit-growth/simulate", form)); announce(t("cg.announce")); });
  if (!plan || !opps) return <div className="card"><h3>{t("cg.title")}</h3>{err ? <ErrorBox error={err} onRetry={load} /> : <Loading />}</div>;
  const v = plan.verified;
  return (
    <div className="card wide" data-testid="credit-growth">
      <div className="hd"><h3>{t("cg.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p>{t("cg.pitch")}</p>

      <h4>{t("cg.plan")}</h4>
      <p className="muted small">{t("cg.verified", { n: v.payments, on: v.on_time, m: v.months, s: v.streak })}</p>
      <ul className="feed" data-testid="cg-milestones">{plan.milestones.map((m) => (
        <li key={m.id}>{m.met ? "✓" : "○"} {t(`cg.m.${m.id}`)} <span className="muted small">({m.current}/{m.target}){m.id === plan.next ? ` · ${t("cg.next")}` : ""}</span></li>))}</ul>
      {plan.upcoming_obligations.length > 0 && <>
        <p className="muted small">{t("cg.upcoming")}</p>
        <ul className="feed">{plan.upcoming_obligations.map((o) => <li key={o.id}>{t(`type.${o.type}`)} · {fmtDate(o.due)}</li>)}</ul>
      </>}
      <p className="muted small">{t("cg.notverified")} {plan.not_verified.map((k) => t(`cg.nv.${k}`)).join(", ")}.</p>

      <h4>{t("cg.opps")}</h4>
      <ul className="feed" data-testid="cg-opps">{opps.opportunities.map((o) => (
        <li key={o.id}><b>{t(`cg.opp.${o.id}`)}</b> {o.ready ? <Pill status="verified">{t("cg.ready")}</Pill> : <Pill status="pending">{t("cg.notyet")}</Pill>}
          {o.ready
            ? <div className="muted small">{t("cg.evidence", { claims: o.package.claims.map((c) => t(`cg.claim.${c}`)).join(", ") })}{" "}
                <button className="ghost" onClick={() => window.dispatchEvent(new CustomEvent("oasis:tp-prefill", { detail: o.package }))} data-testid={`cg-use-${o.id}`}>{t("cg.use")}</button></div>
            : <ul className="feed">{o.missing.map((m, i) => <li key={i} className="muted small">{missingText(m)}</li>)}</ul>}</li>))}</ul>
      <p className="muted small">{t("cg.noguarantee")}</p>

      <h4>{t("cg.sim")}</h4>
      <div className="row">
        <label>{t("cg.sim.months")}<input type="number" min={0} max={24} value={form.on_time_months} onChange={(e) => setForm({ ...form, on_time_months: +e.target.value })} data-testid="cg-months" /></label>
        <label>{t("cg.sim.late")}<input type="number" min={0} max={6} value={form.late_payments} onChange={(e) => setForm({ ...form, late_payments: +e.target.value })} data-testid="cg-late" /></label>
        <label className="check"><input type="checkbox" checked={form.starter_product} onChange={(e) => setForm({ ...form, starter_product: e.target.checked })} /> {t("cg.sim.starter")}</label>
        <label className="check"><input type="checkbox" checked={form.budget_safe} onChange={(e) => setForm({ ...form, budget_safe: e.target.checked })} /> {t("cg.sim.budget")}</label>
        <button disabled={busy} onClick={go} style={{ alignSelf: "flex-end" }} data-testid="cg-run">{t("cg.sim.run")}</button>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {sim && <div data-testid="cg-sim">
        <p><Pill status="pending">{t("cg.hypo")}</Pill></p>
        <p>{t("cg.sim.streak", { a: sim.before.claims.on_time_streak.count, b: sim.after.claims.on_time_streak.count })} · {t("cg.sim.level", { a: sim.before.ladder_level, b: sim.after.ladder_level })}</p>
        {sim.gained_asks.length > 0 && <ul className="feed">{sim.gained_asks.map((a) => <li key={a}>＋ {t(`cp.ask.${a}`)}</li>)}</ul>}
        {sim.lost_asks.length > 0 && <ul className="feed">{sim.lost_asks.map((a) => <li key={a}>－ {t(`cp.ask.${a}`)}</li>)}</ul>}
        {sim.notes.length > 0 && <ul className="feed">{sim.notes.map((n) => <li key={n} className="muted small">{t(`cg.note.${n}`)}</li>)}</ul>}
      </div>}
      <ul className="feed muted small">{plan.caveats.map((_, i) => <li key={i}>{t(`cg.caveat.${i + 1}`)}</li>)}</ul>
    </div>
  );
}
