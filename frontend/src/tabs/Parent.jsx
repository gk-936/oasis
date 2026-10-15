import React, { useCallback, useEffect, useState } from "react";
import { api, short4, signedApprove, useGuard } from "../api.js";
import { signConsent } from "../crypto.js";
import { DraftBox } from "../common.jsx";
import { EarnedAutonomy } from "./trustpass.jsx";
import { REGISTRY, t, tl, useLang } from "../i18n/index.js";
import { ErrorBox, Skeleton, SubNav, announce, cny, fmtDate, inr } from "../ui.jsx";

/* The page text in the language picked on this page. English and Chinese come from the interface dictionaries; Hindi has no
   interface dictionary, so the few strings this page shows around the approval cards are kept here (machine-drafted, needs
   native-speaker review). The approval cards themselves arrive already written in the picked language by the server. */
const HI = {
  "parent.title": "अभिभावक की स्वीकृतियाँ",
  "parent.empty.title": "आपके लिए कुछ भी प्रतीक्षा में नहीं है",
  "parent.empty.text": "जब Arjun कोई बड़ा ट्रांसफ़र माँगेगा, तो वह सटीक राशि और सरल भाषा में स्पष्टीकरण के साथ यहाँ दिखेगा।",
  "parent.lang.note": "स्पष्टीकरण ऑफ़लाइन टेम्पलेट से बनते हैं; लाइव मॉडल के साथ वे दोबारा लिखे जाते हैं, पर संख्याएँ वही रहनी चाहिए। शब्दों की जाँच किसी मातृभाषी से करानी चाहिए।",
};
const tx = (lang, key) => (lang === "hi" ? HI[key] : REGISTRY[lang]?.dict[key]) ?? t(key);

export function Parent({ refresh, role }) {
  const { lang: ui } = useLang();
  const [d, setD] = useState(null);
  const [pick, setPick] = useState(null);                  // null = follow the interface language (English or Chinese); Hindi is picked here
  const lang = pick ?? (ui === "zh" ? "zh" : "en");
  useEffect(() => { setPick(null); }, [ui]);               // switching the interface language (menu) resets the explanation language to follow it
  const [loadErr, setLoadErr] = useState(null);
  const [ladder, setLadder] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const isParent = role === "parent";
  const load = useCallback((l) => api(`/parent/pending?lang=${l}`).then((x) => { setD(x); setLoadErr(null); }).catch(setLoadErr), []);
  useEffect(() => { load(lang); }, [load, lang, ui]);
  useEffect(() => { if (role === "student" || role === "parent") api("/trust-pass/ladder").then(setLadder).catch(() => setLadder(null)); }, [ui, role]);
  const acceptLadder = () => run(async () => { setLadder(await api("/trust-pass/ladder/accept", {})); announce(t("ea.announce")); refresh(); });
  const act = (p, approve) => run(async () => {
    if (approve) await signedApprove("parent", p.id, p.draft); else await api("/approve", { pending_id: p.id, approve: false });
    announce(approve ? t("parent.announce.signed") : t("parent.announce.declined"));
    await load(lang); refresh();
  });
  const consent = (c) => run(async () => { await api(`/plan/${c.plan_id}/consent`, { step: c.step, ...signConsent("parent", c) }); announce(t("parent.announce.consent")); await load(lang); refresh(); });
  if (!d) return loadErr ? <ErrorBox error={loadErr} onRetry={() => load(lang)} /> : <Skeleton rows={4} />;
  return (
    <section aria-labelledby="parent-h" className="stack parent-page">
      <div className="parent-head">
        <h2 id="parent-h"><span className="ph-ico" aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 4.5 6v5.5c0 4.7 3 8 7.5 9.5 4.5-1.5 7.5-4.8 7.5-9.5V6z" /><path d="m9 12 2.2 2.2L15.5 10" /></svg></span>
          {tx(lang, "parent.title")} {d.parent && <span className="muted" style={{ fontWeight: 400 }}>— {d.parent.name}</span>}</h2>
        <span className="rolepill">{t("parent.rolepill")}</span>
      </div>
      {!isParent && (
        <div className="callout" role="note">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="8" cy="15" r="4" /><path d="m11 12 9-9M17 6l3 3M14 9l2 2" /></svg>
          <span>{t("parent.readonly")}</span>
        </div>)}
      <div>
        <div className="langrow">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" /></svg>
          <SubNav id="parentLang" label={t("parent.lang.aria")} value={lang} onChange={setPick} items={Object.entries(d.available_languages).filter(([k]) => k !== "ta").map(([k, v]) => [k, v])} />
        </div>
        <p className="muted small caption" lang={lang}>{tx(lang, "parent.lang.note")}</p>
      </div>
      <ErrorBox error={err || loadErr} onRetry={() => load(lang)} onDismiss={() => { setErr(null); setLoadErr(null); }} />
      {d.pending.length === 0 && (
        <div className="inbox-empty">
          <span className="inbox-ico" aria-hidden="true"><svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="m8 12.3 2.8 2.8L16 9.6" /></svg></span>
          <div><b lang={lang}>{tx(lang, "parent.empty.title")}</b><p className="muted" lang={lang}>{tx(lang, "parent.empty.text")}</p></div>
        </div>)}
      {d.pending.map((p) => (
        <div className="card tone-warn" key={p.id}>
          <div className="big num">{inr(p.amount_inr)} <small>({t("parent.approx")} {cny(p.amount_cny)})</small></div>
          <p lang={lang} className="lang-text">{p.explanation}</p>
          <table><tbody>{p.facts.map((f) => <tr key={f.label}><td lang={lang}>{f.label}</td><td lang={lang}>{f.value}</td></tr>)}</tbody></table>
          <p className="muted">{t("parent.approved", { list: p.approvals.map((r) => tl("role", r)).join(", ") || t("misc.none"), req: p.required.map((r) => tl("role", r)).join(" + ") })}</p>
          {Object.entries(p.signed_by || {}).map(([r, k]) => <p key={r} className="signed"><span className="sigtag">✔ {t("signed.by", { role: tl("role", r) })} <code>{short4(k)}</code></span></p>)}
          <DraftBox d={p.draft} />
          {isParent && (
            <div className="row">
              <button disabled={busy} onClick={() => act(p, true)}>{p.labels.approve} {t("parent.sign.suffix")}</button>
              <button className="ghost" disabled={busy} onClick={() => act(p, false)}>{p.labels.decline}</button>
            </div>)}
          <p className="muted" lang={lang}>{p.labels.nomove}</p>
        </div>
      ))}
      {ladder && <div className="card ea-card"><EarnedAutonomy ladder={ladder} onAccept={isParent ? acceptLadder : null} busy={busy} /></div>}
      {d.plan_consents?.length > 0 && (
        <div className="card"><h4 style={{ marginTop: 0 }}>{t("parent.consents.title")}</h4>
          {d.plan_consents.map((c) => (
            <div className="row" key={`${c.plan_id}-${c.step}`}>
              <span><b className="money">{inr(c.send_inr)}</b> {t("parent.consents.line", { date: fmtDate(c.date), plan: c.plan_id, n: c.step + 1 })}</span>
              {c.signed_by ? <span className="sigtag">✔ {t("signed.by", { role: tl("role", "parent") })} <code>{short4(c.signed_by)}</code></span>
                : isParent ? <button disabled={busy} onClick={() => consent(c)}>{t("parent.consent.btn")}</button> : <span className="sigtag waiting">{t("parent.waiting")}</span>}
            </div>))}
        </div>)}
    </section>
  );
}
