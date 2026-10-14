import React, { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { t, tl } from "./i18n/index.js";

export const ROLES = ["student", "parent", "judge"];
const ROLE_KEY = "oasis.role";
/** The visitor's "who are you" answer. Only a UI preference: it preselects the login role and grants nothing. */
export function storedRole() {
  try { const r = localStorage.getItem(ROLE_KEY); return ROLES.includes(r) ? r : null; } catch { return null; }
}
function saveRole(r) { try { localStorage.setItem(ROLE_KEY, r); } catch { /* storage blocked: lasts for this page */ } }

/** Misty valley drawn as inline SVG: no image files, nothing fetched, works under the strict CSP. Deterministic (no Math.random). */
function ridge(seed, base, amp, step = 40) {
  let d = `M0 900 L0 ${base}`;
  for (let x = 0; x <= 1600; x += step) {
    const y = base - amp * (0.55 * Math.sin(x / 210 + seed) + 0.3 * Math.sin(x / 95 + seed * 2.1) + 0.15 * Math.sin(x / 41 + seed * 3.7));
    d += ` L${x} ${y.toFixed(1)}`;
  }
  return d + " L1600 900 Z";
}
function pines(seed, y0, count, hMin, hMax) {
  const out = [];
  for (let i = 0; i < count; i++) {
    const r = Math.abs(Math.sin(seed + i * 12.9898) * 43758.5453) % 1;
    const x = (i / count) * 1640 - 20 + r * 20;
    const h = hMin + r * (hMax - hMin);
    const w = h * 0.34;
    out.push(`M${x.toFixed(0)} ${y0} l${(-w).toFixed(0)} 0 l${(w * 0.5).toFixed(0)} ${(-h * 0.45).toFixed(0)} l${(-w * 0.3).toFixed(0)} 0 l${(w * 0.55).toFixed(0)} ${(-h * 0.55).toFixed(0)} l${(w * 0.55).toFixed(0)} ${(h * 0.55).toFixed(0)} l${(-w * 0.3).toFixed(0)} 0 l${(w * 0.5).toFixed(0)} ${(h * 0.45).toFixed(0)} Z`);
  }
  return out.join(" ");
}

/** The valley. `id` keeps gradient ids unique when the scene is drawn twice (backdrop + panel). The pencil filter roughens
    contour strokes laid over the painted fills, so the hills read as sketched rather than vector-flat. */
function Valley({ id, className }) {
  const s = useMemo(() => ({
    far: ridge(1.2, 470, 120), mid: ridge(3.4, 560, 150), near: ridge(5.1, 690, 130, 30),
    trees: pines(7, 905, 70, 90, 190), treesFar: pines(2, 760, 90, 40, 80),
  }), []);
  const u = (n) => `url(#${id}-${n})`;
  return (
    <div className={className} aria-hidden="true">
      <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" focusable="false">
        <defs>
          <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7fa7b8" /><stop offset=".55" stopColor="#c9dcd6" /><stop offset="1" stopColor="#eef2e4" /></linearGradient>
          <radialGradient id={`${id}-sun`} cx=".72" cy=".2" r=".5"><stop offset="0" stopColor="#fff6d8" stopOpacity=".95" /><stop offset="1" stopColor="#fff6d8" stopOpacity="0" /></radialGradient>
          <linearGradient id={`${id}-far`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#8fb3a6" /><stop offset="1" stopColor="#bfd4c8" /></linearGradient>
          <linearGradient id={`${id}-mid`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5f9a7d" /><stop offset="1" stopColor="#a6c9b2" /></linearGradient>
          <linearGradient id={`${id}-near`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#2f6f4d" /><stop offset="1" stopColor="#1c4a33" /></linearGradient>
          <linearGradient id={`${id}-mist`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#f4f7ee" stopOpacity="0" /><stop offset=".5" stopColor="#f4f7ee" stopOpacity=".7" /><stop offset="1" stopColor="#f4f7ee" stopOpacity="0" /></linearGradient>
          <filter id={`${id}-pencil`} x="-5%" y="-5%" width="110%" height="110%">
            <feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="4" result="n" />
            <feDisplacementMap in="SourceGraphic" in2="n" scale="4" />
          </filter>
          <pattern id={`${id}-hatch`} width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(-35)">
            <line x1="0" y1="0" x2="0" y2="9" stroke="#0e2a1c" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="1600" height="900" fill={u("sky")} />
        <rect width="1600" height="900" fill={u("sun")} />
        <path d={s.far} fill={u("far")} />
        <path d={s.treesFar} fill="#6f9a86" opacity=".55" />
        <rect className="mist m1" x="-400" y="430" width="2400" height="120" fill={u("mist")} />
        <path d={s.mid} fill={u("mid")} />
        <path d={s.mid} fill={u("hatch")} opacity=".07" />
        <rect className="mist m2" x="-400" y="540" width="2400" height="130" fill={u("mist")} />
        <path d={s.near} fill={u("near")} />
        <path d={s.near} fill={u("hatch")} opacity=".12" />
        <path d={s.trees} fill="#173d2a" />
        <g filter={u("pencil")} fill="none" stroke="#183a28" strokeLinejoin="round">
          <path d={s.far} strokeWidth="1.4" opacity=".28" />
          <path d={s.mid} strokeWidth="1.6" opacity=".32" />
          <path d={s.near} strokeWidth="1.8" opacity=".4" />
        </g>
      </svg>
    </div>
  );
}

/** App logo: the supplied artwork (deep-blue tile) served from /public, so it passes the CSP's img-src 'self'. */
export const LogoTile = ({ size = 32, className = "" }) => (
  <img className={`logo-tile ${className}`} src="/logo.png" width={size} height={size} alt="" draggable="false" />
);

const ROLE_ICON = {
  student: <path d="M4 18 32 7l28 11-28 11zM14 22v11c5 6 31 6 36 0V22M58 19v14" />,
  parent: <><circle cx="22" cy="17" r="7" /><circle cx="43" cy="22" r="5" /><path d="M8 52c1-12 7-19 14-19s13 7 14 19M33 52c1-9 5-14 10-14s9 5 10 14" /></>,
  judge: <><path d="M32 6 54 14v15c0 14-9 23-22 29C19 52 10 43 10 29V14z" /><path d="m22 31 7 7 14-15" /></>,
};
const RoleIcon = ({ role }) => (
  <svg className="who-icon" viewBox="0 0 64 64" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">{ROLE_ICON[role]}</svg>
);

const fadeUp = { hidden: { opacity: 0, y: 18 }, show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 220, damping: 26 } } };
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } } };

