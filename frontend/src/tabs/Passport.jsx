import React, { useCallback, useEffect, useState } from "react";
import { api, downloadPdf, useGuard } from "../api.js";
import { esc, kpis, section, table } from "../reports.js";
import { Card, RateBadge } from "../common.jsx";
import { has, t, tl, tm, tp, useLang } from "../i18n/index.js";
import { announce, cny, Empty, ErrorBox, fmt, fmtDate, Hash, inr, Loading, Mock, pct, Pill, R, Skeleton, SubNav } from "../ui.jsx";
import { AgentPlan } from "./plan.jsx";
import { TrustPass } from "./trustpass.jsx";
import { CreditGrowth } from "./CreditGrowth.jsx";
import { FxPlan } from "./FxPlan.jsx";

/* ------------------------------------------------------------------ Spending + Tier-1 autonomy */
export function Spending({ s, refresh }) {
  const sp = s.spending;
  const [desc, setDesc] = useState("Luckin coffee");
  const [amt, setAmt] = useState("18");
  const { busy, err, setErr, run } = useGuard();
  const cats = Object.entries(sp.categories);
  const max = Math.max(...cats.map(([, v]) => v.monthly_cny), 1);
  const simulate = () => run(async () => { await api("/spending/simulate", { days: 21 }); announce(t("spend.announce.import")); refresh(); });
  const add = () => run(async () => { await api("/spending/add", { desc, amount_cny: parseFloat(amt) || 0 }); announce(t("spend.announce.add")); refresh(); });
  return (
    <div className="card pp-card spend">
      <div className="hd"><h3>{t("spend.title")}</h3><Mock /></div>
      <div className="spend-kpis">
        <div><span>{t("spend.kpi.monthly")}</span><b>{cny(sp.monthly_cny)}</b><small>{sp.basis === "own_pattern" ? t("spend.own") : t("spend.cold")}</small></div>
        <div><span>{t("spend.kpi.trend")}</span><b>{sp.basis === "cold_start" ? t("misc.na") : `×${sp.trend_factor}`}</b><small>{sp.basis_text}</small></div>
        <div><span>{t("spend.kpi.error")}</span><b>{sp.forecast_error_pct != null ? `${sp.forecast_error_pct}%` : t("misc.na")}</b><small>{t("spend.kpi.error.sub")}</small></div>
        <div><span>{t("spend.kpi.runway")}</span><b>{s.runway_months != null ? t("home.months", { n: s.runway_months }) : t("misc.na")}</b><small>{tp("spend.tx", sp.n_transactions, { d: sp.days_of_history })}</small></div>
      </div>
      {sp.basis === "cold_start" && sp.note && <p className="muted small">{sp.note}</p>}
      {cats.length === 0 && <Empty title={t("spend.empty.title")}>{t("spend.empty.text")}</Empty>}
      {cats.map(([c, v]) => (
        <div key={c} className="bar-row"><span className="bar-label">{tl("cat", c)}</span>
          <span className="bar-track" role="img" aria-label={t("spend.bar.aria", { cat: tl("cat", c), amount: cny(v.monthly_cny) })}><span className="bar" style={{ width: `${Math.max(4, (v.monthly_cny / max) * 100)}%` }} /></span>
          <span className="bar-val">{cny(v.monthly_cny)}</span></div>
      ))}
      <div className="row"><button className="ghost" disabled={busy} onClick={simulate}>{t("spend.import")}</button></div>
      <div className="row">
        <label className="grow" style={{ flex: "2 1 180px" }}>{t("spend.desc")}<input value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
        <label style={{ flex: "1 1 100px" }}>{t("spend.amount")}<input inputMode="decimal" value={amt} onChange={(e) => setAmt(e.target.value)} /></label>
        <button className="ghost" disabled={busy} onClick={add} style={{ alignSelf: "flex-end" }}>{t("spend.add")}</button>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      <p className="muted small">{t("spend.note")}</p>
    </div>
  );
}

