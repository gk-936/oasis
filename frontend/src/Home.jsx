import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { MotionConfig, animate, motion, useMotionValue, useTransform } from "motion/react";
import { t, tl } from "./i18n/index.js";
import { api } from "./api.js";
import { money } from "./ui.jsx";
import { Corridors as CorridorTool } from "./tabs/Corridors.jsx";
import { Spending } from "./tabs/Passport.jsx";

/** Landing page after login (all three roles): a welcome, a rail of feature cards that glides along by itself (and stops as soon as
    you hover, focus, drag or use the arrows), live numbers from the sandbox, the six steps every payment goes through and the one
    safety rule. The first card is the one to start with (FlightPath for a student). Each card names the roles that can open the
    feature. Cards only navigate; the server still checks the role on every call.

    The rail moves with a transform (one motion value, spring-animated), never by scrolling the page or re-rendering per frame, so it
    stays on the GPU and is smooth for every role. Depth (the centre card is biggest) is derived from the same motion value. */
const AUTO_MS = 4800;
const SPRING = { type: "spring", stiffness: 120, damping: 22, mass: 0.9 };

const rise = { hidden: { opacity: 0, y: 22 }, show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 160, damping: 22 } } };
const group = { hidden: {}, show: { transition: { staggerChildren: 0.07, delayChildren: 0.05 } } };

/** Numbers shown under the cards, taken from the same /state the other pages use. */
// Judge-only evidence tiles. Every number comes from a file in eval/reports/ or the test suite (see docs/results.md); our own tests,
// offline, MOCK data. Update with the README when the counts change.
const EVIDENCE = [
  { id: "tests", v: "1,393" },
  { id: "cases", v: "1,870", sub: "ChatGPT · Codex · Gemini" },
  { id: "attacks", v: "900 / 900" },
  { id: "stress", v: "92,104", sub: "Claude" },
  { id: "exec", v: "9 + 1", sub: "tamper · replay · forge" },
];

function stats(role, s) {
  if (!s) return [];
  const open = (s.passport?.obligations || []).filter((o) => o.status !== "paid");
  const next = [...open].sort((a, b) => String(a.due).localeCompare(String(b.due)))[0];
  const held = (s.passport?.balances || []).filter((x) => x.amount > 0);
  const waiting = { id: "waiting", v: String(s.pending?.length ?? 0) };
  const proofs = { id: "proofs", v: String(s.proofs?.length ?? 0) };
  const date = { id: "date", v: String(s.now || "").slice(0, 10) };
  if (role === "parent") return [waiting, proofs, date];
  if (role === "judge") return [];                  // the judge's home shows the evidence panel instead of "At a glance"
  return [
    { id: "bills", v: String(open.length) },
    { id: "next", v: next ? <>{money(next.amount, next.currency, 0)}<small>{tl("purpose", next.type)} · {next.due}</small></> : "–" },
    { id: "balance", v: held.length ? held.map((b) => money(b.amount, b.currency, 0)).join("  ·  ") : "–" },
    waiting,
  ];
}

/** One card. Scale and opacity follow the rail's x, so the card nearest the middle is full size and the rest recede. */
function FeatureCard({ k, i, lead, x, geo, roleTabs, onOpen }) {
  const depth = (v) => {
    const g = geo.current;
    return Math.min(1, Math.abs(v - (g.snaps[i] ?? 0)) / (g.vw * 0.62 || 600));
  };
  const scale = useTransform(x, (v) => 1 - depth(v) * 0.09);
  const opacity = useTransform(x, (v) => 1 - depth(v) * 0.5);
  return (
    <motion.div className={`fcard-wrap${lead ? " lead" : ""}`}
      initial={{ opacity: 0, y: 36 }} animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 140, damping: 20, delay: 0.25 + i * 0.07 }} whileHover={{ y: -8 }}>
      <motion.article className="fcard" style={{ scale, opacity }}>
        {lead && <span className="fcard-flag">{t("home.lead")}</span>}
        <h3>{t(`tab.${k}`)}</h3>
        <p>{t(`home.card.${k}`)}</p>
        <div className="fcard-foot">
          <span className="fcard-who">{Object.keys(roleTabs).filter((r) => roleTabs[r].includes(k)).map((r) => tl("role", r)).join(" · ")}</span>
          <button type="button" onClick={() => onOpen(k)} aria-label={`${t("home.open")}: ${t(`tab.${k}`)}`}>{t("home.open")}</button>
        </div>
      </motion.article>
    </motion.div>
  );
}

