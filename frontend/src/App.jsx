import React, { useCallback, useEffect, useState } from "react";
import { deviceOf, lockDevice, unlockDevice } from "./crypto.js";
import { api, markSession, setApiHandlers, short4 } from "./api.js";
import { assertPasskey, passkeysSupported, registerPasskey } from "./passkey.js";
import { MockBanner } from "./common.jsx";
import { ROLES } from "./Landing.jsx";
import { LoginScreen } from "./LoginScreen.jsx";
import { AppMenu, KeyLock } from "./Shell.jsx";
import { Home } from "./Home.jsx";
import { HelpPage, PageHelp } from "./Help.jsx";
import { Settings } from "./Settings.jsx";
import "./polish.css";
import { DarkPattern } from "./DarkPattern.jsx";
import "./shell.css";
import { LANG_CODES, REGISTRY, getLang, hasChoice, normalizeLang, setLang as applyLang, t, tl, useLang } from "./i18n/index.js";
import { announce, Announcer, ApiError, ErrorBox, Loading, R } from "./ui.jsx";
import { FlightPath } from "./tabs/FlightPath.jsx";
import { EvidencePassport } from "./tabs/EvidencePassport.jsx";
import { Chat } from "./tabs/Chat.jsx";
import { Demo } from "./tabs/Demo.jsx";
import { Netting } from "./tabs/Netting.jsx";
import { Numbers } from "./tabs/Numbers.jsx";
import { Parent } from "./tabs/Parent.jsx";
import { Passport } from "./tabs/Passport.jsx";
import { Twin } from "./tabs/Twin.jsx";
import { Proof } from "./tabs/Proof.jsx";
import { RedTeam } from "./tabs/RedTeam.jsx";
import { BreakIt } from "./tabs/BreakIt.jsx";

// Features each role is offered, in the order the menu and the Home cards show them (the first is the one to start with).
const TABS_BY_ROLE = {
  student: ["home", "flightpath", "chat", "passport", "demo", "parent", "twin", "netting", "proof", "evp", "help", "settings"],
  parent: ["home", "parent", "proof", "help", "settings"],
  judge: ["home", "redteam", "breakit", "numbers", "flightpath", "twin", "netting", "proof", "help", "settings"],   // Break it, Numbers and Red team are evaluation tools: judge only
};
const DEFAULT_TAB = { student: "home", parent: "home", judge: "home" };

/** Language picker (login screen and header). For a logged-in student the choice is also saved in the Passport. */
function LangPicker({ role }) {
  const { lang, setLang } = useLang();
  const pick = (code) => {
    setLang(code);
    if (role === "student") api("/student/language", { language: code }).catch(() => { /* the local choice still applies */ });
  };
  return (
    <div className="seg langpick" role="group" aria-label={t("lang.aria")}>
      {LANG_CODES.map((c) => (
        <button key={c} type="button" lang={REGISTRY[c].html} aria-pressed={c === lang} onClick={() => pick(c)}>{REGISTRY[c].name}</button>))}
    </div>
  );
}

async function startSession(role, passcode) {
  const step = await api("/auth/login", { role, passcode });
  if (step.mfa_required) await assertPasskey(step);                 // second factor: the server issues no session until it verifies
  const me = await api("/auth/me");
  if (role === "student" || role === "parent") {
    const d = await unlockDevice(role, passcode);                 // private key stays in this browser
    if (me.device_key?.key_id !== d.keyId) await api("/device/register", { public_key: d.publicKey });
  }
  return me;
}

/** `role` / `setRole` come from the landing's "who are you" choice, so the card opens on the visitor's role. */
// The public demo passcodes (README, docs/agent-api.md). They are prefilled only for a role the server reports as still on its default.
const DEMO_PASS = { student: "student-demo", parent: "parent-demo", judge: "judge-demo" };

