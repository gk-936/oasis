import React, { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "motion/react";
import { t, tl } from "./i18n/index.js";

/* In-app help. The text lives in the dictionaries (help.<feature>.what / .s1-.s3), so it follows the interface language.
   Every feature entry carries a link that opens that page. */
const Q = <><circle cx="12" cy="12" r="9" /><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1.9-1.1 1.8M12 17v.2" /></>;
export const HelpIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{Q}</svg>
);

function Guide({ k, onOpen, compact }) {
  return (
    <article className={`help-guide${compact ? " compact" : ""}`}>
      <h3>{t(`tab.${k}`)}</h3>
      <p>{t(`help.${k}.what`)}</p>
      <p className="help-how">{t("help.how")}</p>
      <ol>{[1, 2, 3].map((n) => <li key={n}>{t(`help.${k}.s${n}`)}</li>)}</ol>
      {onOpen && <button type="button" className="help-link" onClick={() => onOpen(k)}>{t("help.open", { page: t(`tab.${k}`) })} →</button>}
    </article>
  );
}

/** The Help page from the menu: what the logged-in role can do, then one guide per feature the role owns, each with a link to it. */
export function HelpPage({ role, tabs, onOpen }) {
  const features = tabs.filter((k) => k !== "home" && k !== "help" && k !== "settings");
  return (
    <section className="stack help-page" aria-labelledby="help-h">
      <div>
        <h2 id="help-h">{t("help.title")}</h2>
        <p className="lead">{t(`help.role.${role}`)}</p>
      </div>
      <nav className="help-toc" aria-label={t("help.toc")}>
        {features.map((k) => <a key={k} href={`#help-${k}`} onClick={(e) => { e.preventDefault(); document.getElementById(`help-${k}`)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{t(`tab.${k}`)}</a>)}
      </nav>
      <div className="help-grid">
        {features.map((k) => <div key={k} id={`help-${k}`}><Guide k={k} onOpen={onOpen} /></div>)}
      </div>
      <p className="muted small">{t("help.role.note", { role: tl("role", role) })}</p>
    </section>
  );
}

/** The "?" in the top bar: a short guide to the page that is open, with a link to the full help. */
export function PageHelp({ tab, open, onToggle, onClose, onAll }) {
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const off = (e) => { if (!box.current?.contains(e.target)) onClose(); };
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("pointerdown", off); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", off); document.removeEventListener("keydown", esc); };
  }, [open, onClose]);
  if (["home", "help", "settings"].includes(tab)) return null;
  return (
    <span className="pagehelp" ref={box}>
      <button type="button" className="help-btn" aria-haspopup="dialog" aria-expanded={open} aria-label={t("help.page", { page: t(`tab.${tab}`) })} title={t("help.page", { page: t(`tab.${tab}`) })} onClick={onToggle}>
        <HelpIcon /><span>{t("help.btn")}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="pagehelp-pop" role="dialog" aria-label={t("help.page", { page: t(`tab.${tab}`) })}
            initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.16 }}>
            <Guide k={tab} compact />
            <button type="button" className="help-link" onClick={onAll}>{t("help.all")} →</button>
          </motion.div>)}
      </AnimatePresence>
    </span>
  );
}
