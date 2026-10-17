import React, { useState } from "react";
import { getLang, t, tl, tm } from "./i18n/index.js";
import { short4 } from "./api.js";
import { Hash, Pill, PipelineTrail, approvable, cny, fmtDateTime, money, needsText, parseReasons } from "./ui.jsx";

export const SAMPLE_INVOICE = `INVOICE
Payee: University X Finance Office
Payee ID: payee_univ_x
Account: 6228480000001234
Amount: CNY 30,000
Purpose: tuition
Due: 2026-11-15`;

// Fixed sample payloads: documents and payee names are data the user would paste, so they are never translated.
export const TOPUP_TEXT = ["Family top-up", "Payee: Arjun (own CNY account)", "Payee ID: payee_student_self", "Account: acct_student_cny",
  "Amount: CNY 8,000", "Purpose: family_support"].join("\n");

export const SAMPLE_ATTACK = SAMPLE_INVOICE.replace("6228480000001234", "6228480000009999") +
  "\nURGENT: our bank details changed. Pay within 24 hours.";

export function MockBanner({ note }) {
  const body = (getLang() === "en" ? note : tm(note))?.replace(/^(MOCK|模拟)[:：]\s*/, "") || t("mock.banner.default");
  // The two technical names in the note are shown as small code pills.
  const parts = body.split(/(OASIS_ANCHOR=fisco|FISCO BCOS)/);
  return (
    <div className="mockbar" role="note">
      <div className="mockbar-in">
        <span className="mock-env">{t("mock.env")}</span>
        <p><b>{t("mock.banner.lead")}</b> {parts.map((x, k) => (k % 2 ? <code key={k} className="mock-pill">{x}</code> : x))}</p>
      </div>
    </div>
  );
}

// Provenance of the INR->CNY figure: live (real ECB reference rate), STALE (live, last refresh failed) or MOCK.
export function RateBadge({ rates, rate }) {
  const mode = !rates ? "mock" : rates.mode === "live" ? (rates.stale ? "stale" : "live") : "mock";
  let text;
  if (getLang() === "en") text = rates?.label || `INR→CNY ${rate} (offline fallback, not a market rate)`;
  else if (mode === "mock") text = t("rate.label.mock", { rate: Number(rates?.rate ?? rate).toFixed(4) });
  else text = t("rate.label.live", { rate: Number(rates.rate).toFixed(4), stale: rates.stale ? t("rate.label.stale") : "", source: tl("rate.src", rates.source), asof: rates.as_of, time: (rates.fetched_at || "").slice(11, 16) });
  return (
    <span className={`ratebadge ${mode}`} data-testid="rate-badge" title={tm(rates?.spreads_and_fees)}>
      <span className="mode">{t(`rate.mode.${mode}`)}</span>{text}
    </span>
  );
}

export function Card({ card, mismatch }) {
  if (!card) return null;
  return (
    <div className={`card inner why ${card.action}`}>
      <strong>{card.title}</strong>
      <p>{card.text}</p>
      {card.uncertainty?.length > 0 && <p className="muted small"><strong>{t("card.unknown")}</strong> {card.uncertainty.join("; ")}.</p>}
      {card.next_step && <p className="muted small"><strong>{t("card.next")}</strong> {card.next_step}</p>}
      {mismatch?.length > 0 && mismatch.map((m, i) => (
        <p key={i} className="mismatch"><span className="mm-l">{t("plain.got")}</span> <code className="mm bad">{m.got}</code> <span className="mm-l">{t("plain.signed")}</span> <code className="mm ok">{m.signed}</code></p>))}
      <small className="muted">{t("card.rule")} <code>{card.rule}</code></small>
    </div>
  );
}

export function Signed({ approvals }) {
  if (!approvals?.length) return null;
  return <p className="signed">{approvals.map((a) => (
    <span key={a.role} className="sigtag" title={t("signed.title", { sig: a.signature?.slice(0, 16) })}>
      ✔ {t("signed.by", { role: tl("role", a.role) })} <code>{short4(a.key_id)}</code></span>))}</p>;
}

export function DuplicateWarning({ dup, onProof }) {
  if (!dup) return null;
  return (
    <div className="notice warn dupwarn" role="alert"><div><b>{t("dup.title")}</b> {dup.why}
      {dup.proof_id && onProof && <> <button type="button" className="ghost" onClick={() => onProof(dup.proof_id)}>{t("dup.open")}</button></>}</div></div>
  );
}

export function DraftBox({ d, dup }) {
  if (!d) return null;
  return (
    <details className="draftbox" open>
      <summary>{t("draft.title")}</summary>
      {dup && <p className="dupline"><b>{t("draft.dup")}</b> {dup.why} {t("draft.dup.note")}</p>}
      <dl>
        <dt>{t("draft.pay")}</dt><dd><b className="money">{money(d.amount, d.currency, 2)}</b></dd>
        <dt>{t("draft.to")}</dt><dd><code>{d.account_ref}</code> ({d.payee_id})</dd>
        <dt>{t("draft.for")}</dt><dd>{tl("purpose", d.purpose)}</dd>
        <dt>{t("draft.valid")}</dt><dd>{fmtDateTime(d.not_after)}</dd>
        <dt>{t("draft.nonce")}</dt><dd><Hash value={d.nonce} n={8} what={t("hash.nonce")} /></dd>
        <dt>{t("draft.hash")}</dt><dd><Hash value={d.draft_hash} n={12} what={t("hash.draft")} /></dd>
      </dl>
      <p className="small">{t("draft.note")}</p>
    </details>
  );
}