function Autonomy({ s, refresh }) {
  const a = s.autonomy;
  const [rate, setRate] = useState("0.0700");
  const [amount, setAmount] = useState("2000");
  const [days, setDays] = useState(5);
  const [last, setLast] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const setTarget = () => run(async () => { await api("/rate-target", { rate: parseFloat(rate), convert_cny: parseFloat(amount) }); refresh(); });
  const tick = () => run(async () => { const r = await api("/autonomy/tick", { days }); setLast(r); announce(t("auto.announce", { n: r.actions.length })); refresh(); });
  const approveT = (id) => run(async () => { await api("/rate-target/approve", { target_id: id }); refresh(); });
  return (
    <div className="card">
      <div className="hd"><h3>{t("auto.title")}</h3><Mock /></div>
      <p className="muted">{R("auto.intro", { limit: cny(a.tier1_auto_pay_cny) })}</p>
      <p>{R("auto.rate", { rate: a.rate_now })} <RateBadge rates={s.rates} rate={a.rate_now} /></p>
      <h4>{t("auto.targets")}</h4>
      {a.targets.length === 0 && <p className="muted">{t("auto.targets.none")}</p>}
      {a.targets.map((x) => (
        <p key={x.id}><Pill status={x.status} /> {t("auto.target.line", { amount: cny(x.convert_cny), rate: x.rate })}
          {x.status === "awaiting_approval" && <> <button disabled={busy} onClick={() => approveT(x.id)}>{t("auto.approve")}</button></>}</p>))}
      <div className="row">
        <label style={{ flex: "1 1 110px" }}>{t("auto.rate.label")}<input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} /></label>
        <label style={{ flex: "1 1 130px" }}>{t("auto.convert.label")}<input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
        <button className="ghost" disabled={busy} onClick={setTarget} style={{ alignSelf: "flex-end" }}>{t("auto.set")}</button>
      </div>
      <p className="muted small">{t("auto.limit", { limit: cny(a.tier1_auto_convert_cny) })}</p>
      <h4>{t("auto.recurring")}</h4>
      {a.recurring.length === 0 && <p className="muted">{t("auto.none")}</p>}
      {a.recurring.map((o) => <p key={o.id}>{R("auto.bill", { label: o.label ? tm(o.label) : tl("type", o.type), amount: cny(o.amount), days: o.every_days, due: fmtDate(o.due) })} <Pill status={o.status} /></p>)}
      <div className="row">
        <label style={{ flex: "0 1 140px" }}>{t("auto.advance.label")}<input type="number" min="1" max="60" value={days} onChange={(e) => setDays(+e.target.value)} /></label>
        <button disabled={busy} onClick={tick} style={{ alignSelf: "flex-end" }}>{t("auto.advance")}</button>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {last && <p className="muted" role="status">{tp("auto.now", last.actions.length, { date: fmtDate(last.now) })}</p>}
      <h4>{t("auto.log")}</h4>
      {a.log.length === 0 && <p className="muted">{t("auto.log.none")}</p>}
      <ul className="feed">{a.log.slice().reverse().map((e, i) => (
        <li key={i}><b>{fmtDate(e.day)}</b> {tl("status", e.kind)}{e.rule ? ` (${e.rule})` : ""}{e.delivered_cny ? t("auto.log.delivered", { amount: cny(e.delivered_cny, 2), rate: e.rate }) : ""}{e.amount_cny ? `: ${cny(e.amount_cny)}` : ""}</li>))}</ul>
    </div>
  );
}

