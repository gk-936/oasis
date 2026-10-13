import React, { useCallback, useEffect, useState } from "react";
import { api, downloadJson, useGuard } from "../api.js";
import { t } from "../i18n/index.js";
import { announce, cny, ErrorBox, Hash, Loading, Mock, Pill } from "../ui.jsx";
import { Qr } from "./trustpass.jsx";

/* Payment Evidence Passport: one signed bundle (intent, registry payee, FlightPath reconciliation, audit-chain proof). */
const CHECKS = ["signature", "passport_hash", "key_pinned", "proof_pack", "pack_key_pinned", "claim_matches_intent", "payee_credential",
  "payee_bound", "registry_pinned", "reconciliation_recomputed", "audit_chain_linked", "payment_in_chain", "head_on_server_chain"];
const evidenceUrl = (code) => `${window.location.origin}/?evidence=${encodeURIComponent(code)}`;

export function EvidenceResult({ res }) {
  return (
    <div data-testid="evp-result">
      <p className="big">{res.ok ? <Pill status="verified">{t("evp.verify.ok")}</Pill> : <Pill status="failed">{t("evp.verify.bad")}</Pill>}</p>
      {res.claim && <p data-testid="evp-claim">
        {t("evp.claim", { amount: cny(res.claim.amount), payee: res.payee?.name || res.claim.payee_id })}{" "}
        <Pill status={res.status === "credited" ? "verified" : "held"}>{t(`evp.status.${res.status}`)}</Pill>
        {res.finding && <span className="muted small"> · {res.finding.detail} (MOCK)</span>}
      </p>}
      <ul className="feed" data-testid="evp-checks">{CHECKS.map((k) => (
        <li key={k}>{res[k] === true ? "✓" : res[k] === false ? "✗" : "–"} {t(`evp.check.${k}`)}{res[k] == null ? ` ${t("evp.notchecked")}` : ""}</li>))}</ul>
      {res.audit_head && <p className="muted small">{t("evp.head")} <Hash value={res.audit_head} /></p>}
    </div>
  );
}

function PasteVerify({ initial }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { if (initial) { setText(JSON.stringify(initial, null, 2)); setRes(null); } }, [initial]);
  const go = async () => {
    setErr(null);
    try { JSON.parse(text); setRes(await api("/evidence-passport/verify", text)); announce(t("evp.announce.checked")); }
    catch (e) { setErr(e instanceof SyntaxError ? new Error(t("err.badjson")) : e); setRes(null); }
  };
  return (
    <details><summary>{t("evp.paste.summary")}</summary>
      <p className="muted small">{t("evp.paste.intro")}</p>
      <label>{t("evp.paste.label")}<textarea rows={8} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} data-testid="evp-paste" /></label>
      <div className="row"><button className="ghost" disabled={!text.trim()} onClick={go} data-testid="evp-paste-btn">{t("evp.paste.btn")}</button></div>
      {res && <EvidenceResult res={res} />}
      {err && <ErrorBox error={err} onDismiss={() => setErr(null)} />}
    </details>
  );
}

export function EvidencePassport() {
  const [info, setInfo] = useState(null);
  const [sel, setSel] = useState("");
  const [outcome, setOutcome] = useState("credited");
  const [pas, setPas] = useState(null);
  const [code, setCode] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const load = useCallback(() => api("/evidence-passport/payments").then((r) => { setInfo(r); setSel((s) => s || r.payments[0]?.intent_id || ""); }).catch(setErr), [setErr]);
  useEffect(() => { load(); }, [load]);
  const issue = () => run(async () => { setPas(await api("/evidence-passport/issue", { intent_id: sel, outcome })); setCode(null); announce(t("evp.announce.issued")); });
  const share = () => run(async () => { setCode((await api("/evidence-passport/share", { passport: pas })).code); announce(t("evp.announce.shared")); });
  if (!info) return <div className="card"><h3>{t("evp.title")}</h3>{err ? <ErrorBox error={err} onRetry={load} /> : <Loading />}</div>;
  return (
    <div className="card wide" data-testid="evidence-passport">
      <div className="hd"><h3>{t("evp.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p>{t("evp.pitch")}</p>
      {info.payments.length === 0 ? <p className="muted">{t("evp.none")}</p> : (
        <div className="row">
          <label className="grow">{t("evp.pick")}
            <select value={sel} onChange={(e) => setSel(e.target.value)} data-testid="evp-payment">
              {info.payments.map((p) => <option key={p.intent_id} value={p.intent_id}>{p.intent_id} · {cny(p.amount)} · {p.purpose}</option>)}
            </select></label>
          <label>{t("evp.outcome")}
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)} data-testid="evp-outcome">
              {info.outcomes.map((o) => <option key={o} value={o}>{t(`evp.status.${o}`)} (MOCK)</option>)}
            </select></label>
          <button disabled={busy || !sel} onClick={issue} style={{ alignSelf: "flex-end" }} data-testid="evp-issue">{t("evp.issue")}</button>
        </div>)}
      <p className="muted small">{t("evp.mocknote")}</p>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {pas && <>
        <div className="row">
          <button disabled={busy} onClick={share} data-testid="evp-share">{t("evp.share")}</button>
          <button className="ghost" onClick={() => downloadJson(pas, `evidence-passport-${pas.claim.intent_id}.json`)}>{t("evp.download")}</button>
        </div>
        {code && <div data-testid="evp-qr"><Qr text={evidenceUrl(code)} /><p className="muted small">{t("evp.qr.text")}</p></div>}
        <PasteVerify initial={pas} />
      </>}
      {!pas && <PasteVerify />}
    </div>
  );
}

/* Public page opened by the QR: no login. */
export function EvidenceVerifyPage({ code }) {
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api(`/evidence-passport/check/${encodeURIComponent(code)}`).then(setRes).catch(setErr); }, [code]);
  useEffect(() => { document.title = `${t("evp.public.title")} · Oasis`; }, []);
  return (
    <main id="main" className="app" style={{ maxWidth: 640, margin: "0 auto", padding: 16 }}>
      <div className="card" data-testid="evp-verify-page">
        <div className="hd"><h2 style={{ margin: 0 }}>{t("evp.public.title")}</h2><Mock>{t("mock.sandbox")}</Mock></div>
        <p className="muted">{t("evp.public.intro")}</p>
        {!res && !err && <Loading />}
        {err && <ErrorBox error={err.status === 404 ? new Error(t("evp.public.notfound")) : err} />}
        {res && <EvidenceResult res={res} />}
        <p className="muted small">{t("evp.public.foot")}</p>
      </div>
    </main>
  );
}
