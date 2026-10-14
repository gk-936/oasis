import React, { useEffect, useRef, useState } from "react";
import { api, short4, signedApprove, upload, useGuard } from "../api.js";
import { ApprovalActions, Card, Outcome, SAMPLE_INVOICE, TOPUP_TEXT } from "../common.jsx";
import { t, tl } from "../i18n/index.js";
import { ErrorBox, Mock, cny } from "../ui.jsx";

/* Messages the UI writes itself are stored as {k, vars} and translated when drawn, so they follow a language switch;
   the agent's own replies (r.reply) arrive already written in the language of the request. */
const GREETING = { role: "oasis", k: "chat.greeting" };

/* Other ways to send an invoice: forwarded from a phone (Telegram) or a watched mailbox. Server-configured; nothing secret is shown. */
function Channels() {
  const [c, setC] = useState(null);
  const [code, setCode] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const load = () => api("/intake/channels").then(setC).catch(setErr);
  useEffect(() => { load(); }, []);
  if (!c) return err ? <ErrorBox error={err} onRetry={load} /> : null;
  const pair = () => run(async () => { setCode(await api("/intake/telegram/pair", {})); });
  const unpair = () => run(async () => { await api("/intake/telegram/unpair", {}); setCode(null); await load(); });
  return (
    <details className="card" data-testid="channels">
      <summary><b>{t("ch.title")}</b></summary>
      <p className="muted small">{t("ch.intro")}</p>
      <ul className="feed">
        <li>{t("ch.email")}</li>
        <li>{c.telegram.configured ? t("ch.tg.on", { n: c.telegram.paired_chats }) : t("ch.tg.off")}
          {c.telegram.configured && <> <button className="ghost" disabled={busy} onClick={pair} data-testid="tg-pair">{t("ch.tg.pair")}</button>
            {c.telegram.paired_chats > 0 && <button className="ghost" disabled={busy} onClick={unpair}>{t("ch.tg.unpair")}</button>}</>}
          {code && <p data-testid="tg-code"><code>/pair {code.code}</code> <span className="muted small">{t("ch.tg.code", { m: Math.round(code.expires_in / 60) })}</span></p>}
          {c.telegram.last_error && <p className="muted small">{t("ch.err", { e: c.telegram.last_error })}</p>}</li>
        <li>{c.imap.configured ? t("ch.imap.on", { senders: c.imap.allowed_senders.join(", "), p: c.imap.processed, i: c.imap.ignored }) : t("ch.imap.off")}
          {c.imap.last_error && <p className="muted small">{t("ch.err", { e: c.imap.last_error })}</p>}</li>
      </ul>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
    </details>
  );
}

