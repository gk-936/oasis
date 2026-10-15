import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { api, short4 } from "./api.js";
import { unlockDevice } from "./crypto.js";
import { LANG_CODES, REGISTRY, t, tl, useLang } from "./i18n/index.js";
import { ApiError, ErrorBox } from "./ui.jsx";

/* 18px line icons (stroke 1.75), drawn inline so the app needs no icon package. */
const P = {
  home: <path d="m3 11 9-8 9 8M5 10v10h5v-6h4v6h5V10" />,
  flightpath: <><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5z" /></>,
  chat: <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />,
  passport: <><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="m9 12 2.2 2.2L15.5 10" /></>,
  parent: <><circle cx="9" cy="8" r="3.2" /><path d="M3 20c.4-3.6 2.7-5.5 6-5.5s5.6 1.9 6 5.5" /><circle cx="17.5" cy="9" r="2.4" /><path d="M16.5 14.6c2.6.1 4.2 1.7 4.5 4.4" /></>,
  twin: <><rect x="5" y="5" width="14" height="14" rx="2" /><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></>,
  netting: <path d="M7 8h13M16 4l4 4-4 4M17 16H4M8 12l-4 4 4 4" />,
  proof: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 14.5l2 2 4-4" /></>,
  evp: <><ellipse cx="12" cy="6" rx="7.5" ry="3" /><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" /></>,
  demo: <><circle cx="12" cy="12" r="9" /><path d="m10 8.5 5 3.5-5 3.5z" /></>,
  redteam: <><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="M12 8v5M12 16v.5" /></>,
  breakit: <path d="m13 2-9 12h7l-1 8 9-12h-7z" />,
  numbers: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" /></>,
  wallet: <><path d="M20 7H5a2 2 0 0 1 0-4h13v4zM3 5v14a2 2 0 0 0 2 2h15V7" /><circle cx="16.5" cy="14" r="1.2" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 10h18M12 14v3l2 1" /></>,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3M12 15v2" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1.9-1.1 1.8M12 17v.2" /></>,
};
const Icon = ({ name }) => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">{P[name]}</svg>
);
const Mini = ({ children }) => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);

/* Feature groups in the drawer. Only groups the role actually has are drawn; the lists come from the caller (TABS_BY_ROLE). */
const PASS = ["treasury", "obligations", "registry", "security"];
const GROUPS = [
  { id: "core", items: ["home", "chat", "flightpath", "passport", "parent", "twin"] },
  { id: "verify", items: ["netting", "proof", "evp", "demo"] },
  { id: "eval", items: ["redteam", "breakit", "numbers"] },
  { id: "system", items: ["help", "settings"] },
];
const PASS_ICON = { treasury: "wallet", obligations: "calendar", registry: "passport", security: "lock" };
const itemOf = (k) => (k.startsWith("passport:") ? { ico: PASS_ICON[k.slice(9)], label: t(`pass.sub.${k.slice(9)}`), tab: "passport", sec: k.slice(9) } : { ico: k, label: t(`tab.${k}`), tab: k });