/** First screen for a new visitor: pick a role. The answer only preselects the login role (a role string grants nothing). */
function WhoAreYou({ current, onPick, langPicker }) {
  const first = useRef(null);
  useEffect(() => { first.current?.focus({ preventScroll: true }); }, []);
  const keys = (e) => {
    const btns = [...e.currentTarget.querySelectorAll("button")];
    const i = btns.indexOf(document.activeElement);
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (d && i >= 0) { e.preventDefault(); btns[(i + d + btns.length) % btns.length].focus(); }
  };
  return (
    <motion.section className="who" aria-labelledby="who-h" initial="hidden" animate="show" exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.2 } }} variants={stagger}>
      <div className="who-top">{langPicker}</div>
      <motion.div className="who-logo" variants={fadeUp}><LogoTile size={76} /></motion.div>
      <motion.p className="who-kicker" variants={fadeUp}>{t("who.kicker")}</motion.p>
      <motion.h2 id="who-h" className="land-h1 who-h" variants={fadeUp}>{t("who.h1a")} <em>{t("who.h1b")}</em></motion.h2>
      <motion.p className="land-sub" variants={fadeUp}>{t("who.sub")}</motion.p>
      <motion.div className="who-cards" role="group" aria-label={t("login.role.aria")} onKeyDown={keys} variants={stagger}>
        {ROLES.map((r, i) => (
          <motion.button key={r} ref={i === 0 ? first : null} type="button" className={`who-card ${current === r ? "on" : ""}`}
            aria-pressed={current === r} onClick={() => onPick(r)} variants={fadeUp}
            whileHover={{ y: -6, rotate: i === 1 ? 0 : i === 0 ? -0.6 : 0.6 }} whileTap={{ scale: 0.97 }}>
            <RoleIcon role={r} />
            <b>{tl("role", r)}</b>
            <span>{t(`role.${r}.desc`)}</span>
            <i className="who-go" aria-hidden="true">→</i>
          </motion.button>))}
      </motion.div>
      <motion.p className="who-note" variants={fadeUp}>{t("who.note")}</motion.p>
    </motion.section>
  );
}