export function Chat({ refresh, openProof, s }) {
  const [log, setLog] = useState([GREETING]);
  const [msg, setMsg] = useState("");
  const [thinking, setThinking] = useState(false);
  const [resolved, setResolved] = useState(() => new Set());
  const { busy, err, setErr, run } = useGuard();
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [log, thinking]);
  const say = (m) => { setLog((l) => [...l, m]); };
  const send = (text) => run(async () => {
    if (!text.trim()) return;
    say({ role: "student", text }); setMsg(""); setThinking(true);
    try { const r = await api("/chat", { message: text }); say({ role: "oasis", text: r.reply, outcome: r.outcome, meta: r }); }
    finally { setThinking(false); refresh(); }
  });
  const resolve = (id, draft) => setResolved((x) => new Set(x).add(`${id}:${draft?.draft_hash}`));
  const payAgain = (id, o) => run(async () => {
    const r = await api("/pay-again", { pending_id: id });
    if (o) resolve(id, o.draft);
    say({ role: "oasis", k: "chat.payagain", outcome: r });
    refresh();
  });
  const dismiss = (id, o) => run(async () => {
    await api("/approve", { pending_id: id, approve: false });
    if (o) resolve(id, o.draft);
    say({ role: "oasis", k: "chat.dismissed" }); refresh();
  });
  const approve = (id, draft) => run(async () => {
    let r;
    try { r = await signedApprove("student", id, draft); }
    catch (e) { if (e.status === 410 || e.status === 404) resolve(id, draft); throw e; }   // expired or gone: the button must not stay
    resolve(id, draft);
    if (r.status === "waiting") {
      const by = r.signed_by ? Object.entries(r.signed_by).map(([k, v]) => t("chat.devkey", { role: tl("role", k), key: short4(v) })).join(", ") : "";
      say({ role: "oasis", k: "chat.waiting", vars: { missing: r.missing.map((m) => tl("role", m)).join(", "), by: by ? t("chat.waiting.by", { by }) : "" } });
    } else say({ role: "oasis", k: "chat.signed", vars: { status: r.status }, outcome: r });
    refresh();
  });
  const topup = () => run(async () => {
    const o = await api("/intake", { remitter: "parent", text: TOPUP_TEXT });
    say({ role: "oasis", k: "chat.topup", vars: { status: o.status }, outcome: o }); refresh();
  });
  const fileRef = useRef(null);
  const sendEmail = (file) => run(async () => {
    if (!file) return;
    say({ role: "student", k: "chat.email.said", vars: { name: file.name } }); setThinking(true);
    try {
      const o = await upload("/intake/email", file);
      say({ role: "oasis", k: "chat.email.checked", vars: { status: o.status, notes: (o.intake_notes || []).join("; ") }, outcome: o });
    } finally { setThinking(false); refresh(); if (fileRef.current) fileRef.current.value = ""; }
  });
  const recover = (o) => run(async () => {
    const r = await api("/recovery/approve", { obligation: o.recovery?.safe_plan?.obligation });
    say({ role: "oasis", k: "chat.recovered", vars: { n: r.canaries_cleared } }); refresh();
  });
  const SUGGESTIONS = ["rent", "tuition", "owe", "balance", "rate", "runway"];
  /* Quick replies for the last Oasis message: they only send ordinary chat text, so they carry no extra authority. */
  const chips = (m) => {
    const st = m.meta?.status;
    if (st === "needs_confirmation") return [["chip.confirm", () => send(t("chat.chip.confirm.msg"))], ["chip.change", () => setMsg(t("chat.chip.change.prefill"))], ["chip.no", () => send(t("chat.chip.no.msg"))]];
    if (st === "held" && m.meta?.pending_id) return [["chip.change", () => setMsg(t("chat.chip.change.prefill"))], ["chip.cancel", () => send(t("chat.chip.cancel.msg"))]];
    return [];
  };
  const text = (m) => {
    if (!m.k) return m.text;
    const v = m.vars?.status ? { ...m.vars, status: tl("status", m.vars.status) } : m.vars;
    return t(m.k, v) + (m.k === "chat.email.checked" && m.vars?.notes ? ` (${m.vars.notes})` : "");
  };
  return (
    <section aria-labelledby="chat-h" className="stack">
      <h2 id="chat-h">{t("chat.title")}</h2>
      <div className="chat" role="log" aria-label={t("chat.log.aria")}>
        {log.map((m, i) => (
          <div key={i} className={`msg ${m.role}${m.meta?.status === "refused" ? " refused" : ""}`} data-testid={m.meta?.status === "refused" ? "chat-refusal" : undefined}>
            {m.meta?.status === "refused" && <p className="refusal-label"><span aria-hidden="true">🛡</span> <b>{t("chat.refused")}</b></p>}
            <p>{text(m)}</p>
            {m.meta?.needs?.length > 0 && <p className="muted small">{m.meta.needs.filter((n) => n.endsWith("_signature")).map((n) => t(`chat.needs.${n}`)).join(" · ")}</p>}
            {i === log.length - 1 && !busy && chips(m).length > 0 && (
              <div className="row chips" role="group" aria-label={t("chat.waiting.aria")}>
                {chips(m).map(([k, fn]) => <button key={k} type="button" className="ghost chip" onClick={fn}>{t(`chat.${k}`)}</button>)}
              </div>)}
            {m.outcome && <Outcome o={m.outcome} onProof={openProof} onRecovery={recover}
              {...(m.outcome.draft && resolved.has(`${m.outcome.pending_id}:${m.outcome.draft.draft_hash}`) ? {} : { onApprove: approve, onPayAgain: payAgain, onDismiss: dismiss })} />}
          </div>
        ))}
        {thinking && <div className="msg oasis pending" role="status"><p>{t("chat.thinking")}</p></div>}
        <div ref={end} />
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {log.length === 1 && (
        <div className="card" data-testid="chat-suggestions"><p className="muted small" style={{ marginTop: 0 }}>{t("chat.sugg.title")}</p>
          <div className="row chips">
            {SUGGESTIONS.map((k) => <button key={k} type="button" className="ghost chip" disabled={busy} onClick={() => send(t(`chat.sugg.${k}`))}>{t(`chat.sugg.${k}`)}</button>)}
          </div>
        </div>)}
      {(() => {
        const inLog = new Set(log.map((m) => m.outcome?.pending_id).filter(Boolean));
        const waiting = (s?.pending || []).filter((p) => !inLog.has(p.id) && (p.required.includes("student") || p.required.includes("duplicate_confirmation")));
        if (!waiting.length) return null;
        return (
          <div className="card" aria-label={t("chat.waiting.aria")}><h3 style={{ marginTop: 0 }}>{t("chat.waiting.title")}</h3>
            {waiting.map((p) => (
              <div key={p.id} className="stack">
                <p><b className="money">{cny(p.fields?.amount, 2)}</b> {p.fields?.purpose ? t("out.to.purpose", { payee: p.fields?.payee_name, purpose: tl("purpose", p.fields.purpose) }) : t("out.to", { payee: p.fields?.payee_name })}</p>
                <Card card={p.card} />
                <ApprovalActions pid={p.id} draft={p.draft} required={p.required} duplicate={p.duplicate} busy={busy}
                  onApprove={approve} onPayAgain={(id) => payAgain(id, null)} onDismiss={(id) => dismiss(id, null)} onProof={openProof} />
              </div>))}
          </div>);
      })()}
      <label>{t("chat.input.label")}
        <textarea rows={6} value={msg} onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !busy) send(msg); }}
          placeholder={t("chat.input.placeholder")} /></label>
      <div className="row">
        <button disabled={busy || !msg.trim()} onClick={() => send(msg)}>{t("chat.send")}</button>
        <button className="ghost" disabled={busy} onClick={() => setMsg(SAMPLE_INVOICE)}>{t("chat.sample")}</button>
        <button className="ghost" disabled={busy} onClick={() => send(t("chat.ask.msg"))}>{t("chat.ask")}</button>
        <button className="ghost" disabled={busy} onClick={topup}>{t("chat.topup.btn")} <Mock /></button>
        <button className="ghost" disabled={busy} onClick={() => fileRef.current?.click()} data-testid="chat-email-btn">{t("chat.email.btn")}</button>
        <input ref={fileRef} type="file" accept=".eml,message/rfc822" hidden data-testid="chat-email-file" onChange={(e) => sendEmail(e.target.files?.[0])} />
      </div>
      <Channels />
    </section>
  );
}