/** What can be done with a held payment: sign it, ask to pay a suspected duplicate again, or nothing here. */
export function ApprovalActions({ pid, draft, required, duplicate, busy, onApprove, onPayAgain, onDismiss, onProof }) {
  if (!pid) return null;
  if (required?.includes("duplicate_confirmation")) {
    return (<>
      <DuplicateWarning dup={duplicate} onProof={onProof} />
      <p className="muted small">{t("approval.dup.note")}</p>
      <div className="row">
        {onPayAgain && <button disabled={busy} onClick={() => onPayAgain(pid)}>{t("approval.payagain")}</button>}
        {onDismiss && <button className="ghost" disabled={busy} onClick={() => onDismiss(pid)}>{t("approval.dismiss")}</button>}
      </div>
    </>);
  }
  if (!approvable(required) || !onApprove) return null;
  return (<>
    {duplicate && <DuplicateWarning dup={duplicate} onProof={onProof} />}
    <DraftBox d={draft} dup={duplicate} />
    <div className="row"><button disabled={busy} onClick={() => onApprove(pid, draft)}>
      {duplicate ? t("approval.sign.again") : t("approval.sign")}</button></div>
  </>);
}

export function Outcome({ o, onApprove, onRecovery, onProof, onPayAgain, onDismiss, forensic }) {
  const [busy, setBusy] = useState(false);
  if (!o) return null;
  const f = o.fields;
  const click = async (fn, ...a) => { setBusy(true); try { await fn(...a); } finally { setBusy(false); } };
  const trace = o.trace_localized || o.trace;
  const rec = o.recovery;
  const channel = (getLang() !== "en" && rec?.verified_channel_zh) || rec?.verified_channel;
  return (
    <div className="outcome">
      <div className="outhead">
        <Pill status={o.status} />
        {f && <span className="amt">{money(f.amount, f.currency, 2)}</span>}
        {f && <span>{f.purpose ? t("out.to.purpose", { payee: f.payee_name, purpose: tl("purpose", f.purpose) }) : t("out.to", { payee: f.payee_name })}</span>}
      </div>
      <p className="muted small">{t("out.understood", { label: tl("label", o.label) })}
        {o.risk && <> {t("out.risk.pre")}<b className="num">{o.risk.score}</b>{t("out.risk.post")}</>}</p>
      <PipelineTrail outcome={o} />
      {o.risk?.evidence?.length > 0 && <ul className="evidence">{o.risk.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {o.canary_hits?.length > 0 && (
        <div className="card inner tripwire"><strong>{t("out.canary.title")}</strong>
          <p>{t("out.canary.text", { kinds: o.canary_hits.map((h) => h.kind).join(", ") })}</p></div>
      )}
      <div className={forensic && o.card && rec ? "forensic-grid" : undefined}>
      <Card card={o.card} mismatch={forensic ? parseReasons((o.trace_localized || o.trace || []).find((x) => /Execute|执行/.test(x))).filter((x) => x.got) : null} />
      {rec && (
        <div className={`card inner${forensic ? " recovery" : ""}`}>
          <strong>{t("recovery.title")}</strong>
          {forensic ? <ul className="steps">{rec.steps.map((s, i) => <li key={i}><span className="stepno">{i + 1}</span><span>{s.replace(/^\s*\d+[.)]\s*/, "")}</span></li>)}</ul>
            : <ol>{rec.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
          <p className="muted">{t("recovery.draft", { channel, msg: (getLang() !== "en" && rec.draft_message_zh) || rec.draft_message })}</p>
          <p className="muted">{t("recovery.source", { src: (getLang() !== "en" && rec.draft_source_zh) || rec.draft_source, check: rec.draft_checks?.ok ? t("recovery.check.ok") : t("recovery.check.failed") })}
            {rec.llm_draft_rejected?.length > 0 && ` ${t("recovery.rejected", { why: rec.llm_draft_rejected.join("; ") })}`}</p>
          {onRecovery && o.status === "frozen" && <button disabled={busy} onClick={() => click(onRecovery, o)}>{t("recovery.approve")}</button>}
        </div>
      )}
      </div>
      {o.status === "held" && o.decision?.required_approvals?.length > 0 && !approvable(o.decision.required_approvals) && !o.decision.required_approvals.includes("duplicate_confirmation") && (
        <div className="notice info reviewnote" role="note"><div><b>{t("review.needs", { what: needsText(o.decision.required_approvals) })}</b>{" "}
          {o.decision.required_approvals.includes("risk_review") ? t("review.risk") : t("review.else")}</div></div>)}
      {o.status === "held" && o.decision?.required_approvals?.includes("duplicate_confirmation") && !o.pending_id && <DuplicateWarning dup={o.duplicate} onProof={onProof} />}
      <ApprovalActions pid={o.pending_id} draft={o.draft} required={o.decision?.required_approvals} duplicate={o.duplicate} busy={busy}
        onApprove={onApprove && ((id, d) => click(onApprove, id, d))} onPayAgain={onPayAgain && ((id) => click(onPayAgain, id, o))}
        onDismiss={onDismiss && ((id) => click(onDismiss, id, o))} onProof={onProof} />
      {o.status === "paid" && <Signed approvals={o.intent?.approvals} />}
      {o.proof_id && (
        <p>{t("out.proof.pre")}<code>{o.proof_id}</code>{t("out.proof.post")}{" "}
          {onProof && <button className="ghost" onClick={() => onProof(o.proof_id)}>{t("out.proof.open")}</button>}</p>
      )}
      <details><summary>{t("out.trace")}</summary><ol className="trace">{trace?.map((x, i) => <li key={i}>{x}</li>)}</ol></details>
    </div>
  );
}