/** Settings popover on the landing nav: change the remembered role and the language. */
function Settings({ role, onRole, onWho, langPicker }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const off = (e) => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", off); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <span className="land-set" ref={box}>
      <button type="button" className="lnk gear" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)} title={t("land.settings")}>
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" /></svg>
        <span className="sr-only">{t("land.settings")}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="land-pop" role="dialog" aria-label={t("land.settings")}
            initial={{ opacity: 0, y: -8, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.97 }} transition={{ duration: 0.16 }}>
            <b>{t("land.settings.role")}</b>
            <div className="seg" role="group" aria-label={t("login.role.aria")}>
              {ROLES.map((r) => <button key={r} type="button" aria-pressed={r === role} onClick={() => onRole(r)}>{tl("role", r)}</button>)}
            </div>
            <b>{t("lang.aria")}</b>
            {langPicker}
            <button type="button" className="lnk who-again" onClick={() => { setOpen(false); onWho(); }}>{t("land.settings.who")}</button>
          </motion.div>)}
      </AnimatePresence>
    </span>
  );
}

/** Hand-drawn underline that pencils itself in under the hero's italic phrase. */
const Scribble = () => (
  <svg className="scribble" viewBox="0 0 300 24" preserveAspectRatio="none" aria-hidden="true">
    <motion.path d="M4 16 C 60 6, 120 20, 180 11 S 270 8, 296 14" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round"
      initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 0.7, duration: 0.9, ease: "easeInOut" }} />
  </svg>
);

const STEPS = [1, 2, 3, 4, 5, 6];
const FEATURES = ["flight", "pass", "twin", "break"];

/** Logged-out site: "who are you" first (until answered), then the home page, then the login card for the chosen role.
    `renderLogin({ role, setRole })` returns the existing Login card, kept in App because it owns the session logic. */
