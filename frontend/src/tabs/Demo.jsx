import React, { useEffect, useRef, useState } from "react";
import { api, useGuard } from "../api.js";
import { Outcome } from "../common.jsx";
import { t, tl, tm, tp, useLang } from "../i18n/index.js";
import { announce, cny, Empty, ErrorBox, fmtDate, inr, Loading, MiniTrail, Mock, Pill, R } from "../ui.jsx";
import { PlanPanel } from "./plan.jsx";

function PlanView({ plan }) {
  return (
    <div className="card inner">
      <div className="hd"><h4 style={{ margin: 0 }}>{t("demo.plan.title")}</h4><Mock /></div>
      <p>{R("demo.plan.balances", { inr: inr(plan.balances.INR), cny: cny(plan.balances.CNY), obl: cny(plan.obligations_cny), need: inr(plan.inr_needed_for_all), short: inr(plan.shortfall_inr), months: plan.runway_months })}</p>
      <p className="muted">{t("demo.plan.basis", { basis: plan.burn.basis, monthly: cny(plan.burn.monthly_cny) })}</p>
      {plan.triggers.map((x, i) => <p key={i}><Pill status={x.kind} /> {x.message}</p>)}
      <div className="tbl"><table aria-label={t("demo.routes.aria")}><thead><tr><th>{t("demo.routes.route")}</th><th className="r">{t("demo.routes.yuan")}</th><th className="r">{t("demo.routes.days")}</th></tr></thead>
        <tbody>{plan.routes.map((r) => <tr key={r.name}><td>{tm(r.name)}</td><td className="r money">{cny(r.cny_per_100k_inr, 2)}</td><td className="r">{r.days}</td></tr>)}</tbody></table></div>
      <p>{R("demo.savings", { route: tm(plan.projected_savings.route), saved: cny(plan.projected_savings.saved_cny, 2), pct: plan.projected_savings.saved_pct })}</p>
      <p><b>{plan.advice}</b></p>
    </div>
  );
}

function ParentLang({ views }) {
  const { lang: ui } = useLang();
  const [lang, setLang] = useState(null);                 // null = Tamil (the demo parent's language), or Chinese when the interface is Chinese
  const cur = lang ?? (ui === "zh" && views.zh ? "zh" : "ta");
  const v = views[cur];
  return (
    <div className="card inner">
      <h4 style={{ marginTop: 0 }}>{t("demo.parent.title")}</h4>
      <div className="seg" role="group" aria-label={t("demo.parent.aria")}>{Object.keys(views).map((l) => <button key={l} lang={l} aria-pressed={l === cur} onClick={() => setLang(l)}>{views[l].language_name}</button>)}</div>
      <p lang={cur} className="lang-text">{v.explanation}</p>
      <table><tbody>{v.facts.map((f) => <tr key={f.label}><td lang={cur}>{f.label}</td><td lang={cur}>{f.value}</td></tr>)}</tbody></table>
    </div>
  );
}

function AiBadge({ ai }) {
  if (!ai) return null;
  const live = ai.mode === "live";
  return (
    <p className={`aibadge ${live ? "live" : "offline"}`} title={t("ai.title")}>
      <span className="mode">{live ? t("ai.live") : t("ai.offline")}</span> <span>{ai.label}</span>
      {ai.replay_misses > 0 && <span className="muted">{tp("ai.misses", ai.replay_misses)}</span>}
    </p>
  );
}

