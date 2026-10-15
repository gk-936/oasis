import React, { useCallback, useEffect, useState } from "react";
import qrcode from "qrcode-generator";
import { api, downloadPdf, useGuard } from "../api.js";
import { esc, kpis, qrSvg, section, table } from "../reports.js";
import { t, tl, tm, tp } from "../i18n/index.js";
import { announce, cny, ErrorBox, fmtDate, Hash, inr, Loading, Mock, Pill, R } from "../ui.jsx";

/* ------------------------------------------------------------------ Oasis Trust Pass (portable payment reputation) */
const TP_CHECKS = ["signature", "key_pinned", "credential_hash", "not_expired", "disclosures_valid", "proofs_checked", "zk_valid"];
const THRESHOLD_IDS = ["on_time_pct_min", "history_months_min", "payments_min"];

/** Printable Trust Pass: what the holder chose to show, and the signed data so it can still be verified. */
function trustPassPdf(h, pres, zk, code) {
  const c = h.credential || {};
  const rows = pres.disclosures.map((d) => [tl("type", d.entry.obligation_type), cny(d.entry.amount_cny), fmtDate(d.entry.paid_date), tl("level", d.entry.payee_level || "verified_full"), d.entry.on_time ? t("rr.ontime") : t("rr.late.pill")]);
  return [
    kpis([[t("cp.pdf.shown"), String(rows.length), ""], [t("cp.pdf.valid"), fmtDate(c.valid_until), ""], [t("cp.pdf.audience"), c.audience || "—", ""]]),
    section(t("cp.pdf.payments"), rows.length ? table([t("rr.col.what"), t("rr.col.amount"), t("rr.col.paid"), t("pass.col.level"), t("rr.col.ontime")], rows, [1]) : `<p>${esc(t("cp.nopayments"))}</p>`),
    zk.length ? section(t("cp.zk.title"), `<ul>${zk.map((z) => `<li>${esc(zkText(z))}</li>`).join("")}</ul>`) : "",
    code ? section(t("cp.pdf.verify"), `<div class="qrbox">${qrSvg(verifyUrl(code))}<div><p>${esc(t("cp.pdf.verify.text"))}</p><p><code>${esc(verifyUrl(code))}</code></p></div></div>`) : "",
    section(t("cp.pdf.signed"), `<p>${esc(t("rr.fingerprint"))}: <code>${esc(c.trust_fingerprint)}</code></p>`),
  ].join("");
}

export const claimText = (c) => {
  const v = c.value || {};
  if (c.id === "no_late") return t(v.value ? "cp.claim.no_late" : "cp.claim.some_late");
  if (c.id === "volume_band") return t("cp.claim.volume_band", { band: v.band ? tm(v.band) : t("misc.na") });
  return t(`cp.claim.${c.id}`, v);
};

export const zkText = (z) => t(z.kind === "rate" ? "cp.zk.stmt.rate" : z.kind === "count" ? "cp.zk.stmt.count" : "cp.zk.stmt.bad", { k: z.k });

export const verifyUrl = (code) => `${window.location.origin}/?verify=${encodeURIComponent(code)}`;

export function Qr({ text }) {
  const q = qrcode(0, "M");
  q.addData(text);
  q.make();
  // createSvgTag builds the SVG from the module grid only; `text` never reaches the markup.
  return <div className="qr" role="img" aria-label={t("cp.qr.aria")} dangerouslySetInnerHTML={{ __html: q.createSvgTag({ cellSize: 4, margin: 2, scalable: true }) }} />;
}

