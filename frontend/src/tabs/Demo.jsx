import React, { useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { api, useGuard } from "../api.js";
import { Outcome } from "../common.jsx";
import { t, tl, tm, tp, useLang } from "../i18n/index.js";
import { announce, cny, ErrorBox, fmtDate, inr, Loading, Mock, Pill, R, STEPS, money, trailOf } from "../ui.jsx";
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
  const [lang, setLang] = useState(null);                 // null = follow the interface language (English or Chinese)
  const cur = lang ?? (ui === "zh" && views.zh ? "zh" : "en");
  useEffect(() => { setLang(null); }, [ui]);
  const v = views[cur];
  return (
    <div className="card inner">
      <h4 style={{ marginTop: 0 }}>{t("demo.parent.title")}</h4>
      <div className="seg" role="group" aria-label={t("demo.parent.aria")}>{Object.keys(views).filter((l) => l !== "ta").map((l) => <button key={l} lang={l} aria-pressed={l === cur} onClick={() => setLang(l)}>{views[l].language_name}</button>)}</div>
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

const pad2 = (n) => String(n).padStart(2, "0");
const stripNo = (title) => String(title || "").replace(/^\s*\d+[.)、]\s*/, "");

/** The six pipeline stages as pills: `on` = stages this step exercises, `stop` = the stage where a payment was stopped. */
function StagePills({ items, stop = -1 }) {
  return (
    <ol className="stage-pills" aria-label={t("pipe.mini.aria")}>
      {STEPS.map((k, i) => (
        <li key={k} className={i === stop ? "stop" : items?.includes(k) ? "on" : ""}>{t(`pipe.${k}`)}
          {(items?.includes(k) || i === stop) && <span className="sr-only"> {t("pipe.mini.exercised")}</span>}</li>))}
    </ol>
  );
}

const Chevron = ({ open }) => (
  <svg className={`chev${open ? " open" : ""}`} viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6" /></svg>
);

function StepView({ r, openProof, last, open, onToggle, no }) {
  const ref = useRef(null);
  useEffect(() => { if (last && ref.current) ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [last]);
  const o = r.outcome, f = o?.fields;
  const stopped = o && ["frozen", "rejected"].includes(o.status);
  const stopIdx = stopped ? trailOf(o).findIndex((x) => x.state === "stop") : -1;
  const status = stopped ? { cls: "bad", text: o.status === "frozen" ? t("demo.acc.frozen") : t("demo.acc.rejected") }
    : o?.status === "held" ? { cls: "warn", text: t("demo.acc.held") } : { cls: "ok", text: t("demo.acc.passed") };
  const id = `step-body-${no}`;
  return (
    <article className={`card step acc${open ? ` open ${stopped ? "acc-bad" : "acc-ok"}` : ""}`} ref={ref} aria-label={r.title}>
      <button type="button" className="acc-head" aria-expanded={open} aria-controls={id} onClick={onToggle}>
        <span className="acc-left">
          <span className="acc-top">
            <span className="stepbadge">{pad2(no)}</span>
            <span className={`acc-status ${status.cls}${stopped ? " pulse" : ""}`}>{status.cls === "ok" ? "✓" : "●"} {status.text}</span>
            {stopped && f && <span className="acc-amt">{money(f.amount, f.currency, 2)}</span>}
          </span>
          <b className="acc-title">{r.title}</b>
          <small className="acc-sub">{r.narrative}</small>
        </span>
        <span className="acc-right"><StagePills items={r.pipeline} stop={stopIdx} /><Chevron open={open} /></span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div id={id} key="body" className="acc-body-wrap" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}>
            <div className="acc-body">
              <div className="acc-bar"><AiBadge ai={r.ai} /><p className="lead">{r.headline}</p></div>
              {r.plan && <PlanView plan={r.plan} />}
              {r.agentic_plan && <PlanPanel plan={r.agentic_plan} />}
              {r.outcome && <Outcome o={r.outcome} onProof={openProof} forensic />}
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
            </div>
          </motion.div>)}
      </AnimatePresence>
    </article>
  );
}

/** One scripted step of the run: a single badge, title, description, and the stages it exercises. */
function PlanRow({ s, no, state }) {
  return (
    <li className={`steprow ${state}`}>
      <div className="steprow-l">
        <div className="steprow-top"><span className="stepbadge">{pad2(no)}</span><b>{stripNo(s.title)}</b>{state === "done" && <span className="steprow-ok">✓ {t("pipe.s.done")}</span>}</div>
        <p>{s.narrative}</p>
      </div>
      <StagePills items={s.pipeline} />
    </li>
  );
}