function StepView({ r, openProof, last }) {
  const ref = useRef(null);
  useEffect(() => { if (last && ref.current) ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [last]);
  return (
    <article className="card step" ref={ref} aria-label={r.title}>
      <div className="hd"><h3>{r.title}</h3><MiniTrail items={r.pipeline} /></div>
      <p className="muted">{r.narrative}</p>
      <AiBadge ai={r.ai} />
      <p className="lead" style={{ fontWeight: 600, color: "var(--ink)" }}>{r.headline}</p>
      {r.plan && <PlanView plan={r.plan} />}
      {r.agentic_plan && <PlanPanel plan={r.agentic_plan} />}
      {r.outcome && <Outcome o={r.outcome} onProof={openProof} />}
      {r.parent_view && <ParentLang views={r.parent_view} />}
      {r.recovery && <p className="muted">{tp("demo.recovery", r.recovery.canaries_cleared)}</p>}
      {r.actions && (
        <div className="card inner"><h4 style={{ marginTop: 0 }}>{t("demo.actions.title")}</h4>
          <p className="muted">{t("demo.actions.target", { amount: cny(r.target.convert_cny), rate: r.target.rate })}</p>
          {r.actions.map((a, i) => <p key={i}><Pill status={a.kind} /> {fmtDate(a.day)}: {a.kind === "rate_target_conversion"
            ? t("demo.actions.conv", { rate: a.rate, target: a.target_rate, amount: cny(a.convert_cny), route: tm(a.route), rule: a.rule })
            : t("demo.actions.bill", { label: tm(a.label), amount: cny(a.amount_cny), rule: a.rule, proof: a.proof_id })}</p>)}
        </div>
      )}
      {r.proof_ids && (
        <div className="card inner"><div className="hd"><h4 style={{ margin: 0 }}>{t("demo.proofs.title")}</h4><Mock /></div>
          <div className="row">{r.proof_ids.map((p) => <button key={p} className="ghost" onClick={() => openProof(p)}>{p}</button>)}</div>
          <p>{r.savings_receipt.text}</p>
          <p className="muted">{t("demo.proofs.rep", { n: r.reputation.verified_on_time_payments })} <Pill status={r.audit_ok ? "intact" : "broken"} /></p>
        </div>
      )}
      {r.cards && r.money_lost !== undefined && (
        <div className="kpis">
          <div className="kpi"><div className="k">{t("demo.kpi.lost")}</div><div className="v">{cny(r.money_lost, 2)}</div></div>
          <div className="kpi"><div className="k">{t("demo.kpi.cards")}</div><div className="v">{r.cards.length}</div></div>
          <div className="kpi"><div className="k">{t("demo.kpi.audit")}</div><div className="v"><Pill status={r.audit_ok ? "intact" : "broken"} /></div></div>
        </div>
      )}
    </article>
  );
}

export function Demo({ refresh, openProof }) {
  const { lang } = useLang();
  const [info, setInfo] = useState(null);
  const [results, setResults] = useState([]);
  const [mode, setMode] = useState("offline");
  const { busy, err, setErr, run } = useGuard();
  const addResult = (r) => { setResults((x) => [...x, r]); announce(t("demo.announce.step", { n: (r.index ?? 0) + 1 })); };
  const start = (which) => run(async () => {
    setResults([]); const i = await api("/demo/start", { run: which, mode }); setInfo(i);
    announce(t("demo.announce.started", { run: tl("run", which), mode: i.mode === "live" ? t("ai.live") : t("ai.offline") })); refresh();
  });
  const next = () => run(async () => { const r = await api("/demo/next", {}); addResult(r); setInfo((i) => ({ ...i, done: r.done })); refresh(); });
  const playAll = () => run(async () => {
    try {
      while (true) { const r = await api("/demo/next", {}); addResult(r); if (r.done) { setInfo((i) => ({ ...i, done: true })); break; } }
    } finally { refresh(); }
  });
  // Switching language re-reads the run so the server's own text (step titles, plans, why-cards) follows the interface.
  const seen = useRef(lang);
  useEffect(() => {
    if (seen.current === lang) return;
    seen.current = lang;
    if (!info) return;
    api("/demo/state").then((d) => { if (d.active) { setResults(d.results.filter((r) => r.index !== undefined)); setInfo((i) => ({ ...i, steps: d.steps })); } }).catch(() => {});
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <section aria-labelledby="demo-h" className="stack">
      <div>
        <h2 id="demo-h">{t("demo.title")}</h2>
        <p className="lead">{t("demo.lead.pre")} <Mock /> {R("demo.lead.post")}</p>
      </div>
      <div className="card">
        <h3>{t("demo.mode.title")}</h3>
        <div className="seg" role="group" aria-label={t("demo.mode.aria")}>
          <button aria-pressed={mode === "live"} disabled={busy} onClick={() => setMode("live")}>{t("demo.mode.live")}</button>
          <button aria-pressed={mode === "offline"} disabled={busy} onClick={() => setMode("offline")}>{t("demo.mode.offline")}</button>
        </div>
        <p className="muted">{mode === "live" ? t("demo.mode.live.text") : t("demo.mode.offline.text")}</p>
        <div className="row">
          <button disabled={busy} onClick={() => start("legit")}>{t("demo.start.legit")}</button>
          <button disabled={busy} onClick={() => start("attack")}>{t("demo.start.attack")}</button>
          {info && !info.done && <button disabled={busy} onClick={next}>{t("demo.next")}</button>}
          {info && !info.done && <button className="ghost" disabled={busy} onClick={playAll}>{t("demo.playall")}</button>}
          {busy && <Loading>{t("demo.running")}</Loading>}
        </div>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {info && (
        <div className="card">
          <div className="hd">
            <span className={`aibadge ${info.mode === "live" ? "live" : "offline"}`} style={{ margin: 0 }}>
              <span className="mode">{info.mode === "live" ? t("ai.live") : t("ai.offline")}</span>
              <span>{info.mode === "live" ? t("demo.replayed", { model: info.model }) : info.llm}</span></span>
            <Pill status={info.done && results.length > 0 ? "done" : "pending"}>{info.done && results.length > 0 ? t("demo.complete") : t("demo.inprogress")}</Pill>
          </div>
          <p className="muted small">{R("demo.info", { run: tl("run", info.run), seed: info.seed, n: results.length, total: info.total })}
            {info.mode === "live" && ` · ${t("demo.fixture", { n: info.fixture?.entries ?? 0 })}${info.fixture?.recorded?.length ? ` (${info.fixture.recorded.join(", ")})` : ""}`}</p>
          {results.length === 0 && (
            <ol className="trace">{info.steps.map((s) => <li key={s.title}><b>{s.title}</b> <span className="muted">{s.narrative}</span> <MiniTrail items={s.pipeline} /></li>)}</ol>)}
        </div>
      )}
      {results.map((r, i) => <StepView key={r.index ?? i} r={r} openProof={openProof} last={i === results.length - 1} />)}
      {!info && <Empty title={t("demo.empty.title")}>{t("demo.empty.text")}</Empty>}
    </section>
  );
}
