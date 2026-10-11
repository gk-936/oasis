import React, { useEffect, useRef, useState } from "react";
import { api, short4, signedApprove, useGuard } from "../api.js";
import { ApprovalActions, Card, Outcome, SAMPLE_INVOICE, TOPUP_TEXT } from "../common.jsx";
import { t, tl } from "../i18n/index.js";
import { ErrorBox, Mock, cny } from "../ui.jsx";

/* Messages the UI writes itself are stored as {k, vars} and translated when drawn, so they follow a language switch;
   the agent's own replies (r.reply) arrive already written in the language of the request. */
const GREETING = { role: "oasis", k: "chat.greeting" };

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
    try { const r = await api("/chat", { message: text }); say({ role: "oasis", text: r.reply, outcome: r.outcome }); }
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
  const recover = (o) => run(async () => {
    const r = await api("/recovery/approve", { obligation: o.recovery?.safe_plan?.obligation });
    say({ role: "oasis", k: "chat.recovered", vars: { n: r.canaries_cleared } }); refresh();
  });
  const text = (m) => {
    if (!m.k) return m.text;
    const v = m.vars?.status ? { ...m.vars, status: tl("status", m.vars.status) } : m.vars;
    return t(m.k, v);
  };
  return (
    <section aria-labelledby="chat-h" className="stack">
      <h2 id="chat-h">{t("chat.title")}</h2>
      <div className="chat" role="log" aria-label={t("chat.log.aria")}>
        {log.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <p>{text(m)}</p>
            {m.outcome && <Outcome o={m.outcome} onProof={openProof} onRecovery={recover}
              {...(m.outcome.draft && resolved.has(`${m.outcome.pending_id}:${m.outcome.draft.draft_hash}`) ? {} : { onApprove: approve, onPayAgain: payAgain, onDismiss: dismiss })} />}
          </div>
        ))}
        {thinking && <div className="msg oasis pending" role="status"><p>{t("chat.thinking")}</p></div>}
        <div ref={end} />
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
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
      </div>
    </section>
  );
}