function Rail({ features, roleTabs, onOpen }) {
  const vp = useRef(null), track = useRef(null);
  const x = useMotionValue(0);
  const geo = useRef({ snaps: [0], vw: 0 });
  const [bounds, setBounds] = useState({ left: 0, right: 0 });
  const [active, setActive] = useState(0);
  const activeRef = useRef(0);
  const paused = useRef(false);
  const ctrl = useRef(null);
  const dragged = useRef(false);
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const n = features.length;

  const nearest = (v) => {
    const s = geo.current.snaps;
    let best = 0;
    for (let i = 1; i < s.length; i++) if (Math.abs(v - s[i]) < Math.abs(v - s[best])) best = i;
    return best;
  };

  // Where each card sits when it is centred; re-measured when the size changes, keeping the current card centred.
  const measure = useCallback(() => {
    const v = vp.current, tr = track.current;
    if (!v || !tr) return;
    const vw = v.clientWidth;
    const snaps = [...tr.children].map((c) => vw / 2 - (c.offsetLeft + c.offsetWidth / 2));
    geo.current = { snaps, vw };
    setBounds({ left: Math.min(...snaps), right: Math.max(...snaps) });
    x.set(snaps[activeRef.current] ?? 0);
  }, [x]);
  useLayoutEffect(() => {
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(vp.current); ro.observe(track.current);
    return () => ro.disconnect();
  }, [measure, n]);

  useEffect(() => x.on("change", (v) => {
    const i = nearest(v);
    if (i !== activeRef.current) { activeRef.current = i; setActive(i); }
  }), [x]);

  const go = useCallback((i) => {
    const to = geo.current.snaps[Math.max(0, Math.min(n - 1, i))];
    if (to === undefined) return;
    ctrl.current?.stop();
    if (reduce) x.set(to); else ctrl.current = animate(x, to, SPRING);
  }, [n, reduce, x]);
  const step = (d) => go((activeRef.current + d + n) % n);

  // Auto-advance: one card every few seconds, looping; paused while the visitor interacts or the tab is hidden.
  useEffect(() => {
    if (reduce || n < 2) return undefined;
    const id = setInterval(() => { if (!paused.current && !document.hidden) go((activeRef.current + 1) % n); }, AUTO_MS);
    return () => { clearInterval(id); ctrl.current?.stop(); };
  }, [go, n, reduce]);

  // Trackpad / shift+wheel sideways: move with the fingers, settle on the nearest card when they stop.
  useEffect(() => {
    const el = vp.current;
    let timer = 0;
    const wheel = (e) => {
      if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;     // vertical scrolling stays with the page
      e.preventDefault();
      ctrl.current?.stop();
      const { snaps } = geo.current;
      x.set(Math.max(Math.min(...snaps), Math.min(Math.max(...snaps), x.get() - e.deltaX)));
      clearTimeout(timer);
      timer = setTimeout(() => go(nearest(x.get())), 140);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => { el.removeEventListener("wheel", wheel); clearTimeout(timer); };
  }, [go, x]);

  const keys = (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  };
  const hold = (v) => () => { paused.current = v; };
  const open = (k) => { if (!dragged.current) onOpen(k); };

  return (
    <>
      <div className="rail-wrap" onPointerEnter={hold(true)} onPointerLeave={hold(false)} onFocus={hold(true)} onBlur={hold(false)}>
        <button type="button" className="rail-arrow" aria-label={t("home.prev")} onClick={() => step(-1)}>
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="m14.5 6-6 6 6 6" /></svg>
        </button>
        <div className="rail-vp" ref={vp} tabIndex={0} role="group" aria-label={t("home.rail.aria")} onKeyDown={keys}>
          <motion.div className="rail-track" ref={track} style={{ x }} drag="x" dragConstraints={bounds} dragElastic={0.1} dragMomentum={false}
            onDragStart={() => { dragged.current = true; ctrl.current?.stop(); }}
            onDragEnd={(_, info) => { go(nearest(x.get() + info.velocity.x * 0.2)); setTimeout(() => { dragged.current = false; }, 0); }}>
            {features.map((k, i) => <FeatureCard key={k} k={k} i={i} lead={i === 0} x={x} geo={geo} roleTabs={roleTabs} onOpen={open} />)}
          </motion.div>
        </div>
        <button type="button" className="rail-arrow" aria-label={t("home.next")} onClick={() => step(1)}>
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="m9.5 6 6 6-6 6" /></svg>
        </button>
      </div>
      <div className="rail-dots" role="group" aria-label={t("home.rail.aria")}>
        {features.map((k, i) => (
          <button key={k} type="button" className={i === active ? "on" : ""} aria-label={t(`tab.${k}`)} aria-current={i === active ? "true" : undefined} onClick={() => go(i)} />))}
      </div>
    </>
  );
}

/* 20px line icons for the six stages (scan, route, check, sign, watch, prove). */
const STAGE_ICON = {
  1: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
  2: <><circle cx="6" cy="19" r="2.5" /><circle cx="18" cy="5" r="2.5" /><path d="M8.5 19H15a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h6.5" /></>,
  3: <><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="m9 12 2.2 2.2L15.5 10" /></>,
  4: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4" /><path d="M14 3v5h5" /><path d="M13 20c1.500-3 3-3 3.500-1.500s1.500 1.500 3-.500" /></>,
  5: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4.500" /><path d="M12 12 18 6" /></>,
  6: <><path d="M12 11v3c0 2.500-.500 4.500-1.500 6.500M8 14c0-2.200 1.800-4 4-4s4 1.800 4 4c0 1.500-.200 3-.800 4.500M5 14a7 7 0 0 1 14 0c0 1.500-.200 2.800-.500 4M8.500 5.500A8 8 0 0 1 20 11" /></>,
};
const STAGES = [1, 2, 3, 4, 5, 6];

/** The currency pairs the sandbox can price. A chip picks the pair in the comparison tool right below it (students only; the
    other roles see the list). Prices are MOCK sandbox estimates. */
function Corridors({ canOpen }) {
  const [list, setList] = useState(null);
  const [cid, setCid] = useState(null);
  useEffect(() => { api("/corridors").then((r) => setList(r.corridors || [])).catch(() => setList([])); }, []);
  if (!list?.length) return null;
  return (
    <motion.div className="cors" variants={group} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.2 }}>
      <motion.h3 variants={rise} className="home-h3">{t("home.cor.h")}</motion.h3>
      <motion.p variants={rise} className="cors-sub">{canOpen ? t("home.cor.sub.tool") : t("home.cor.sub")}</motion.p>
      <ul className="cors-row">
        {list.map((c) => (
          <motion.li key={c.id} variants={rise}>
            {canOpen
              ? <button type="button" className={`cor${cid === c.id ? " on" : ""}`} aria-pressed={cid === c.id} onClick={() => setCid(c.id)}><b>{c.from}</b><i aria-hidden="true">→</i><b>{c.to}</b></button>
              : <span className="cor"><b>{c.from}</b><i aria-hidden="true">→</i><b>{c.to}</b></span>}
          </motion.li>))}
      </ul>
      {canOpen && <motion.div variants={rise} className="home-tool"><CorridorTool initial={cid} onReset={() => setCid(null)} /></motion.div>}
    </motion.div>
  );
}

