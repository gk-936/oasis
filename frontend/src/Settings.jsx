import React from "react";
import { t, tl } from "./i18n/index.js";
import { LangToggle } from "./Shell.jsx";

const Ico = ({ children }) => (
  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);

/** Language, passkey, sandbox reset and log out: what used to crowd the bottom of the drawer. */
export function Settings({ role, onPasskey, onReset, onLogout }) {
  return (
    <section className="stack settings" aria-labelledby="set-h">
      <h2 id="set-h">{t("set.title")}</h2>
      <div className="set-grid">
        <div className="card set-card">
          <span className="set-ico"><Ico><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" /></Ico></span>
          <h3>{t("set.lang.title")}</h3>
          <p className="muted">{t("set.lang.text")}</p>
          <LangToggle role={role} />
        </div>
        {onPasskey && <div className="card set-card">
          <span className="set-ico"><Ico><circle cx="8" cy="15" r="4" /><path d="m11 12 9-9M17 6l3 3M14 9l2 2" /></Ico></span>
          <h3>{t("set.key.title")}</h3>
          <p className="muted">{t("set.key.text")}</p>
          <button type="button" className="ghost" onClick={onPasskey}>{t("app.passkey")}</button>
        </div>}
        {onReset && <div className="card set-card">
          <span className="set-ico"><Ico><path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5" /></Ico></span>
          <h3>{t("set.reset.title")}</h3>
          <p className="muted">{t("set.reset.text")}</p>
          <button type="button" className="ghost" onClick={onReset}>{t("app.reset")}</button>
        </div>}
        <div className="card set-card">
          <span className="set-ico"><Ico><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></Ico></span>
          <h3>{t("set.session.title")}</h3>
          <p className="muted">{t("set.session.text")} <span className="rolepill">{tl("role", role).toUpperCase()}</span></p>
          <button type="button" className="danger" onClick={onLogout}>{t("app.logout")}</button>
        </div>
      </div>
    </section>
  );
}