export function Demo({ refresh, openProof }) {
  const { lang } = useLang();
  const [info, setInfo] = useState(null);
  const [results, setResults] = useState([]);
  const [mode, setMode] = useState("offline");
  const [open, setOpen] = useState({});                      // step index -> expanded; every step starts collapsed
  const { busy, err, setErr, run } = useGuard();
  const addResult = (r) => { setResults((x) => [...x, r]); announce(t("demo.announce.step", { n: (r.index ?? 0) + 1 })); };
  const start = (which) => run(async () => {
    setResults([]); setOpen({}); const i = await api("/demo/start", { run: which, mode }); setInfo(i);
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
  const allOpen = results.length > 0 && results.every((r, i) => open[r.index ?? i]);
  const fade = { hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 170, damping: 24 } } };
  const stage = { hidden: {}, show: { transition: { staggerChildren: 0.07 } } };
  const ENGINES = [["live", t("demo.mode.live"), true], ["offline", t("demo.mode.offline"), false]];
  const PLAY = <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="currentColor"><path d="M8 5.5v13l11-6.5z" /></svg>;
  return (
    <MotionConfig reducedMotion="user">
    <motion.section aria-labelledby="demo-h" className="stack demo" variants={stage} initial="hidden" animate="show">
      <motion.div variants={fade} className="demo-hero">
        <span className="demo-eyebrow"><i aria-hidden="true" />{t("demo.eyebrow")}</span>
        <h2 id="demo-h">{t("demo.title")}</h2>
        <p className="lead">{t("demo.lead.clean")}</p>
        <ul className="chips-spec" aria-label={t("demo.chips.aria")}>
          <li>{t("demo.chip.pipeline")}</li>
          <li className="amber">{t("demo.chip.data")}</li>
          <li className="cyan">{t("demo.chip.keys")}</li>
          <li>{t("demo.chip.net")}</li>
        </ul>
      </motion.div>

      <motion.div variants={fade} className="deck">
        <span className="deck-scan" aria-hidden="true" />
        <h3>{t("demo.mode.title")}</h3>
        <div className="engine" role="group" aria-label={t("demo.mode.aria")}>
          {ENGINES.map(([id, label, rec]) => (
            <button key={id} type="button" aria-pressed={mode === id} disabled={busy} onClick={() => setMode(id)}>
              {mode === id && <motion.span layoutId="engineSelector" className="engine-pill" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                {id === "live" ? <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" /> : <path d="m7 8-4 4 4 4M17 8l4 4-4 4M14 5l-4 14" />}
              </svg>
              <span>{label}</span>
              {rec && <em>{t("demo.recorded")}</em>}
            </button>))}
        </div>
        <AnimatePresence mode="wait" initial={false}>
          <motion.p key={mode} className="engine-note" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.16 }}>
            {mode === "live" ? t("demo.mode.live.text") : t("demo.mode.offline.text")}
          </motion.p>
        </AnimatePresence>

        <div className="runs">
          <motion.button type="button" className="run ok" disabled={busy} onClick={() => start("legit")} whileHover={{ y: -2 }} whileTap={{ scale: 0.985 }}>
            <svg className="run-ico" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="m9 12 2.2 2.2L15.5 10" /></svg>
            <span className="run-t"><b>{t("demo.start.legit")}</b><small>{t("demo.run1.sub")}</small></span>
            <span className="run-go">{PLAY}</span>
          </motion.button>
          <motion.button type="button" className="run bad" disabled={busy} onClick={() => start("attack")} whileHover={{ y: -2 }} whileTap={{ scale: 0.985 }}>
            <svg className="run-ico" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="M12 8v5M12 16v.5" /></svg>
            <span className="run-t"><b>{t("demo.start.attack")}</b><small>{t("demo.run2.sub")}</small></span>
            <span className="run-go">{PLAY}</span>
          </motion.button>
          <motion.button type="button" className="run ok" disabled={busy} onClick={() => start("autonomy")} whileHover={{ y: -2 }} whileTap={{ scale: 0.985 }}>
            <svg className="run-ico" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="M12 8v5M12 16v.5" /></svg>
            <span className="run-t"><b>{t("demo.start.autonomy")}</b><small>{t("demo.run3.sub")}</small></span>
            <span className="run-go">{PLAY}</span>
          </motion.button>
        </div>
        {busy && !info && <div className="row"><Loading>{t("demo.running")}</Loading></div>}
      </motion.div>
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
          <ol className="steprows">{info.steps.map((st, i) => <PlanRow key={st.title} s={st} no={i + 1} state={i < results.length ? "done" : i === results.length && !info.done ? "now" : ""} />)}</ol>
          <div className="toolbar">
            <div className="toolbar-btns">
              {!info.done && <button type="button" className="go" disabled={busy} onClick={next}><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="M6 5v14l9-7zM17 5h2v14h-2z" /></svg>{t("demo.next")}</button>}
              {!info.done && <button type="button" className="ghost" disabled={busy} onClick={playAll}><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="M3 5v14l8-7zM12 5v14l9-7z" /></svg>{t("demo.playall")}</button>}
              {results.length > 0 && <button type="button" className="ghost" onClick={() => setOpen(allOpen ? {} : Object.fromEntries(results.map((r, i) => [r.index ?? i, true])))}>
                {allOpen ? t("demo.collapseall") : t("demo.expandall")}</button>}
              {busy && <Loading>{t("demo.running")}</Loading>}
            </div>
            <div className="toolbar-prog" role="status">
              <span>{t("demo.stepof", { n: Math.min(results.length, info.total), total: info.total })}</span>
              <span className="prog-track"><span className="prog-fill" style={{ width: `${Math.min(100, (results.length / (info.total || 1)) * 100)}%` }} /></span>
            </div>
          </div>
        </div>
      )}
      {results.map((r, i) => { const k = r.index ?? i; return <StepView key={k} r={r} no={k + 1} openProof={openProof} last={i === results.length - 1} open={!!open[k]} onToggle={() => setOpen((x) => ({ ...x, [k]: !x[k] }))} />; })}
      {!info && (
        <motion.div variants={fade} className="standby">
          <span className="standby-badge"><i aria-hidden="true" />{t("demo.standby")}</span>
          <ol className="pipe">
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <li key={n}><span className="pipe-node" aria-hidden="true" /><b>{t(`land.step.${n}.t`)}</b></li>))}
          </ol>
          <p className="muted small">{t("demo.empty.text")}</p>
        </motion.div>)}
    </motion.section>
    </MotionConfig>
  );
}