function Login({ onDone, cfg, cfgErr, retryCfg, notice, role, setRole, gate }) {
  const [pass, setPass] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);          // the "View" button reveals the passcode while on
  const go = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { onDone(await startSession(role, pass)); } catch (x) { setErr(x); }
    setBusy(false);
  };
  const keys = (e) => {
    const i = ROLES.indexOf(role);
    const n = e.key === "ArrowRight" || e.key === "ArrowDown" ? ROLES[(i + 1) % 3] : e.key === "ArrowLeft" || e.key === "ArrowUp" ? ROLES[(i + 2) % 3] : null;
    if (n) { e.preventDefault(); setRole(n); e.currentTarget.querySelector(`[data-role="${n}"]`)?.focus(); }
  };
  const demoOn = !!cfg?.demo_passcodes_in_use?.includes(role);
  useEffect(() => { if (gate) setPass(demoOn ? DEMO_PASS[role] : ""); }, [gate, role, demoOn]);
  if (gate) return (
    <section className="login" aria-labelledby="login-h">
      <form className="card" onSubmit={go}>
        <h2 id="login-h" className="sr-only">{t("login.title")}</h2>
        {notice && <div className="notice warn" role="alert"><div>{t(notice)}</div></div>}
        {cfgErr && <ErrorBox error={cfgErr} onRetry={retryCfg} />}
        <div className="roles" role="radiogroup" aria-label={t("login.role.aria")} onKeyDown={keys}>
          {ROLES.map((r) => (
            <button type="button" key={r} data-role={r} role="radio" aria-checked={role === r} tabIndex={role === r ? 0 : -1}
              className={`rolebtn ${role === r ? "on" : ""}`} onClick={() => setRole(r)}>{tl("role", r)}</button>))}
        </div>
        <label htmlFor="gate-pass">{t("login.passcode", { role: tl("role", role) })}</label>
        <div className="pass-field">
          <input id="gate-pass" type={show ? "text" : "password"} autoComplete="current-password" autoFocus value={pass} onChange={(e) => setPass(e.target.value)} />
          <button type="button" className="pass-toggle" aria-pressed={show} aria-label={show ? t("gate.hide") : t("gate.view")} title={show ? t("gate.hide") : t("gate.view")} onClick={() => setShow((v) => !v)}>
            <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />{show && <path d="M4 20 20 4" />}
            </svg>
          </button>
        </div>
        <div className="row"><button type="submit" disabled={busy || !pass}>{t("login.submit", { role: tl("role", role) })}</button>{busy && <Loading>{t("login.signingin")}</Loading>}</div>
        {demoOn && <p className="demo-note">{t("gate.demo")}</p>}
        {err && <ErrorBox error={err.status === 401 ? new ApiError(401, t("login.wrong")) : err} />}
      </form>
    </section>
  );
  return (
    <section className="login" aria-labelledby="login-h">
      <div className="card">
        <div className="login-lang"><LangPicker role={null} /></div>
        <h2 id="login-h">{t("login.title")}</h2>
        <p className="muted">{t("login.intro")}</p>
        {notice && <div className="notice warn" role="alert"><div>{t(notice)}</div></div>}
        {cfgErr && <ErrorBox error={cfgErr} onRetry={retryCfg} />}
        <form onSubmit={go}>
          <div className="roles" role="radiogroup" aria-label={t("login.role.aria")} onKeyDown={keys}>
            {ROLES.map((r) => (
              <button type="button" key={r} data-role={r} role="radio" aria-checked={role === r} tabIndex={role === r ? 0 : -1}
                className={`rolebtn ${role === r ? "on" : ""}`} onClick={() => setRole(r)}>
                <b>{tl("role", r)}</b><span>{t(`role.${r}.desc`)}</span></button>))}
          </div>
          <label>{t("login.passcode", { role: tl("role", role) })}
            <input type="password" autoComplete="current-password" value={pass} onChange={(e) => setPass(e.target.value)} /></label>
          <div className="row"><button type="submit" disabled={busy || !pass}>{t("login.submit", { role: tl("role", role) })}</button>{busy && <Loading>{t("login.signingin")}</Loading>}</div>
        </form>
        {err && <ErrorBox error={err.status === 401 ? new ApiError(401, t("login.wrong")) : err} />}
        {cfg?.demo_passcodes_in_use?.length > 0 && <p className="hint">{R("login.demo")}</p>}
        <p className="hint">{R("login.devicekey")}</p>
      </div>
    </section>
  );
}

