import React, { useCallback, useEffect, useState } from "react";
import { api, short4, signedApprove, useGuard } from "../api.js";
import { signConsent } from "../crypto.js";
import { DraftBox } from "../common.jsx";
import { EarnedAutonomy } from "./trustpass.jsx";
import { t, tl, useLang } from "../i18n/index.js";
import { Empty, ErrorBox, Skeleton, announce, cny, fmtDate, inr } from "../ui.jsx";

export function Parent({ refresh, role }) {
  const { lang: ui } = useLang();
  const [d, setD] = useState(null);
  const [pick, setPick] = useState(null);                  // null = the parent's own language (Tamil), or Chinese when the interface is Chinese
  const lang = pick ?? (ui === "zh" ? "zh" : "ta");
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
    <section aria-labelledby="parent-h" className="stack">
      <div>
        <h2 id="parent-h">{t("parent.title")} {d.parent && <span className="muted" style={{ fontWeight: 400 }}>— {d.parent.name}</span>}</h2>
        {!isParent && <div className="notice info" role="note"><div>{t("parent.readonly")}</div></div>}
      </div>
      <div>
        <div className="seg" role="group" aria-label={t("parent.lang.aria")}>
          {Object.entries(d.available_languages).map(([k, v]) => <button key={k} lang={k} aria-pressed={k === lang} onClick={() => setPick(k)}>{v}</button>)}
        </div>
        <p className="muted small">{t("parent.lang.note")}</p>
      </div>
      <ErrorBox error={err || loadErr} onRetry={() => load(lang)} onDismiss={() => { setErr(null); setLoadErr(null); }} />
      {d.pending.length === 0 && <Empty title={t("parent.empty.title")}>{t("parent.empty.text")}</Empty>}
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
      {ladder && <div className="card"><EarnedAutonomy ladder={ladder} onAccept={isParent ? acceptLadder : null} busy={busy} /></div>}
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