export function Landing({ renderLogin, langPicker, notice }) {
  const [role, setRoleState] = useState(storedRole);
  const [view, setView] = useState(() => (notice ? "login" : storedRole() ? "home" : "who"));
  const setRole = (r) => { setRoleState(r); saveRole(r); };
  const pick = (r) => { setRole(r); setView("home"); };
  const go = (id) => {
    setView("home");
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" }), 30);
  };
  return (
    <MotionConfig reducedMotion="user">
      <div className="land">
        <Valley id="lb" className="land-bg" />
        <AnimatePresence mode="wait">
          {view === "who" ? (
            <div className="land-wrap" key="who"><div className="land-panel who-panel"><Valley id="lp1" className="panel-scene" /><WhoAreYou current={role} onPick={pick} langPicker={langPicker} /></div></div>
          ) : (
            <motion.div className="land-wrap" key="site" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
              <div className="land-panel" id="land-home">
                <Valley id="lp2" className="panel-scene" />
                <nav className="land-nav" aria-label={t("land.nav.aria")}>
                  <span className="land-brand"><LogoTile size={30} /><b>Oasis</b></span>
                  <span className="land-links">
                    <button type="button" className="lnk" onClick={() => go("land-home")}>{t("land.nav.home")}</button>
                    <button type="button" className="lnk" onClick={() => go("land-how")}>{t("land.nav.how")}</button>
                    <button type="button" className="lnk" onClick={() => go("land-safe")}>{t("land.nav.safety")}</button>
                    <button type="button" className="lnk" onClick={() => go("land-limits")}>{t("land.nav.limits")}</button>
                  </span>
                  <span className="land-nav-r">
                    <Settings role={role} onRole={setRole} onWho={() => setView("who")} langPicker={langPicker} />
                    <button type="button" className="land-btn sm" onClick={() => setView("login")}>{t("land.nav.login")}</button>
                  </span>
                </nav>
                <AnimatePresence mode="wait">
                  {view === "login" ? (
                    <motion.div className="land-login" key="login" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.25 }}>
                      <button type="button" className="lnk back" onClick={() => setView("home")}>← {t("land.back")}</button>
                      {renderLogin({ role: role || "student", setRole })}
                    </motion.div>
                  ) : (
                    <motion.div className="land-hero" key="hero" initial="hidden" animate="show" exit={{ opacity: 0, y: -10 }} variants={stagger}>
                      <motion.span className="land-badge" variants={fadeUp}><span className="pulse" aria-hidden="true" />{t("land.badge")}</motion.span>
                      <motion.h2 className="land-h1" variants={fadeUp}>{t("land.h1a")} <em>{t("land.h1b")}<Scribble /></em></motion.h2>
                      <motion.p className="land-sub" variants={fadeUp}>{t("land.sub")}</motion.p>
                      <motion.div className="land-cta" variants={fadeUp}>
                        <motion.button type="button" className="land-btn" onClick={() => setView("login")} whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}>
                          {role ? t("land.cta.as", { role: tl("role", role) }) : t("land.cta")}</motion.button>
                      </motion.div>
                      <motion.ul className="land-marks" aria-label={t("land.marks.aria")} variants={fadeUp}>
                        {FEATURES.map((k) => <li key={k}>{t(`land.chip.${k}`)}</li>)}
                      </motion.ul>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              <motion.section className="land-sec" id="land-how" aria-labelledby="land-how-h" initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.2 }}>
                <h3 id="land-how-h">{t("land.how.h")}</h3>
                <ol className="land-steps">
                  {STEPS.map((i) => <li key={i}><b>{t(`land.step.${i}.t`)}</b><span>{t(`land.step.${i}.d`)}</span></li>)}
                </ol>
              </motion.section>

              <div className="land-two">
                <motion.section className="land-sec" id="land-safe" aria-labelledby="land-safe-h" initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.2 }}>
                  <h3 id="land-safe-h">{t("land.safe.h")}</h3>
                  <p>{t("land.safe.p1")}</p>
                  <p>{t("land.safe.p2")}</p>
                  <aside className="land-guard" aria-label={t("land.guard.title")}>
                    <b className="gt">{t("land.guard.title")}</b>
                    <p className="g1">{t("land.guard.l1")}</p>
                    <p className="g2">{t("land.guard.l2")}</p>
                    <p className="g3"><span className="dot" aria-hidden="true" />{t("land.guard.l3")}</p>
                  </aside>
                </motion.section>
                <motion.section className="land-sec" id="land-limits" aria-labelledby="land-limits-h" initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: 0.2 }}>
                  <h3 id="land-limits-h">{t("land.limits.h")}</h3>
                  <ul>
                    <li>{t("land.limits.l1")}</li>
                    <li>{t("land.limits.l2")}</li>
                    <li>{t("land.limits.l3")}</li>
                  </ul>
                </motion.section>
              </div>
              <p className="land-foot">{t("land.footer")}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}
