import React, { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import Globe from "./Globe.jsx";
import { ROLES, storedRole, saveRole } from "./Landing.jsx";
import { t } from "./i18n/index.js";
import "./gate.css";

/** First screen for a logged-out visitor. The planet sits fully on the right; the Oasis name and one "Log in" button sit in
    the left half, with the language switch top right. Clicking the button slides the name up and opens the login card beneath it; the planet does not move.
    `renderLogin` returns the existing Login card (App owns the session logic), so passcodes, device keys and role checks are
    unchanged. The role chosen here only preselects the card; a role string grants nothing. */
export function LoginScreen({ renderLogin, langPicker, notice }) {
  const [role, setRoleState] = useState(() => storedRole() || "student");
  const [open, setOpen] = useState(!!notice);            // a "session ended" notice opens the card straight away
  const setRole = (r) => { if (ROLES.includes(r)) { setRoleState(r); saveRole(r); } };
  useEffect(() => {
    if (!open) return undefined;
    const esc = (e) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [open]);
  const spring = { type: "spring", stiffness: 190, damping: 26 };
  return (
    <MotionConfig reducedMotion="user">
      <div className="gate">
        <Globe />
        <div className="gate-lang">{langPicker}</div>
        <div className="gate-panel">
          <motion.h1 layout="position" transition={spring} className="gate-brand"><img src="/oasis-logo.svg" alt="Oasis" draggable="false" /></motion.h1>
          <AnimatePresence mode="popLayout" initial={false}>
            {open ? (
              <motion.div key="card" className="gate-slot" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8, transition: { duration: 0.14 } }} transition={{ ...spring, delay: 0.05 }}>
                {renderLogin({ role, setRole, gate: true })}
                <button type="button" className="gate-cancel" onClick={() => setOpen(false)}>{t("gate.cancel")}</button>
              </motion.div>
            ) : (
              <motion.div key="enter" className="gate-slot" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: 0.12 } }} transition={{ duration: 0.3 }}>
                <button type="button" className="gate-enter" onClick={() => setOpen(true)}>{t("land.nav.login")}</button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <p className="gate-foot" role="note">{t("gate.mock")}</p>
      </div>
    </MotionConfig>
  );
}