/* ------------------------------------------------------------------ Corridor rules and sources */
const RULE_STATUS = { "confirmed-primary": "ok", "researched-secondary": "warn", unconfirmed: "bad" };
function ruleValue(r) {
  const v = r.values || {};
  if (r.id === "lrs_annual_limit_usd") return t("rules.v.lrs", { v: fmt(v.value) });
  if (r.id === "tcs_threshold_inr") return t("rules.v.tcsthr", { v: inr(v.value) });
  if (r.id.startsWith("tcs_")) return t("rules.v.tcs", { rate: pct(v.rate), thr: inr(1000000) });
  if (r.id === "safe_quota_usd") return t("rules.v.safe", { v: fmt(v.value) });
  if (r.id === "wallet_foreign_card_fee") return t("rules.v.wallet", { rate: pct(v.rate), over: v.applies_over_cny });
  if (r.id === "purpose_code_education") return String(v.value);
  if (r.id === "split_pattern") return t("rules.v.split", { n: v.min_payments, h: v.window_hours, ratio: pct(v.near_limit_ratio) });
  return JSON.stringify(v);
}
function CorridorRules() {
  const { lang } = useLang();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => { setErr(null); api("/corridor/rules").then(setD).catch(setErr); }, []);
  useEffect(() => { load(); }, [load, lang]);
  return (
    <div className="card wide" aria-label={t("rules.aria")}>
      <div className="hd"><h3>{t("rules.title")}</h3><span className="pill neutral">{t("rules.researched", { date: "2026-10-11" })}</span></div>
      {err && <ErrorBox error={err} onRetry={load} />}
      {!d && !err && <Loading />}
      {d && <>
        <p className="muted small">{t("rules.short")}</p>
        <ul className="rules" aria-label={t("rules.list.aria")}>{d.rules.map((r) => {
          const policy = r.kind === "oasis_policy";
          const cls = policy ? "neutral" : (RULE_STATUS[r.status] || "neutral");
          const txt = policy ? t("rules.policy") : (has(`rules.status.${r.status}`) ? t(`rules.status.${r.status}`) : r.status);
          return (
            <li key={r.id}>
              <div className="rule-hd"><b>{has(`rule.${r.id}`) ? t(`rule.${r.id}`) : r.label}</b><span className={`pill ${cls}`}>{txt}</span></div>
              <div>{ruleValue(r)} <span className="muted small">· {t("rules.conf", { c: tl("conf", r.confidence) })}</span></div>
              <details><summary className="small">{t("rules.source", { date: fmtDate(r.retrieved) })}</summary><p className="small">{r.source}</p></details>
            </li>);
        })}</ul>
      </>}
    </div>
  );
}

/* ------------------------------------------------------------------ Currency view + wallet conversion */
const money = (h, n, d = 2) => (h.currency === "INR" ? inr(n, d) : h.currency === "CNY" ? cny(n, d) : `${h.symbol}${fmt(n, d)}`);

function Converter({ cv, refresh }) {
  const [from, setFrom] = useState("INR");
  const [to, setTo] = useState("USD");
  const [amount, setAmount] = useState("10000");
  const [q, setQ] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const body = () => ({ amount: parseFloat(amount) || 0, from, to });
  const quote = () => run(async () => setQ(await api("/fx/quote", body())));
  const convert = () => run(async () => { const r = await api("/fx/convert", body()); setQ(null); announce(t("fx.announce", { amount: fmt(r.received, 2), to: r.to })); refresh(); });
  const sel = (v, set) => <select value={v} onChange={(e) => { set(e.target.value); setQ(null); }}>{cv.supported.map((c) => <option key={c} value={c}>{c}</option>)}</select>;
  return (
    <>
      <h4>{t("fx.title")}</h4>
      <div className="row">
        <label style={{ flex: "1 1 110px" }}>{t("fx.amount")}<input inputMode="decimal" value={amount} onChange={(e) => { setAmount(e.target.value); setQ(null); }} /></label>
        <label style={{ flex: "0 1 90px" }}>{t("fx.from")}{sel(from, setFrom)}</label>
        <label style={{ flex: "0 1 90px" }}>{t("fx.to")}{sel(to, setTo)}</label>
        <button className="ghost" disabled={busy} onClick={quote} style={{ alignSelf: "flex-end" }} data-testid="fx-quote">{t("fx.quote")}</button>
      </div>
      {q && <p>{R("fx.result", { got: fmt(q.received, 2), to: q.to, rate: q.rate, fee: fmt(q.fee, 2), from: q.from, saved: fmt(q.saved, 2) })}{" "}
        <button disabled={busy} onClick={convert} data-testid="fx-convert">{t("fx.convert")}</button></p>}
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      <p className="muted small">{t("fx.note")}</p>
    </>
  );
}

