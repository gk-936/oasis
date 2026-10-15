import React, { useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { api, short4, signedApprove, upload, useGuard } from "../api.js";
import { ApprovalActions, Card, Outcome, SAMPLE_INVOICE, TOPUP_TEXT } from "../common.jsx";
import { t, tl } from "../i18n/index.js";
import { ErrorBox, Mock, money } from "../ui.jsx";

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

const SUGG_ICON = {
  rent: <path d="m3 11 9-8 9 8M5 10v10h5v-6h4v6h5V10" />,
  tuition: <path d="m2 9 10-5 10 5-10 5zM6 11.5V16c0 1.5 3 3 6 3s6-1.500 6-3v-4.500M22 9v6" />,
  owe: <path d="M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6" />,
  balance: <path d="M3 7a2 2 0 0 1 2-2h13v4M3 7v11a2 2 0 0 0 2 2h15V9H5a2 2 0 0 1-2-2zM16 14.500h.01" />,
  rate: <path d="M7 8h13M16 4l4 4-4 4M17 16H4M8 12l-4 4 4 4" />,
  runway: <path d="m3 7 6 6 4-4 8 8M21 11v6h-6" />,
};
const Gly = ({ children, size = 18 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);
/* Small data tokens inside a reply (a rate, the MOCK label, a date) are drawn as monospace pills. */
const TELE = /(INR\s*(?:→|->)\s*CNY\s+[\d.]+|MOCK|模拟|\d{4}-\d{2}-\d{2})/g;
const Rich = ({ text }) => String(text).split(TELE).map((x, i) => (i % 2 ? <code key={i} className="tele">{x}</code> : x));

export function Chat({ refresh, openProof, s, onBack }) {
  const [log, setLog] = useState([GREETING]);
  const [msg, setMsg] = useState("");
  const [thinking, setThinking] = useState(false);
  const [resolved, setResolved] = useState(() => new Set());
  const { busy, err, setErr, run } = useGuard();
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [log, thinking]);
  const active = log.length > 1;                                // a conversation is under way
  const toPrompts = () => { setLog([GREETING]); setResolved(new Set()); setMsg(""); setErr(null); };   // back to the starter view (the screen only; nothing server-side changes)
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
  const box = useRef(null), toolsRef = useRef(null);
  const [tools, setTools] = useState(false);            // the "+" menu: sample invoice, email upload, top-up, other channels
  const [showChannels, setShowChannels] = useState(false);
  const fit = (el) => { el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, 200)}px`; };   // grows with the text
  useEffect(() => { if (!msg && box.current) box.current.style.height = "auto"; }, [msg]);
  useEffect(() => {
    if (!tools) return undefined;
    const off = (e) => { if (!toolsRef.current?.contains(e.target)) setTools(false); };
    const esc = (e) => { if (e.key === "Escape") setTools(false); };
    document.addEventListener("pointerdown", off); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", off); document.removeEventListener("keydown", esc); };
  }, [tools]);
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
    <MotionConfig reducedMotion="user">
    <section aria-labelledby="chat-h" className="chatpage">
      <header className="chat-top">
        <button type="button" className="chat-back" onClick={() => (active ? toPrompts() : onBack?.())}>
          <Gly size={15}><path d="M19 12H5M11 6l-6 6 6 6" /></Gly>{t("chat.back")}
        </button>
        <h2 id="chat-h">{t("chat.title")}</h2>
        <AnimatePresence>
          {active && (
            <motion.button type="button" className="chat-back chat-prompts" onClick={toPrompts}
              initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 8 }}>
              <Gly size={15}><path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5" /></Gly>{t("chat.prompts")}
            </motion.button>)}
        </AnimatePresence>
      </header>

      <div className="chat-scroll">
        <div className="chat" role="log" aria-label={t("chat.log.aria")}>
          {log.map((m, i) => (
            <motion.div key={i} className={`msg-row ${m.role}`} initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: "spring", stiffness: 260, damping: 26 }}>
              {m.role === "oasis" && (
                <span className="ai-av" aria-hidden="true"><Gly size={17}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.200L5 10l5.200-1.800z" /></Gly></span>)}
              <div className={`msg ${m.role}${m.meta?.status === "refused" ? " refused" : ""}`} data-testid={m.meta?.status === "refused" ? "chat-refusal" : undefined}>
                {m.meta?.status === "refused" && <p className="refusal-label"><span aria-hidden="true">🛡</span> <b>{t("chat.refused")}</b></p>}
                <p>{m.role === "oasis" ? <Rich text={text(m)} /> : text(m)}</p>
                {m.meta?.needs?.length > 0 && <p className="muted small">{m.meta.needs.filter((n) => n.endsWith("_signature")).map((n) => t(`chat.needs.${n}`)).join(" · ")}</p>}
                {i === log.length - 1 && !busy && chips(m).length > 0 && (
                  <div className="row chips" role="group" aria-label={t("chat.waiting.aria")}>
                    {chips(m).map(([k, fn]) => <button key={k} type="button" className="ghost chip" onClick={fn}>{t(`chat.${k}`)}</button>)}
                  </div>)}
                {m.outcome && <Outcome o={m.outcome} onProof={openProof} onRecovery={recover}
                  {...(m.outcome.draft && resolved.has(`${m.outcome.pending_id}:${m.outcome.draft.draft_hash}`) ? {} : { onApprove: approve, onPayAgain: payAgain, onDismiss: dismiss })} />}
              </div>
            </motion.div>
          ))}
          {thinking && (
            <div className="msg-row oasis"><span className="ai-av" aria-hidden="true"><Gly size={17}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.200L5 10l5.200-1.800z" /></Gly></span>
              <div className="msg oasis pending" role="status"><p>{t("chat.thinking")}</p></div></div>)}
          <AnimatePresence>
            {!active && (
              <motion.div className="suggest" data-testid="chat-suggestions" exit={{ opacity: 0, y: 10, transition: { duration: 0.18 } }}>
                <p className="suggest-h">{t("chat.sugg.title")}</p>
                <div className="suggest-grid">
                  {SUGGESTIONS.map((k) => (
                    <button key={k} type="button" className="suggest-card" disabled={busy} onClick={() => send(t(`chat.sugg.${k}`))}>
                      <span className="sg-ico"><Gly>{SUGG_ICON[k]}</Gly></span><span className="sg-t">{t(`chat.sugg.${k}`)}</span><i aria-hidden="true">→</i>
                    </button>))}
                </div>
              </motion.div>)}
          </AnimatePresence>
          <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {(() => {
        const inLog = new Set(log.map((m) => m.outcome?.pending_id).filter(Boolean));
        const waiting = (s?.pending || []).filter((p) => !inLog.has(p.id) && (p.required.includes("student") || p.required.includes("duplicate_confirmation")));
        if (!waiting.length) return null;
        return (
          <div className="card" aria-label={t("chat.waiting.aria")}><h3 style={{ marginTop: 0 }}>{t("chat.waiting.title")}</h3>
            {waiting.map((p) => (
              <div key={p.id} className="stack">
                <p><b className="money">{money(p.fields?.amount, p.fields?.currency, 2)}</b> {p.fields?.purpose ? t("out.to.purpose", { payee: p.fields?.payee_name, purpose: tl("purpose", p.fields.purpose) }) : t("out.to", { payee: p.fields?.payee_name })}</p>
                <Card card={p.card} />
                <ApprovalActions pid={p.id} draft={p.draft} required={p.required} duplicate={p.duplicate} busy={busy}
                  onApprove={approve} onPayAgain={(id) => payAgain(id, null)} onDismiss={(id) => dismiss(id, null)} onProof={openProof} />
              </div>))}
          </div>);
      })()}
          <div ref={end} />
        </div>
      </div>

      <div className="chat-dock">
      {showChannels && <Channels />}
      <motion.form layout transition={{ type: "spring", stiffness: 260, damping: 30 }} className="composer" onSubmit={(e) => { e.preventDefault(); if (!busy && msg.trim()) send(msg); }}>
        <label htmlFor="chat-msg" className="sr-only">{t("chat.input.label")}</label>
        <textarea id="chat-msg" ref={box} rows={1} value={msg} placeholder={t("chat.input.placeholder")}
          onChange={(e) => { setMsg(e.target.value); fit(e.target); }}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (!busy && msg.trim()) send(msg); } }} />
        <div className="composer-bar">
          <div className="composer-tools" ref={toolsRef}>
            <button type="button" className="composer-plus" aria-haspopup="menu" aria-expanded={tools} aria-label={t("chat.tools")} onClick={() => setTools((v) => !v)}>
              <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
            </button>
            {tools && (
              <div className="composer-menu" role="menu">
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setMsg(SAMPLE_INVOICE); setTools(false); setTimeout(() => { if (box.current) { box.current.focus(); fit(box.current); } }, 0); }}>{t("chat.sample")}</button>
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setTools(false); send(t("chat.ask.msg")); }}>{t("chat.ask")}</button>
                <button type="button" role="menuitem" disabled={busy} onClick={() => { setTools(false); topup(); }}>{t("chat.topup.btn")} <Mock /></button>
                <button type="button" role="menuitem" disabled={busy} data-testid="chat-email-btn" onClick={() => { setTools(false); fileRef.current?.click(); }}>{t("chat.email.btn")}</button>
                <button type="button" role="menuitem" onClick={() => { setTools(false); setShowChannels((v) => !v); }}>{t("ch.title")}</button>
              </div>)}
            <span className="composer-hint">{t("chat.attach")}</span>
            <input ref={fileRef} type="file" accept=".eml,message/rfc822" hidden data-testid="chat-email-file" onChange={(e) => sendEmail(e.target.files?.[0])} />
          </div>
          <button type="submit" className="composer-send" disabled={busy || !msg.trim()} aria-label={t("chat.send")} title={t("chat.send")}>
            <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" /></svg>
          </button>
        </div>
      </motion.form>
      </div>
    </section>
    </MotionConfig>
  );
}