export default function App() {
  const { lang } = useLang();
  const [auth, setAuth] = useState(undefined);     // undefined = checking, null = logged out, {role,...}
  const [cfg, setCfg] = useState(null);
  const [cfgErr, setCfgErr] = useState(null);
  const [notice, setNotice] = useState(null);      // a dictionary key, so it follows a language switch
  const [dev, setDev] = useState(null);
  const [scrolled, setScrolled] = useState(false);   // the top bar is transparent until the page scrolls under it
  const [tab, setTab] = useState("home");
  const [s, setS] = useState(null);
  const [err, setErr] = useState(null);
  const [proofSel, setProofSel] = useState(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [passSec, setPassSec] = useState("treasury");
  const [corr, setCorr] = useState(null);
  setApiHandlers({
    unauth: (status) => { setAuth(null); setS(null); setNotice(status === 403 ? "notice.role" : "notice.ended"); },
    expired: () => { api("/state").then(setS).catch(() => {}); },
  });
  const loadCfg = useCallback(() => { api("/auth/config").then((c) => { setCfg(c); setCfgErr(null); }).catch(setCfgErr); }, []);
  // The interface language and the student's saved language (Passport) agree: an explicit local choice is saved to the server,
  // otherwise the saved one is adopted.
  const syncLanguage = useCallback((me) => {
    if (me?.role !== "student") return;
    const saved = normalizeLang(me.language);
    if (hasChoice()) { if (saved !== getLang()) api("/student/language", { language: getLang() }).catch(() => {}); }
    else if (saved && saved !== getLang()) applyLang(saved);
  }, []);
  useEffect(() => {
    loadCfg();
    // /auth/me answers 200 {"role": null} when logged out, so the probe is not an error and a cold visit logs nothing.
    api("/auth/me").then((me) => {
      if (!me?.role) { markSession(false); setAuth(null); return; }
      setAuth(me); setDev(deviceOf(me.role)); setTab(DEFAULT_TAB[me.role]); syncLanguage(me);
    }).catch(() => { markSession(false); setAuth(null); });
  }, [loadCfg, syncLanguage]);
  const refresh = useCallback(() => api("/state").then((x) => { setS(x); setErr(null); }).catch((e) => { if (e.status !== 401 && e.status !== 403) setErr(e); }), []);
  useEffect(() => { if (auth) refresh(); }, [refresh, tab, auth, lang]);
  useEffect(() => { document.title = auth ? `${t(`tab.${tab}`)} · Oasis` : "Oasis"; }, [tab, auth, lang]);
  useEffect(() => {
    const f = () => setScrolled(window.scrollY > 8);
    f(); addEventListener("scroll", f, { passive: true });
    return () => removeEventListener("scroll", f);
  }, []);
  useEffect(() => { setHelpOpen(false); }, [tab]);
  const pick = (k, sec, c) => { if (sec) setPassSec(sec); setCorr(c || null); setTab(k); };
  const openProof = (id) => { setProofSel(id); setTab("proof"); };
  const loggedIn = (me) => { markSession(true); setNotice(null); setAuth(me); setDev(deviceOf(me.role)); setTab(DEFAULT_TAB[me.role]); syncLanguage(me); announce(t("app.loggedin", { role: tl("role", me.role) })); };
  const loginCard = (p) => <Login {...p} onDone={loggedIn} cfg={cfg} cfgErr={cfgErr} retryCfg={loadCfg} notice={notice} />;
  const logout = async () => { try { await api("/auth/logout", {}); } catch { /* already gone */ } if (auth) lockDevice(auth.role); markSession(false); setAuth(null); setS(null); setDev(null); setNotice(null); };
  const needsKey = auth && (auth.role === "student" || auth.role === "parent");
  const tabs = auth ? TABS_BY_ROLE[auth.role] : [];
  const view = auth && tabs.includes(tab) ? tab : auth ? DEFAULT_TAB[auth.role] : tab;   // never render a feature the role does not own
  return (
    <div className={auth ? `shell${view === "chat" ? " fit" : ""}` : undefined}>
      {auth && <DarkPattern />}
      <a className="skip" href="#main">{t("app.skip")}</a>
      <Announcer />
      {auth && <header className={`shell-top${scrolled ? " scrolled" : ""}`}>
        <div className="shell-top-in">
          <span className="shell-brand"><img src="/oasis-logo.svg" alt="Oasis" draggable="false" /></span>
          {view !== "home" && <span className="shell-crumb"><span>{t(`tab.${view}`)}</span></span>}
          <span className="shell-spacer" />
          <PageHelp tab={view} open={helpOpen} onToggle={() => setHelpOpen((v) => !v)} onClose={() => setHelpOpen(false)} onAll={() => { setHelpOpen(false); setTab("help"); }} />
          {needsKey && <KeyLock role={auth.role} dev={dev} onUnlocked={setDev} demoPass={cfg?.demo_passcodes_in_use?.includes(auth.role) ? DEMO_PASS[auth.role] : null} />}
          <AppMenu tabs={tabs} tab={view} sec={passSec} onPick={pick} role={auth.role} />
        </div>
      </header>}
      <div className="app">
        <main id="main" tabIndex={-1}>
          {auth === undefined && <Loading>{t("app.checking")}</Loading>}
          {auth === null && <LoginScreen notice={notice} langPicker={<LangPicker role={null} />} renderLogin={loginCard} />}
          {auth && (<>
            <ErrorBox error={err} onRetry={refresh} />
            {view === "home" && <Home role={auth.role} tabs={tabs} roleTabs={TABS_BY_ROLE} onOpen={pick} s={s} refresh={refresh} />}
            {view === "demo" && <Demo refresh={refresh} openProof={openProof} />}
            {view === "chat" && <Chat refresh={refresh} openProof={openProof} s={s} onBack={() => setTab("home")} />}
            {view === "passport" && <Passport s={s} refresh={refresh} sec={passSec} onSec={setPassSec} />}
            {view === "parent" && <Parent refresh={refresh} role={auth.role} />}
            {view === "redteam" && <RedTeam onProof={openProof} />}
            {view === "breakit" && <BreakIt />}
            {view === "proof" && <Proof s={s} selected={proofSel} />}
            {view === "numbers" && <Numbers />}
            {view === "flightpath" && <FlightPath />}
            {view === "netting" && <Netting />}
            {view === "twin" && <Twin />}
            {view === "evp" && <EvidencePassport />}
            {view === "settings" && <Settings role={auth.role} onLogout={logout}
              onPasskey={passkeysSupported() ? () => registerPasskey().then(() => announce(t("app.passkey.done"))).catch((x) => setErr(x)) : null}
              onReset={auth.role === "student" ? () => api("/reset", {}).then(() => { announce(t("app.reset.announce")); refresh(); }).catch(setErr) : null} />}
            {view === "help" && <HelpPage role={auth.role} tabs={tabs} onOpen={setTab} />}
          </>)}
        </main>
        {auth && <MockBanner note={s?.mock_note} />}
        <footer>{t("app.footer")}</footer>
      </div>
    </div>
  );
}