function CurrencyView({ s, refresh }) {
  const cv = s.currency_view;
  if (!cv) return null;
  const hints = (s.triggers || []).filter((x) => x.kind === "rate_move" || x.kind === "rate_target" || x.kind === "shortfall");
  const targets = s.autonomy?.targets || [];
  const rows = cv.holdings.filter((h) => h.amount > 0 || h.currency === "INR" || h.currency === "CNY");
  const cov = cv.coverage;
  return (
    <div className="card pp-card" data-testid="currency-view">
      <div className="hd"><h3>{t("cur.title")}</h3><Mock /></div>
      <div className="tbl"><table aria-label={t("cur.title")}><thead><tr><th>{t("cur.currency")}</th><th className="r">{t("cur.holding")}</th><th className="r">{t("cur.worth")}</th><th className="r">{t("cur.exposure")}</th></tr></thead>
        <tbody>{rows.map((h) => (
          <tr key={h.currency}><td>{h.currency}</td><td className="r money">{money(h, h.amount)}</td>
            <td className="r money">{cny(h.value_cny, 2)}</td><td className="r num">{cv.exposure_pct[h.currency]}%</td></tr>))}</tbody></table></div>
      <p>{R("cur.total", { cny: cny(cv.total_cny, 2), inr: inr(cv.total_inr, 2), rate: cv.rate_cny_per_inr })}</p>
      {cov && <p>{cov.shortfall_cny > 0 ? <Pill status="shortfall" /> : <Pill status="paid">{t("cur.covered.pill")}</Pill>}{" "}
        {R(cov.shortfall_cny > 0 ? "cur.short" : "cur.covered", { due: cny(cov.due_cny), have: cny(cov.cny_on_hand), short: cny(cov.shortfall_cny), days: cov.days })}</p>}
      <p className="muted small">{t("cur.note")}</p>
    </div>
  );
}