export function Home({ role, tabs, roleTabs, onOpen, s, refresh }) {
  const features = tabs.filter((k) => k !== "home" && k !== "help" && k !== "settings");
  const tiles = stats(role, s);
  return (
    <MotionConfig reducedMotion="user">
      <section className="home" aria-labelledby="home-h">
        <motion.div variants={group} initial="hidden" animate="show">
          <motion.p variants={rise} className="home-kicker">{tl("role", role)}</motion.p>
          <motion.h2 variants={rise} id="home-h">{t(`home.title.${role}`)}</motion.h2>
          <motion.p variants={rise} className="home-sub">{t(`home.sub.${role}`)}</motion.p>
        </motion.div>

        <Rail features={features} roleTabs={roleTabs} onOpen={onOpen} />

        {tiles.length > 0 && (
          <motion.div className="stats" variants={group} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.3 }}>
            <motion.h3 variants={rise} className="home-h3">{t("home.glance")}</motion.h3>
            <div className="stat-row">
              {tiles.map((x) => (
                <motion.div key={x.id} variants={rise} className="stat"><span>{t(`home.stat.${x.id}`)}</span><b>{x.v}</b></motion.div>))}
            </div>
          </motion.div>)}

        {role === "judge" && (
          <div className="stats">
            <h3 className="home-h3">{t("home.evidence")}</h3>
            <div className="stat-row">
              {EVIDENCE.map((x) => (
                <div key={x.id} className="stat"><span>{t(`home.ev.${x.id}`)}</span><b>{x.v}{x.sub && <small>{x.sub}</small>}</b></div>))}
            </div>
          </div>)}

        {role !== "judge" && <Corridors canOpen />}
        {role === "student" && s?.spending && <div className="home-tool home-spend"><Spending s={s} refresh={refresh} /></div>}

        {role !== "judge" && <motion.aside className="rule" variants={rise} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.5 }} aria-label={t("land.safe.h")}>
          <b>{t("land.safe.h")}</b>
          <p>{t("land.safe.p1")}</p>
          <p>{t("land.safe.p2")}</p>
        </motion.aside>}
      </section>
    </MotionConfig>
  );
}