/* What the landlord or bank sees: used both inside the app and on the public ?verify= page. */
export function VerifyResult({ res }) {
  return (
    <div data-testid="cp-result">
      <p className="big">{res.ok ? <Pill status="verified">{t("cp.verify.ok")}</Pill> : <Pill status="failed">{t("cp.verify.bad")}</Pill>}</p>
      {res.ok && <>
        <h4>{t("cp.verify.sees")}</h4>
        <ul className="feed">{res.claims.map((c) => <li key={c.id}>✓ {claimText(c)}</li>)}</ul>
        {res.zk_claims?.length > 0 && <>
          <h4>{t("cp.verify.zk")}</h4>
          <ul className="feed" data-testid="cp-zk-claims">{res.zk_claims.map((z, i) => <li key={i}>{z.verified ? "✓" : "✗"} {zkText(z)}</li>)}</ul>
        </>}
        <p className="muted small">{t("cp.verify.counts", { shown: res.revealed.length, hidden: res.hidden })}{res.audience ? ` · ${t("cp.audience.is", { a: res.audience })}` : ""} · {t("cp.valid", { date: fmtDate(res.valid_until) })}</p>
        {res.revealed.length > 0 && <ul className="feed">{res.revealed.map((e) => (
          <li key={e.proof_id}>{tl("type", e.obligation_type)} · {cny(e.amount_cny)} · {fmtDate(e.paid_date)} · {e.on_time ? t("rr.ontime") : t("rr.late.pill")}</li>))}</ul>}
      </>}
      <ul className="feed" data-testid="cp-checks">{TP_CHECKS.filter((k) => k !== "zk_valid" || res.zk_claims?.length > 0).map((k) => (
        <li key={k}>{res[k] === true ? "✓" : res[k] === false ? "✗" : "–"} {t(`cp.check.${k}`)}{res[k] == null ? ` ${t("rr.notchecked")}` : ""}</li>))}</ul>
    </div>
  );
}