function FxConverter({ s, refresh }) {
  const cv = s.currency_view;
  if (!cv) return null;
  const hints = (s.triggers || []).filter((x) => x.kind === "rate_move" || x.kind === "rate_target" || x.kind === "shortfall");
  const targets = s.autonomy?.targets || [];
  return (
    <div className="card pp-card">
      <Converter cv={cv} refresh={refresh} />
      <h4>{t("cur.timing")}</h4>
      {hints.length ? hints.map((x, i) => <p key={i}><Pill status={x.kind} /> {x.message}</p>) : <p className="muted">{t("cur.timing.none")}</p>}
      {targets.length > 0 && <p className="muted small">{t("cur.targets", { list: targets.map((x) => t("cur.target.item", { amount: cny(x.convert_cny), rate: x.rate, status: tl("status", x.status) })).join(t("misc.semicolon")) })}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ Payment reliability record */
const RR_CHECKS = ["signature", "key_pinned", "record_hash", "summary_consistent", "on_time_consistent", "proofs_checked"];

// The signed record's caveats and amount bands are English text inside signed data, so they are translated for display only.
const caveat = (c) => tm(c);

function reliabilityPdf(rec) {
  const sm = rec.summary;
  return [
    kpis([[t("rr.pdf.payments"), String(sm.payments), ""], [t("rr.pdf.ontime"), String(sm.on_time), sm.late ? t("rr.late", { n: sm.late }) : ""], ...(sm.total_cny != null ? [[t("rr.pdf.total"), cny(sm.total_cny), ""]] : [])]),
    section(t("rr.pdf.student"), `<p>${esc(rec.student.name ? `${rec.student.name} · ` : "")}${esc(rec.student.pseudonym)} · ${esc(rec.period.from ? t("rr.period", { from: fmtDate(rec.period.from), to: fmtDate(rec.period.to) }) : t("rr.noperiod"))}</p>`),
    rec.payments.length ? section(t("rr.pdf.list"), table([t("rr.col.what"), t("rr.col.to"), t("rr.col.amount"), t("rr.col.paid"), t("rr.col.due"), t("rr.col.ontime")],
      rec.payments.map((e) => [tl("type", e.obligation_type), tl("ptype", e.payee_type), e.amount_cny != null ? cny(e.amount_cny) : tm(e.amount_band), fmtDate(e.paid_date), fmtDate(e.due_date), e.on_time ? t("rr.ontime") : t("rr.late.pill")]), [2])) : "",
    section(t("rr.pdf.notes"), `<ul>${rec.caveats.map((c) => `<li>${esc(tm(c))}</li>`).join("")}</ul><p>${esc(t("rr.fingerprint"))}: <code>${esc(rec.trust_fingerprint)}</code><br>${esc(t("rr.record"))} hash: <code>${esc(rec.record_hash)}</code></p>`),
  ].join("");
}

function RecordSummary({ rec }) {
  const sm = rec.summary;
  return (
    <div className="card" data-testid="rr-summary" style={{ marginTop: 8 }}>
      <h4 style={{ marginTop: 0 }}>{t("rr.title")} <Mock>{t("mock.sandbox")}</Mock></h4>
      <p>{t("rr.student")} <code>{rec.student.name ? `${rec.student.name} · ` : ""}{rec.student.pseudonym}</code> · {rec.period.from ? t("rr.period", { from: fmtDate(rec.period.from), to: fmtDate(rec.period.to) }) : t("rr.noperiod")}</p>
      <p>{R("rr.summary", { on: sm.on_time, n: sm.payments })}{sm.late ? t("rr.late", { n: sm.late }) : ""}{sm.total_cny != null ? ` · ${t("rr.total", { amount: cny(sm.total_cny) })}` : ""}</p>
      {rec.payments.length > 0 && (
        <div className="tbl"><table aria-label={t("rr.table.aria")}><thead><tr><th>{t("rr.col.what")}</th><th>{t("rr.col.to")}</th><th className="r">{t("rr.col.amount")}</th><th>{t("rr.col.paid")}</th><th>{t("rr.col.due")}</th><th>{t("rr.col.ontime")}</th></tr></thead>
          <tbody>{rec.payments.map((e) => (
            <tr key={e.proof_id}><td>{tl("type", e.obligation_type)}</td><td>{tl("ptype", e.payee_type)}</td>
              <td className="r">{e.amount_cny != null ? cny(e.amount_cny) : tm(e.amount_band)}</td><td>{fmtDate(e.paid_date)}</td><td>{fmtDate(e.due_date)}</td>
              <td><Pill status={e.on_time ? "paid" : "frozen"}>{e.on_time ? t("rr.ontime") : t("rr.late.pill")}</Pill></td></tr>))}</tbody></table></div>)}
      <ul className="feed">{rec.caveats.map((c, i) => <li key={i}>{caveat(c)}</li>)}</ul>
      <p className="muted small">{t("rr.fingerprint")} <Hash value={rec.trust_fingerprint} n={12} what={t("hash.fingerprint")} /> · {t("rr.record")} <Hash value={rec.record_hash} n={12} what={t("hash.record")} /></p>
    </div>
  );
}

function ReliabilityVerify({ initial }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRes(null); }, [initial]);
  const mine = async () => { setBusy(true); setErr(null); try { setRes(await api("/reliability/verify", initial)); announce(t("rr.announce.checked")); } catch (e) { setErr(e); setRes(null); } finally { setBusy(false); } };
  const go = async () => {
    setBusy(true); setErr(null);
    try { JSON.parse(text); setRes(await api("/reliability/verify", text)); announce(t("rr.announce.checked")); }
    catch (e) { setErr(e instanceof SyntaxError ? new Error(t("err.badjson")) : e); setRes(null); }
    finally { setBusy(false); }
  };
  return (
    <details><summary>{t("rr.verify.summary")}</summary>
      <p className="muted small">{t("rr.verify.intro")}</p>
      {initial && <div className="row"><button type="button" disabled={busy} onClick={mine}>{t("verify.mine")}</button></div>}
      <label>{t("rr.verify.label")}<textarea rows={8} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} data-testid="rr-verify-text" /></label>
      <div className="row"><button className="ghost" disabled={busy || !text.trim()} onClick={go} data-testid="rr-verify-btn">{t("rr.verify.btn")}</button>
        {res && (res.ok ? <Pill status="verified">{t("rr.verify.ok")}</Pill> : <Pill status="failed">{t("rr.verify.bad")}</Pill>)}</div>
      {res && (
        <ul className="feed" data-testid="rr-checks">{RR_CHECKS.map((k) => (
          <li key={k}>{res[k] === true ? "✓" : res[k] === false ? "✗" : "–"} {t(`rr.check.${k}`)}{res[k] == null ? ` ${t("rr.notchecked")}` : ""}</li>))}</ul>)}
      {err && <ErrorBox error={err} onDismiss={() => setErr(null)} />}
    </details>
  );
}

