import React, { useCallback, useEffect, useState } from "react";
import { deviceOf, lockDevice, unlockDevice } from "./crypto.js";
import { api, markSession, setApiHandlers, short4 } from "./api.js";
import { assertPasskey, passkeysSupported, registerPasskey } from "./passkey.js";
import { MockBanner } from "./common.jsx";
import { LANG_CODES, REGISTRY, getLang, hasChoice, normalizeLang, setLang as applyLang, t, tl, useLang } from "./i18n/index.js";
import { announce, Announcer, ApiError, ErrorBox, Loading, R } from "./ui.jsx";
import { FlightPath } from "./tabs/FlightPath.jsx";
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

const TABS_BY_ROLE = {
  student: ["demo", "chat", "passport", "parent", "breakit", "proof", "numbers", "flightpath", "netting", "twin"],
  parent: ["parent", "proof"],
  judge: ["redteam", "breakit", "proof", "numbers", "flightpath", "netting", "twin"],
};
const DEFAULT_TAB = { student: "demo", parent: "parent", judge: "redteam" };
const ROLES = ["student", "parent", "judge"];

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

function Login({ onDone, cfg, cfgErr, retryCfg, notice }) {
  const [role, setRole] = useState("student");
  const [pass, setPass] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
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

function Unlock({ role, onUnlocked }) {
  const [pass, setPass] = useState("");
  const [err, setErr] = useState(null);
  const go = async (e) => {
    e.preventDefault();
    try {
      const d = await unlockDevice(role, pass);
      const me = await api("/auth/me");
      if (me.device_key?.key_id !== d.keyId) await api("/device/register", { public_key: d.publicKey });
      onUnlocked(d);
    } catch (x) { setErr(x instanceof ApiError ? x : new ApiError(400, t("unlock.bad"))); }
  };
  return (
    <form className="card unlock" onSubmit={go}>
      <b>{t("unlock.title", { role: tl("role", role) })}</b> {t("unlock.text")}
      <div className="row"><label className="grow">{t("unlock.label")}<input type="password" autoComplete="current-password" value={pass} onChange={(e) => setPass(e.target.value)} /></label>
        <button type="submit" disabled={!pass} style={{ alignSelf: "flex-end" }}>{t("unlock.btn")}</button></div>
      <ErrorBox error={err} />
    </form>
  );
}

const Logo = () => (
  <svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="15" fill="#4fc7d6" /><path d="M32 10c-8 10-15 17-15 27a15 15 0 0 0 30 0c0-10-7-17-15-27z" fill="#0b3a44" /><path d="M23 41c3 5 15 5 18 0" stroke="#4fc7d6" strokeWidth="3.4" fill="none" strokeLinecap="round" /></svg>
);

export default function App() {
  const { lang } = useLang();
  const [auth, setAuth] = useState(undefined);     // undefined = checking, null = logged out, {role,...}
  const [cfg, setCfg] = useState(null);
  const [cfgErr, setCfgErr] = useState(null);
  const [notice, setNotice] = useState(null);      // a dictionary key, so it follows a language switch
  const [dev, setDev] = useState(null);
  const [tab, setTab] = useState("demo");
  const [s, setS] = useState(null);
  const [err, setErr] = useState(null);
  const [proofSel, setProofSel] = useState(null);
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
  const openProof = (id) => { setProofSel(id); setTab("proof"); };
  const loggedIn = (me) => { markSession(true); setNotice(null); setAuth(me); setDev(deviceOf(me.role)); setTab(DEFAULT_TAB[me.role]); syncLanguage(me); announce(t("app.loggedin", { role: tl("role", me.role) })); };
  const logout = async () => { try { await api("/auth/logout", {}); } catch { /* already gone */ } if (auth) lockDevice(auth.role); markSession(false); setAuth(null); setS(null); setDev(null); setNotice(null); };
  const needsKey = auth && (auth.role === "student" || auth.role === "parent");
  const tabs = auth ? TABS_BY_ROLE[auth.role] : [];
  return (
    <>
      <a className="skip" href="#main">{t("app.skip")}</a>
      <Announcer />
      <header className="topbar">
        <div className="topbar-in">
          <div className="brand"><Logo /><h1>Oasis</h1></div>
          <span className="tagline">{t("app.tagline")}</span>
          <div className="right">
            {auth && <LangPicker role={auth.role} />}
            {auth && <>
              <span className={`rolebadge ${auth.role}`} title={t("app.role.title")}>{tl("role", auth.role)}</span>
              {needsKey && dev && <span className="muted small" title={t("app.devkey.title")}>{t("app.devkey")} <code>{short4(dev.keyId)}</code></span>}
              {passkeysSupported() && <button className="ghost" title={t("app.passkey.title")} onClick={() => registerPasskey().then(() => announce(t("app.passkey.done"))).catch((x) => setErr(x))}>{t("app.passkey")}</button>}
              {auth.role === "student" && <button className="ghost" onClick={() => api("/reset", {}).then(() => { announce(t("app.reset.announce")); refresh(); }).catch(setErr)}>{t("app.reset")}</button>}
              <button className="ghost" onClick={logout}>{t("app.logout")}</button>
            </>}
          </div>
        </div>
      </header>
      <MockBanner note={s?.mock_note} />
      <div className="app">
        <main id="main" tabIndex={-1}>
          {auth === undefined && <Loading>{t("app.checking")}</Loading>}
          {auth === null && <Login onDone={loggedIn} cfg={cfg} cfgErr={cfgErr} retryCfg={loadCfg} notice={notice} />}
          {auth && (<>
            <ErrorBox error={err} onRetry={refresh} />
            {needsKey && !dev && <Unlock role={auth.role} onUnlocked={setDev} />}
            <nav className="tabs" aria-label={t("app.tabs.aria")}>{tabs.map((k) => <button key={k} type="button" aria-current={k === tab ? "page" : undefined} onClick={() => setTab(k)}>{t(`tab.${k}`)}</button>)}</nav>
            {tab === "demo" && <Demo refresh={refresh} openProof={openProof} />}
            {tab === "chat" && <Chat refresh={refresh} openProof={openProof} s={s} />}
            {tab === "passport" && <Passport s={s} refresh={refresh} />}
            {tab === "parent" && <Parent refresh={refresh} role={auth.role} />}
            {tab === "redteam" && <RedTeam onProof={openProof} />}
            {tab === "breakit" && <BreakIt />}
            {tab === "proof" && <Proof s={s} selected={proofSel} />}
            {tab === "numbers" && <Numbers />}
            {tab === "flightpath" && <FlightPath />}
            {tab === "netting" && <Netting />}
            {tab === "twin" && <Twin />}
          </>)}
        </main>
        <footer>{t("app.footer")}</footer>
      </div>
    </>
  );
}
