import React, { useCallback, useEffect, useState } from "react";
import { api, downloadPdf, useGuard } from "../api.js";
import { t } from "../i18n/index.js";
import { announce, cny, money, ErrorBox, Hash, Loading, Mock, Pill } from "../ui.jsx";
import { Qr } from "./trustpass.jsx";
import { qrSvg } from "../reports.js";

/* Payment Evidence Passport: one signed bundle (intent, registry payee, FlightPath reconciliation, audit-chain proof). */
const CHECKS = ["signature", "passport_hash", "key_pinned", "proof_pack", "pack_key_pinned", "claim_matches_intent", "payee_credential",
  "payee_bound", "registry_pinned", "reconciliation_recomputed", "audit_chain_linked", "payment_in_chain", "head_on_server_chain"];
const evidenceUrl = (code) => `${window.location.origin}/?evidence=${encodeURIComponent(code)}`;

export function EvidenceResult({ res }) {
  return (
    <div data-testid="evp-result">
      <p className="big">{res.ok ? <Pill status="verified">{t("evp.verify.ok")}</Pill> : <Pill status="failed">{t("evp.verify.bad")}</Pill>}</p>
      {res.claim && <p data-testid="evp-claim">
        {t("evp.claim", { amount: money(res.claim.amount, res.claim.currency), payee: res.payee?.name || res.claim.payee_id })}{" "}
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
  useEffect(() => { setRes(null); }, [initial]);
  const mine = async () => { setErr(null); try { setRes(await api("/evidence-passport/verify", initial)); announce(t("evp.announce.checked")); } catch (e) { setErr(e); setRes(null); } };
  const go = async () => {
    setErr(null);
    try { JSON.parse(text); setRes(await api("/evidence-passport/verify", text)); announce(t("evp.announce.checked")); }
    catch (e) { setErr(e instanceof SyntaxError ? new Error(t("err.badjson")) : e); setRes(null); }
  };
  return (
    <details><summary>{t("evp.paste.summary")}</summary>
      <p className="muted small">{t("evp.paste.intro")}</p>
      {initial && <div className="row"><button type="button" onClick={mine}>{t("verify.mine")}</button></div>}
      <label>{t("evp.paste.label")}<textarea rows={8} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} data-testid="evp-paste" /></label>
      <div className="row"><button className="ghost" disabled={!text.trim()} onClick={go} data-testid="evp-paste-btn">{t("evp.paste.btn")}</button></div>
      {res && <EvidenceResult res={res} />}
      {err && <ErrorBox error={err} onDismiss={() => setErr(null)} />}
    </details>
  );
}

/** Printable Evidence Passport: the facts, the reconciliation result and a link/QR so anyone can verify it online. */
function evidencePdf(p, code) {
  const c = p.claim || {}, cr = p.payee_credential || {}, f = p.reconciliation?.finding || {};
  const esc = (x) => String(x ?? "").replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[m]);
  const row = (k, v) => `<tr><th>${esc(k)}</th><td>${v}</td></tr>`;
  return `<table>
    ${row(t("evp.pdf.payment"), esc(c.intent_id))}
    ${row(t("evp.pdf.amount"), esc(money(c.amount, c.currency, 2)))}
    ${row(t("evp.pdf.payee"), `${esc(cr.name || c.payee_id)} <code>${esc(c.payee_id)}</code>`)}
    ${cr.account_ref ? row(t("evp.pdf.account"), `<code>${esc(cr.account_ref)}</code>`) : ""}
    ${row(t("evp.pdf.status"), esc(c.status ? t(`evp.status.${c.status}`) : ""))}
    ${f.detail ? row(t("evp.pdf.finding"), esc(f.detail)) : ""}
    ${p.issued_at ? row(t("evp.pdf.issued"), esc(p.issued_at)) : ""}</table>
    ${code ? `<h3>${esc(t("cp.pdf.verify"))}</h3><div class="qrbox">${qrSvg(evidenceUrl(code))}<div><p>${esc(t("evp.pdf.verify.text"))}</p><p><code>${esc(evidenceUrl(code))}</code></p></div></div>` : ""}
    <p>${esc(t("evp.pdf.fp"))}: <code>${esc(p.passport_hash || "")}</code></p>
    <p>${esc(t("evp.pdf.head"))}: <code>${esc(p.audit_head || p.audit_inclusion?.head || "")}</code></p>`;
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
  const issue = () => run(async () => { setPas(await api("/evidence-passport/issue", { intent_id: sel, outcome })); setCode(null); setStale(null); announce(t("evp.announce.issued")); });
  const [stale, setStale] = useState(null);
  // A passport the server no longer recognises (sandbox reset, restarted with new keys, or edited) cannot be shared: show which checks fail.
  const share = () => run(async () => {
    setStale(null);
    try { setCode((await api("/evidence-passport/share", { passport: pas })).code); announce(t("evp.announce.shared")); }
    catch (e) { if (e.status !== 400) throw e; setStale(await api("/evidence-passport/verify", pas)); setCode(null); }
  });
  if (!info) return <div className="card"><h3>{t("evp.title")}</h3>{err ? <ErrorBox error={err} onRetry={load} /> : <Loading />}</div>;
  return (
    <div className="card wide" data-testid="evidence-passport">
      <div className="hd"><h3>{t("evp.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p>{t("evp.pitch")}</p>
      {info.payments.length === 0 ? <p className="muted">{t("evp.none")}</p> : (
        <div className="row">
          <label className="grow">{t("evp.pick")}
            <select value={sel} onChange={(e) => setSel(e.target.value)} data-testid="evp-payment">
              {info.payments.map((p) => <option key={p.intent_id} value={p.intent_id}>{p.intent_id} · {money(p.amount, p.currency)} · {p.purpose}</option>)}
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
          <button className="ghost" onClick={() => run(async () => { const r = code ? { code } : await api("/evidence-passport/share", { passport: pas }); setCode(r.code); downloadPdf(evidencePdf(pas, r.code), `evidence-passport-${pas.claim.intent_id}`, { heading: t("evp.title"), subtitle: t("evp.pitch"), note: t("pdf.mocknote") }); })} disabled={busy}>{t("evp.download.pdf")}</button>
        </div>
        {stale && <div className="notice warn" role="alert"><div><b>{t("evp.stale.title")}</b> {t("evp.stale.text")}<EvidenceResult res={stale} /></div></div>}
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