function ReliabilityRecord() {
  const [name, setName] = useState(false);
  const [amounts, setAmounts] = useState(false);
  const [rec, setRec] = useState(null);
  const [n, setN] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  useEffect(() => { let live = true; api("/reliability/mine").then((r) => { if (live) { setRec(r.record); setN(r.eligible_payments); } }).catch(() => {}); return () => { live = false; }; }, []);
  const create = () => run(async () => { const r = await api("/reliability/record", { include_name: name, share_amounts: amounts }); setRec(r); setN(r.summary.payments); announce(t("rr.announce.created", { n: r.summary.payments })); });
  return (
    <div className="card" data-testid="reliability-card">
      <div className="hd"><h3>{t("rr.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p className="muted">{R("rr.intro")}</p>
      <p className="muted small">{n == null ? "" : `${tp("rr.eligible", n)} `}{t("rr.default")}</p>
      <div className="row">
        <label className="check"><input type="checkbox" checked={name} onChange={(e) => setName(e.target.checked)} /> {t("rr.name")}</label>
        <label className="check"><input type="checkbox" checked={amounts} onChange={(e) => setAmounts(e.target.checked)} /> {t("rr.amounts")}</label>
      </div>
      <div className="row">
        <button disabled={busy} onClick={create} data-testid="rr-create">{t("rr.create")}</button>
        <button className="ghost" disabled={!rec} onClick={() => downloadPdf(reliabilityPdf(rec), "oasis-payment-reliability-record", { heading: t("rr.title"), subtitle: t("rr.intro").replace(/\*\*|`/g, ""), note: t("pdf.mocknote") })} data-testid="rr-download">{t("rr.download")}</button>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {rec && <RecordSummary rec={rec} />}
      <ReliabilityVerify initial={rec} />
    </div>
  );
}

/* ------------------------------------------------------------------ Passport tab */
/** One collapsible panel: a clear title and a one-line summary when closed, the full card when open. Keeps a busy tab readable. */
function Fold({ title, hint, open = false, children }) {
  return (
    <details className="fold" open={open}>
      <summary><span className="fold-t">{title}</span>{hint && <span className="fold-h">{hint}</span>}<svg className="chev" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg></summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}
const SECTIONS = ["treasury", "obligations", "registry", "security"];
const ICON = {
  treasury: <><path d="M20 7H5a2 2 0 0 1 0-4h13v4zM3 5v14a2 2 0 0 0 2 2h15V7" /><circle cx="16.5" cy="14" r="1.2" /></>,
  obligations: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 10h18M12 14v3l2 1" /></>,
  registry: <><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="m9 12 2.2 2.2L15.5 10" /></>,
  security: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3M12 15v2" /></>,
};

export function Passport({ s, refresh, sec = "treasury", onSec }) {
  if (!s) return <Skeleton rows={6} />;
  const p = s.passport;
  const bal = (
    <div className="card pp-card">
      <div className="hd"><h3>{t("pass.balances")}</h3><Mock /></div>
      <div className="kpis">{p.balances.map((b) => (
        <div className="kpi" key={b.currency}><div className="k">{b.currency}</div><div className="v">{money({ currency: b.currency, symbol: s.currency_view?.holdings.find((h) => h.currency === b.currency)?.symbol || "" }, b.amount)}</div></div>))}</div>
      <p className="muted">{R("pass.runway", { m: s.runway_months, burn: cny(s.burn.monthly_cny), basis: s.burn.basis })}</p>
      <p className="muted small">{t("pass.simdate", { date: fmtDate(s.now) })} {tm(s.rates?.spreads_and_fees) || ""} {t("rate.foot")}</p>
    </div>);
  const obl = (
    <div className="card pp-card">
      <h3>{t("pass.obligations")}</h3>
      <div className="tbl"><table aria-label={t("pass.obligations")}><thead><tr><th>{t("pass.col.what")}</th><th className="r">{t("pass.col.amount")}</th><th>{t("pass.col.due")}</th><th>{t("pass.col.status")}</th></tr></thead>
        <tbody>{p.obligations.map((o) => (
          <tr key={o.id}><td>{o.label ? tm(o.label) : tl("type", o.type)}</td><td className="r money">{o.currency && o.currency !== "CNY" ? `${{ USD: "$", EUR: "€" }[o.currency] || ""}${fmt(o.amount, 2)}` : cny(o.amount)}</td><td>{fmtDate(o.due)}</td><td><Pill status={o.status} /></td></tr>))}
        </tbody></table></div>
    </div>);
  const rec = (
    <div className="card pp-card">
      <div className="hd"><h3>{t("pass.recipients")}</h3><Mock>{t("mock.registry")}</Mock></div>
      <div className="tbl"><table aria-label={t("pass.recipients")}><thead><tr><th>{t("pass.col.payee")}</th><th>{t("pass.col.account")}</th><th>{t("pass.col.level")}</th><th className="r">{t("pass.col.limit")}</th></tr></thead>
        <tbody>{Object.values(p.recipients).map((r) => (
          <tr key={r.id}><td>{r.name}</td><td className="acct"><Hash value={r.account_ref} n={6} what={t("hash.account")} /></td><td className="nw"><Pill status={r.verification.level} /></td>
            <td className="r money">{cny(r.verification.limit_cny)}</td></tr>))}
        </tbody></table></div>
    </div>);
  const routes = (
    <div className="card pp-card">
      <div className="hd"><h3>{t("pass.routes")}</h3><Mock /></div>
      <div className="tbl"><table aria-label={t("pass.routes.aria")}><thead><tr><th>{t("demo.routes.route")}</th><th className="r">{t("pass.col.delivered")}</th><th className="r">{t("demo.routes.days")}</th><th className="r">{t("pass.col.vsmid")}</th></tr></thead>
        <tbody>{s.routes.map((r) => (
          <tr key={r.id}><td>{tm(r.name)}{r.typical_bank && <span className="muted"> {t("pass.typicalbank")}</span>}</td><td className="r money">{cny(r.delivered_cny_per_100k_inr, 2)}</td><td className="r">{r.days}</td><td className="r num">{r.cost_vs_mid_pct}%</td></tr>))}
        </tbody></table></div>
      <p className="muted small">{t("pass.lastmile", { extra: cny(s.last_mile_rent_6000.extra_cost_cny) })}</p>
    </div>);
  const cur = <CurrencyView s={s} refresh={refresh} />;
  const conv = <FxConverter s={s} refresh={refresh} />;
  const alertsA = (
    <div className="card pp-card">
      <h3>{t("pass.alerts")}</h3>
      {s.triggers.length ? s.triggers.map((x, i) => <p key={i}><Pill status={x.kind} /> {x.message}</p>) : <p className="muted">{t("pass.alerts.none")}</p>}
      <h3 style={{ marginTop: 16 }}>{t("pass.why")}</h3>
      {s.cards.length ? s.cards.slice().reverse().map((c) => <Card key={c.id} card={c} />) : <p className="muted">{t("pass.why.none")}</p>}
    </div>);
  const alertsB = (
    <div className="card pp-card">
      <h3>{t("pass.feed")}</h3>
      <p>{t("pass.tripwires")} {s.canaries_tripped ? <Pill status="frozen">{t("pass.tripped")}</Pill> : <Pill status="paid">{t("pass.quiet")}</Pill>}</p>
      <p className="muted small">{t("pass.decoys")}</p>
      {s.security_feed.length === 0 ? <p className="muted">{t("pass.feed.none")}</p>
        : <ul className="feed">{s.security_feed.slice().reverse().map((e) => <li key={e.i}><code>#{e.i}</code> {tl("audit", e.kind)}</li>)}</ul>}
      <p className="muted small">{t("pass.counter", { n: p.reputation.verified_on_time_payments })}</p>
    </div>);
  const F = (title, hint, node, open) => <Fold key={title} title={title} hint={hint} open={open}>{node}</Fold>;
  const balHint = p.balances.map((x) => money({ currency: x.currency, symbol: s.currency_view?.holdings.find((h) => h.currency === x.currency)?.symbol || "" }, x.amount, 0)).join(" · ");
  const open = p.obligations.filter((o) => o.status !== "paid").length;
  const body = {
    treasury: (<>
      <div className="ratebar"><RateBadge rates={s.rates} rate={s.rate_mid} /></div>
      {F(t("pass.balances"), balHint, bal, true)}
      {s.currency_view && F(t("cur.title"), cny(s.currency_view.total_cny), cur)}
      {s.currency_view && F(t("fold.conv"), t("fold.conv.hint"), conv)}
      {F(t("pass.routes"), tm(s.routes[0]?.name), routes)}
      {F(t("fxp.title"), t("fold.fxp.hint"), <FxPlan s={s} refresh={refresh} />)}
    </>),
    obligations: (<>
      {F(t("pass.obligations"), t("fold.obl.hint", { n: open }), obl, true)}
      {F(t("plan.agentic.title"), t("fold.plan.hint"), <AgentPlan s={s} refresh={refresh} />)}
      {F(t("auto.title"), t("fold.auto.hint"), <Autonomy s={s} refresh={refresh} />)}
    </>),
    registry: (<>
      {F(t("pass.recipients"), t("fold.rec.hint", { n: Object.keys(p.recipients).length }), rec, true)}
      {F(t("rules.title"), t("fold.rules.hint"), <CorridorRules />)}
    </>),
    security: (<>
      {F(t("cp.title"), t("fold.trust.hint"), <TrustPass />, true)}
      {F(t("cg.title"), t("fold.credit.hint"), <CreditGrowth />)}
      {F(t("rr.title"), t("fold.rr.hint"), <ReliabilityRecord />)}
      {F(t("pass.alerts"), s.triggers.length ? String(s.triggers.length) : t("pass.alerts.none"), alertsA)}
      {F(t("pass.feed"), s.canaries_tripped ? t("pass.tripped") : t("pass.quiet"), alertsB)}
    </>),
  }[sec] || null;
  return (
    <section className="stack pp folds" aria-label={t("pass.aria")}>
      <h2>{t("tab.passport")}</h2>
      <SubNav id="passportSubNav" label={t("pass.sub.aria")} value={sec} onChange={(k) => onSec && onSec(k)} items={SECTIONS.map((k) => [k, t(`pass.sub.${k}`), ICON[k]])} />
      {body}
    </section>
  );
}