function PasteVerify({ initial }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const sig = initial ? JSON.stringify(initial) : "";
  useEffect(() => { setRes(null); }, [sig]);
  const mine = async () => { setBusy(true); setErr(null); try { setRes(await api("/trust-pass/verify", initial)); announce(t("cp.announce.checked")); } catch (e) { setErr(e); setRes(null); } finally { setBusy(false); } };
  const go = async () => {
    setBusy(true); setErr(null);
    // Accepts the pass itself (JSON), or the verification link / share code printed in the PDF. A bare key or fingerprint is not enough.
    const x = text.trim();
    try {
      if (x.startsWith("{")) { JSON.parse(x); setRes(await api("/trust-pass/verify", x)); }
      else {
        const code = (/[?&]verify=([^&#\s]+)/.exec(x)?.[1] && decodeURIComponent(/[?&]verify=([^&#\s]+)/.exec(x)[1])) || (/^[A-Za-z0-9_-]{6,32}$/.test(x) ? x : null);
        if (!code) throw new Error(t("cp.verify.notpass"));
        setRes(await api(`/trust-pass/check/${encodeURIComponent(code)}`));
      }
      announce(t("cp.announce.checked"));
    }
    catch (e) { setErr(e instanceof SyntaxError ? new Error(t("err.badjson")) : e); setRes(null); }
    finally { setBusy(false); }
  };
  return (
    <details><summary>{t("cp.verify.summary")}</summary>
      <p className="muted small">{t("cp.verify.intro")}</p>
      {initial && <div className="row"><button type="button" disabled={busy} onClick={mine}>{t("verify.mine")}</button></div>}
      <label className="filepick">{t("cp.verify.file")}
        <input type="file" accept=".json,application/json" onChange={(e) => { const f = e.target.files?.[0]; if (f) f.text().then((x) => { setText(x); setRes(null); setErr(null); }); }} /></label>
      <details className="rawbox"><summary>{t("cp.verify.raw")}</summary>
        <label>{t("cp.verify.label")}<textarea rows={8} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} data-testid="cp-verify-text" /></label></details>
      {text.trim() && <p className="muted small">{t("cp.verify.loaded", { n: text.length })}</p>}
      <div className="row"><button className="ghost" disabled={busy || !text.trim()} onClick={go} data-testid="cp-verify-btn">{t("cp.verify.btn")}</button></div>
      {res && <VerifyResult res={res} />}
      {err && <ErrorBox error={err} onDismiss={() => setErr(null)} />}
    </details>
  );
}

export function TrustPass() {
  const [info, setInfo] = useState(null);
  const [pick, setPick] = useState({ on_time_all: true, verified_payees: true, no_late: true });
  const [th, setTh] = useState({});
  const [audience, setAudience] = useState("");
  const [holder, setHolder] = useState(null);
  const [reveal, setReveal] = useState({});
  const [shared, setShared] = useState(null);
  const [zkProofs, setZkProofs] = useState([]);
  const [zkPct, setZkPct] = useState(90);
  const [zkMin, setZkMin] = useState(2);
  const { busy, err, setErr, run } = useGuard();
  const load = useCallback(() => api("/trust-pass/claims").then(setInfo).catch(setErr), [setErr]);
  useEffect(() => { load(); }, [load]);
  // Credit growth pre-fills the form with the evidence an opportunity needs; the student still reviews and issues it.
  useEffect(() => {
    const on = (e) => { const d = e.detail; setPick(Object.fromEntries(d.claims.map((c) => [c, true]))); setTh(d.thresholds || {}); setAudience(d.audience || ""); setHolder(null); document.querySelector('[data-testid="trust-pass"]')?.scrollIntoView({ behavior: "smooth" }); };
    window.addEventListener("oasis:tp-prefill", on);
    return () => window.removeEventListener("oasis:tp-prefill", on);
  }, []);
  const issue = () => run(async () => {
    const claims = Object.keys(pick).filter((k) => pick[k] && (!THRESHOLD_IDS.includes(k) || th[k]));
    const h = await api("/trust-pass/issue", { claims, thresholds: th, audience: audience.trim() || null });
    setHolder(h); setReveal({}); setShared(null); setZkProofs([]); announce(t("cp.announce.issued"));
  });
  const presentation = holder && { credential: holder.credential, disclosures: holder.disclosures.filter((_, i) => reveal[i]),
    ...(zkProofs.length ? { zk_proofs: zkProofs } : {}) };
  // Zero-knowledge threshold: the server builds the proof from the openings only this student holds; it refuses a false claim.
  const addZk = (kind, k) => run(async () => {
    const p = await api("/trust-pass/zk-prove", { credential: holder.credential, openings: holder.zk_openings, kind, k });
    setZkProofs((cur) => [...cur.filter((x) => !(x.kind === kind && x.k === k)), p].slice(0, 6)); setShared(null); announce(t("cp.announce.zk"));
  });
  const share = () => run(async () => { const r = await api("/trust-pass/share", { presentation }); setShared(r); announce(t("cp.announce.shared")); });
  if (!info) return <div className="card"><h3>{t("cp.title")}</h3>{err ? <ErrorBox error={err} onRetry={load} /> : <Loading />}</div>;
  // a ratio over zero payments ("rent 0 of 0") or zero months is not worth claiming
  const exact = info.claims.filter((c) => !(c.value?.of === 0 || (c.id === "history_months" && !c.value.months) || (c.id === "volume_band" && !c.value.band)));
  return (
    <div className="card wide" data-testid="trust-pass">
      <div className="hd"><h3>{t("cp.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p>{R("cp.pitch")}</p>
      <ul className="feed">{["cp.diff.1", "cp.diff.2", "cp.diff.3"].map((k) => <li key={k}>{R(k)}</li>)}</ul>
      <h4>{t("cp.step1")}</h4>
      <ul className="choices">{exact.map((c) => (
        <li key={c.id}><label className="check"><input type="checkbox" checked={!!pick[c.id]} onChange={(e) => setPick({ ...pick, [c.id]: e.target.checked })} data-testid={`cp-claim-${c.id}`} /> {claimText(c)}</label></li>))}</ul>
      <p className="muted small">{t("cp.threshold.intro")}</p>
      <ul className="choices">{THRESHOLD_IDS.map((id) => (
        <li key={id}><label className="check"><input type="checkbox" checked={!!pick[id]} onChange={(e) => setPick({ ...pick, [id]: e.target.checked })} data-testid={`cp-claim-${id}`} /> {t(`cp.threshold.${id}`)}</label>{" "}
          {info.thresholds[id].some((o) => o.met)
            ? <select aria-label={t(`cp.threshold.${id}`)} value={th[id] ?? ""} onChange={(e) => setTh({ ...th, [id]: e.target.value ? +e.target.value : undefined })}>
              <option value="">–</option>
              {info.thresholds[id].map((o) => <option key={o.at_least} value={o.at_least} disabled={!o.met}>{o.at_least}{o.met ? "" : ` (${t("cp.threshold.notmet")})`}</option>)}
            </select>
            : <span className="muted small">{t("cp.threshold.unavailable")}</span>}</li>))}</ul>
      <div className="row">
        <label className="grow">{t("cp.audience")}<input value={audience} maxLength={80} placeholder={t("cp.audience.ph")} onChange={(e) => setAudience(e.target.value)} /></label>
        <button disabled={busy || !Object.values(pick).some(Boolean)} onClick={issue} style={{ alignSelf: "flex-end" }} data-testid="cp-issue">{t("cp.issue")}</button>
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {info.suggested_asks.length > 0 && <>
        <h4>{t("cp.asks")}</h4>
        <ul className="feed">{info.suggested_asks.map((a) => <li key={a}>{t(`cp.ask.${a}`)}</li>)}</ul>
        <p className="muted small">{t("cp.asks.note")}</p>
      </>}
      {holder && <>
        <h4>{t("cp.step2")}</h4>
        <p className="muted small">{t("cp.step2.note", { days: info.valid_days })}</p>
        {holder.disclosures.length === 0 ? <p className="muted">{t("cp.nopayments")}</p> : (
          <ul className="reveal-list" aria-label={t("cp.step2")}>{holder.disclosures.map((d, i) => (
            <li key={i}>
              <label className="reveal-main">
                <input type="checkbox" checked={!!reveal[i]} onChange={(e) => { setReveal({ ...reveal, [i]: e.target.checked }); setShared(null); }} />
                <span><b>{tl("type", d.entry.obligation_type)}</b> <span className="money">{cny(d.entry.amount_cny)}</span>
                  <span className="muted small"> · {t("rr.col.paid")} {fmtDate(d.entry.paid_date)}</span></span>
              </label>
              <span className="reveal-pills">
                <Pill status={d.entry.payee_level || "verified"}>{tl("level", d.entry.payee_level || "verified_full")}</Pill>
                <Pill status={d.entry.on_time ? "paid" : "frozen"}>{d.entry.on_time ? t("rr.ontime") : t("rr.late.pill")}</Pill>
              </span>
            </li>))}</ul>)}
        <p className="muted small">{t("cp.sharing", { shown: presentation.disclosures.length, hidden: holder.disclosures.length - presentation.disclosures.length })} · {t("rr.fingerprint")} <Hash value={holder.credential.trust_fingerprint} n={12} what={t("hash.fingerprint")} /></p>
        <h4>{t("cp.zk.title")}</h4>
        <p className="muted small">{t("cp.zk.note")}</p>
        {holder.zk_openings ? <>
          <div className="row">
            <label>{t("cp.zk.rate")}<input type="number" min={1} max={100} value={zkPct} onChange={(e) => setZkPct(+e.target.value)} data-testid="cp-zk-pct" /></label>
            <button className="ghost" disabled={busy || !(zkPct >= 1 && zkPct <= 100)} onClick={() => addZk("rate", zkPct)} style={{ alignSelf: "flex-end" }} data-testid="cp-zk-add-rate">{t("cp.zk.add")}</button>
            <label>{t("cp.zk.count")}<input type="number" min={1} value={zkMin} onChange={(e) => setZkMin(+e.target.value)} data-testid="cp-zk-min" /></label>
            <button className="ghost" disabled={busy || !(zkMin >= 1)} onClick={() => addZk("count", zkMin)} style={{ alignSelf: "flex-end" }} data-testid="cp-zk-add-count">{t("cp.zk.add")}</button>
          </div>
          {zkProofs.length === 0 ? <p className="muted small">{t("cp.zk.none")}</p> : (
            <ul className="feed" data-testid="cp-zk-list">{zkProofs.map((z) => (
              <li key={`${z.kind}-${z.k}`}>✓ {zkText(z)}{" "}<button className="ghost" onClick={() => { setZkProofs(zkProofs.filter((x) => x !== z)); setShared(null); }}>{t("cp.zk.remove")}</button></li>))}</ul>)}
        </> : <p className="muted small">{t("cp.zk.nocommit")}</p>}
        <h4>{t("cp.step3")}</h4>
        <div className="row">
          <button disabled={busy} onClick={share} data-testid="cp-share">{t("cp.share")}</button>
          <button className="ghost" disabled={busy} onClick={() => run(async () => { const r = shared || await api("/trust-pass/share", { presentation }); setShared(r); downloadPdf(trustPassPdf(holder, presentation, zkProofs, r.code), "oasis-trust-pass", { heading: t("cp.title"), subtitle: t("cp.pitch").replace(/\*\*|`/g, ""), note: t("pdf.mocknote") }); })} data-testid="cp-download">{t("cp.download")}</button>
        </div>
        {shared && (
          <div className="qr-box" data-testid="cp-qr">
            <Qr text={verifyUrl(shared.code)} />
            <div>
              <p>{t("cp.qr.text")}</p>
              <p className="small"><a href={verifyUrl(shared.code)} target="_blank" rel="noreferrer">{verifyUrl(shared.code)}</a></p>
              <p className="muted small">{t("cp.qr.note", { date: fmtDate(shared.valid_until) })}</p>
            </div>
          </div>)}
      </>}
      <PasteVerify initial={presentation} />
      <EarnedAutonomy ladder={info.ladder} />
    </div>
  );
}

/* ------------------------------------------------------------------ public page opened by the QR: no login */
export function VerifyPage({ code }) {
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => { api(`/trust-pass/check/${encodeURIComponent(code)}`).then(setRes).catch(setErr); }, [code]);
  useEffect(() => { document.title = `${t("cp.public.title")} · Oasis`; }, []);
  return (
    <main id="main" className="app" style={{ maxWidth: 640, margin: "0 auto", padding: 16 }}>
      <div className="card" data-testid="verify-page">
        <div className="hd"><h2 style={{ margin: 0 }}>{t("cp.public.title")}</h2><Mock>{t("mock.sandbox")}</Mock></div>
        <p className="muted">{t("cp.public.intro")}</p>
        {!res && !err && <Loading />}
        {err && <ErrorBox error={err.status === 404 ? new Error(t("cp.public.notfound")) : err} />}
        {res && <VerifyResult res={res} />}
        <p className="muted small">{t("cp.public.foot")}</p>
      </div>
    </main>
  );
}

/* ------------------------------------------------------------------ Earned autonomy ladder (student view; the parent accepts) */
export function EarnedAutonomy({ ladder, onAccept, busy }) {
  if (!ladder) return null;
  const need = ladder.next ? ladder.next.needs_streak : 0;
  const pctDone = ladder.next ? Math.min(100, Math.round((ladder.streak / (need || 1)) * 100)) : 100;
  return (
    <div data-testid="earned-autonomy" className="ea">
      <h4 className="ea-title">{t("ea.title")}</h4>
      <p className="ea-status"><b>{t("ea.status", { level: ladder.level, cur: inr(ladder.current_threshold_inr) })}</b></p>
      <p className="muted small">{tp("ea.streak", ladder.streak)}</p>
      <div className="prog-track ea-prog" role="img" aria-label={tp("ea.streak", ladder.streak)}><span className="prog-fill" style={{ width: `${pctDone}%` }} /></div>
      {ladder.proposal
        ? <p><Pill status="held">{t("ea.proposal.pill")}</Pill> {t("ea.proposal", { th: inr(ladder.earned_threshold_inr) })}{" "}
          {onAccept && <button disabled={busy} onClick={onAccept} data-testid="ea-accept">{t("ea.accept")}</button>}</p>
        : ladder.next && <p className="muted small">{tp("ea.next", need - ladder.streak, { th: inr(ladder.next.threshold_inr) })}</p>}
      <ul className="tiers" aria-label={t("ea.title")}>{ladder.levels.map((l) => {
        const on = l.level <= ladder.level;
        return (
          <li key={l.level} className={on ? "on" : "locked"}>
            <span className="tier-badge">{on ? <>✓ {t("ea.unlocked")}</> : <><svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg> {t("ea.locked")}</>}</span>
            <b>{t("ea.tier", { level: l.level })}</b>
            <span className="tier-req">{t("ea.req", { n: l.needs_streak })}</span>
            <span className="tier-th">{inr(l.threshold_inr)}</span>
          </li>);
      })}</ul>
      <p className="ea-foot"><svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16v.5" /></svg>{t("ea.note")}</p>
    </div>
  );
}