/** Segmented language control with a pill that slides to the active language. For a student the choice is also saved in the Passport. */
export function LangToggle({ role }) {
  const { lang, setLang } = useLang();
  const pick = (code) => {
    setLang(code);
    if (role === "student") api("/student/language", { language: code }).catch(() => { /* the local choice still applies */ });
  };
  return (
    <div className="lt" role="group" aria-label={t("lang.aria")}>
      {LANG_CODES.map((c) => (
        <button key={c} type="button" lang={REGISTRY[c].html} aria-pressed={c === lang} onClick={() => pick(c)}>
          {c === lang && <motion.span layoutId="langPill" className="lt-pill" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
          <span>{REGISTRY[c].name}</span>
        </button>))}
    </div>
  );
}

/** The logged-in menu: a glass drawer from the right with every feature the role may use (grouped), the language switch and the
    account actions. The feature list comes from the caller, so a role is only ever offered its own features; the server enforces
    the same split on every endpoint. */
export function AppMenu({ tabs, tab, onPick, role, sec }) {
  const [open, setOpen] = useState(false);
  const btn = useRef(null), panel = useRef(null);
  const close = (refocus) => { setOpen(false); if (refocus) btn.current?.focus(); };

  useEffect(() => {
    if (!open) return undefined;
    const keys = (e) => {
      if (e.key === "Escape") { close(true); return; }
      if (e.key !== "Tab" || !panel.current) return;          // keep keyboard focus inside the open drawer
      const f = [...panel.current.querySelectorAll("button:not(:disabled)")];
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    addEventListener("keydown", keys);
    const id = setTimeout(() => panel.current?.querySelector("[aria-current='page']")?.focus(), 60);
    return () => { removeEventListener("keydown", keys); clearTimeout(id); };
  }, [open]);

  const groups = GROUPS.map((g) => ({ ...g, items: g.items.filter((k) => tabs.includes(k.startsWith("passport:") ? "passport" : k)) })).filter((g) => g.items.length);
  const target = typeof document !== "undefined" ? (btn.current?.closest(".shell") || document.body) : null;

  const list = { hidden: {}, show: { transition: { staggerChildren: 0.03, delayChildren: 0.12 } } };
  const row = { hidden: { opacity: 0, y: 6 }, show: { opacity: 1, y: 0 } };

  return (
    <MotionConfig reducedMotion="user">
      <button ref={btn} type="button" className="menu-btn" aria-haspopup="dialog" aria-expanded={open} aria-label={t("menu.open")} title={t("menu.open")} onClick={() => setOpen(true)}>
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
      </button>
      {target && createPortal(
        <AnimatePresence>
          {open && (
            <div className="menu-layer" key="layer">
              <motion.div className="menu-scrim" onClick={() => close(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
              <motion.aside className="menu-panel" role="dialog" aria-modal="true" aria-label={t("menu.open")} ref={panel}
                initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", stiffness: 380, damping: 32 }}>
                <div className="md-head">
                  <span className={`rolebadge ${role}`}><i aria-hidden="true" />{tl("role", role)}</span>
                  <motion.button type="button" className="md-x" aria-label={t("menu.close")} onClick={() => close(true)} whileTap={{ scale: 0.94 }}>
                    <Mini><path d="M6 6l12 12M18 6 6 18" /></Mini>
                  </motion.button>
                </div>

                <motion.nav className="md-nav" variants={list} initial="hidden" animate="show" aria-label={t("menu.features")}>
                  {groups.map((g) => (
                    <motion.div key={g.id} variants={row} className="md-group">
                      <p className="md-h">{t(`menu.group.${g.id}`)}</p>
                      <ul>
                        {g.items.map((k) => { const it = itemOf(k); const on = it.tab === tab && (!it.sec || it.sec === sec); return (
                          <motion.li key={k} variants={row}>
                            <motion.button type="button" className={`md-item${on ? " on" : ""}`} aria-current={on ? "page" : undefined}
                              whileHover="hover" whileTap={{ scale: 0.98 }} onClick={() => { onPick(it.tab, it.sec); close(true); }}>
                              {on && <motion.span layoutId="activeNavIndicator" className="md-active" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
                              <motion.span className="md-ico" variants={{ hover: { x: 3 } }}><Icon name={it.ico} /></motion.span>
                              <motion.span className="md-label" variants={{ hover: { x: 3 } }}>{it.label}</motion.span>
                            </motion.button>
                          </motion.li>); })}
                      </ul>
                    </motion.div>))}
                </motion.nav>

              </motion.aside>
            </div>)}
        </AnimatePresence>, target)}
    </MotionConfig>
  );
}

/** Top-bar lock for students and parents. Amber = the signing key is locked (approving a payment needs it); teal = unlocked.
    The key lives only in this browser, wrapped with the passcode, so unlocking asks for the passcode again after a reload.
    The popover is the same unlock the old page card did: unlock the key, then register its public half if the server lacks it. */
export function KeyLock({ role, dev, onUnlocked, demoPass }) {
  const [open, setOpen] = useState(false);
  const [pass, setPass] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const off = (e) => { if (!box.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", off); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  useEffect(() => { if (open && !dev) setPass(demoPass || ""); }, [open, dev, demoPass]);   // demo build: the public demo passcode is typed in for you
  const unlock = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const d = await unlockDevice(role, pass);
      const me = await api("/auth/me");
      if (me.device_key?.key_id !== d.keyId) await api("/device/register", { public_key: d.publicKey });
      setPass(""); setOpen(false); onUnlocked(d);
    } catch (x) { setErr(x instanceof ApiError ? x : new ApiError(400, t("unlock.bad"))); }
    setBusy(false);
  };
  const locked = !dev;
  const label = locked ? t("unlock.title", { role: tl("role", role) }) : t("key.unlocked");
  return (
    <span className="keylock" ref={box}>
      <button type="button" className={`keylock-btn ${locked ? "locked" : "open"}`} aria-haspopup="dialog" aria-expanded={open}
        aria-label={label} title={label} onClick={() => setOpen((v) => !v)}>
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="11" width="14" height="9" rx="2" />{locked ? <path d="M8 11V8a4 4 0 0 1 8 0v3" /> : <path d="M8 11V8a4 4 0 0 1 7.6-1.7" />}
        </svg>
      </button>
      {open && (
        <div className="keylock-pop" role="dialog" aria-label={label}>
          <b>{label}</b>
          {locked ? (
            <form onSubmit={unlock}>
              <p className="muted small">{t("unlock.text")} {t("key.same")}</p>
              <label htmlFor="key-pass">{t("unlock.label")}</label>
              <div className="pass-field">
                <input id="key-pass" type={show ? "text" : "password"} autoComplete="current-password" autoFocus value={pass} onChange={(e) => setPass(e.target.value)} />
                <button type="button" className="pass-toggle" aria-pressed={show} aria-label={show ? t("gate.hide") : t("gate.view")} title={show ? t("gate.hide") : t("gate.view")} onClick={() => setShow((v) => !v)}>
                  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />{show && <path d="M4 20 20 4" />}
                  </svg>
                </button>
              </div>
              <button type="submit" disabled={busy || !pass}>{t("unlock.btn")}</button>
              {demoPass && <p className="demo-note">{t("gate.demo")}</p>}
              <ErrorBox error={err} />
            </form>
          ) : (
            <p className="muted small">{t("app.devkey")} <code>{short4(dev.keyId)}</code></p>
          )}
          <p className="muted small keylock-note">{t("key.local")}</p>
        </div>)}
    </span>
  );
}
