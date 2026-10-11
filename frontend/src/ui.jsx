import React, { useEffect, useState } from "react";
import { has, locale, t, tl, tm } from "./i18n/index.js";

/* ---------------------------------------------------------------- formatting
   Numbers and dates follow the active language, with one deliberate exception: rupees always use Indian digit grouping
   (12,34,567) in every language, and yuan use standard grouping (1,234,567). */
const num = (n) => (typeof n === "number" ? n : Number(n ?? 0)) || 0;
export const fmt = (n, d = 0) => num(n).toLocaleString(locale(), { maximumFractionDigits: d });
/** Rupees with Indian digit grouping (12,34,567). d = fixed decimals. */
export const inr = (n, d = 0) => `₹${num(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
/** Yuan with standard grouping (1,234,567). */
export const cny = (n, d = 0) => `¥${num(n).toLocaleString(locale(), { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const pct = (x, d = 0) => `${(num(x) * 100).toFixed(d)}%`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-11-15" or an ISO timestamp -> "15 Nov 2026" / "2026年11月15日" (wall-clock date as written, no timezone shift). */
export function fmtDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
  if (!m) return s || "";
  if (locale().startsWith("en")) return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  try {
    return new Intl.DateTimeFormat(locale(), { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))));
  } catch { return `${m[1]}-${m[2]}-${m[3]}`; }
}
/** ISO timestamp -> "12 Oct 2026, 10:00" / "2026年10月12日 10:00" (wall-clock as written). */
export function fmtDateTime(s) {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(s || "");
  if (!m) return fmtDate(s);
  return locale().startsWith("en") ? `${fmtDate(m[1])}, ${m[2]}` : `${fmtDate(m[1])} ${m[2]}`;
}
export const label = (s) => String(s ?? "").replace(/_/g, " ");

/** Dictionary text may carry two inline marks: **bold** and `code`. Everything else is plain text (never HTML). */
export function rich(text) {
  return String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter((x) => x !== "").map((part, i) => {
    if (part.startsWith("**")) return <b key={i}>{part.slice(2, -2)}</b>;
    if (part.startsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}
/** t() with the inline marks rendered. */
export const R = (key, vars) => rich(t(key, vars));

/* ---------------------------------------------------------------- announcer (aria-live) */
let sink = () => {};
export const announce = (m) => sink(m);
export function Announcer() {
  const [m, setM] = useState("");
  useEffect(() => { sink = (x) => { setM(""); setTimeout(() => setM(x), 40); }; return () => { sink = () => {}; }; }, []);
  return <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{m}</div>;
}

/* ---------------------------------------------------------------- errors */
export class ApiError extends Error {
  constructor(status, detail, retryAfter, code) { super(`${status} ${detail}`); this.status = status; this.detail = detail; this.retryAfter = retryAfter; this.code = code; }
}
/** FastAPI/our 422 detail is an array of {loc,type,msg}: "text: Field required; amount: ..." instead of "[object Object]". */
export function formatDetail(j) {
  if (Array.isArray(j)) {
    return j.map((x) => {
      if (typeof x === "string") return x;
      const where = (x?.loc || []).filter((l) => l !== "body" && l !== "query").join(".");
      const msg = String(x?.msg ?? x?.type ?? JSON.stringify(x)).replace(/^Value error,\s*/i, "");
      return where && !msg.startsWith(where) ? `${where}: ${msg}` : msg;
    }).join("; ");
  }
  if (j && typeof j === "object") return j.msg ? String(j.msg) : JSON.stringify(j);
  return String(j ?? "");
}
/** Approval requirements that are not an approver's signature, in plain words (`req.*` keys). */
export const APPROVER_ROLES = ["student", "parent"];
export const approvable = (req) => (req || []).length > 0 && req.every((r) => APPROVER_ROLES.includes(r));
export const needsText = (req) => (req || []).map((r) => (has(`req.${r}`) ? t(`req.${r}`) : tl("role", r))).join(" + ");

const sentence = (d) => `${d}${/[.!?。！？]$/.test(d) ? "" : t("misc.period")}`;

/** The server writes its error text in the caller's language (X-Oasis-Lang), so `detail` is shown as it arrives; the titles and
    the wording around it are ours. Special cases use the language-neutral `code`, never the wording. */
export function describeError(e) {
  if (!e) return null;
  if (e instanceof ApiError) {
    const d = e.detail;
    if (e.status === 0) return { title: t("err.network.title"), text: t("err.network.text"), retry: true };
    if (e.status === 429) return { title: t("err.ratelimit.title"), text: `${sentence(d)}${e.retryAfter ? ` ${t("err.ratelimit.retry", { s: e.retryAfter })}` : ` ${t("err.ratelimit.wait")}`}`, tone: "warn" };
    if (e.status === 410) return { title: t("err.expired.title"), text: t("err.expired.text") };
    if (e.status === 401) return { title: t("err.denied.title"), text: d };
    if (e.status === 403) return { title: e.code === "approval_rejected" ? t("err.approval.title") : e.code === "cross_origin" ? t("err.cross.title") : t("err.denied.title"), text: d };
    if (e.status >= 500) return { title: t("err.server.title"), text: t("err.server.text", { detail: d }), retry: true };
    if (e.status === 413) return { title: t("err.toolarge.title"), text: d };
    if (e.status === 422) return { title: t("err.invalid.title"), text: typeof d === "string" ? d : formatDetail(d) };
    return { title: t("err.refused.title", { status: e.status }), text: d };
  }
  return { title: t("err.generic.title"), text: String(e.message || e) };
}
export function ErrorBox({ error, onRetry, onDismiss }) {
  const d = describeError(error);
  if (!d) return null;
  return (
    <div className={`error ${d.tone || ""}`} role="alert">
      <div className="msg"><b>{d.title}</b>{d.text}</div>
      {onRetry && d.retry !== false && <button type="button" onClick={onRetry}>{t("err.retry")}</button>}
      {onDismiss && <button type="button" onClick={onDismiss} aria-label={t("err.dismiss.aria")}>{t("err.dismiss")}</button>}
    </div>
  );
}
export function Loading({ children }) {
  return <div className="loading" role="status"><span className="spinner" aria-hidden="true" />{children ?? t("common.loading")}</div>;
}
export function Skeleton({ rows = 3 }) {
  return <div aria-busy="true" aria-label={t("common.loading.aria")}>{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ width: `${95 - i * 12}%` }} />)}</div>;
}
export function Empty({ title, children }) {
  return <div className="empty"><b>{title}</b>{children}</div>;
}

/* ---------------------------------------------------------------- small pieces */
export function Mock({ children }) {
  return <span className="mocktag" title={t("mock.title")}>{children ?? t("mock.tag")}</span>;
}

const TONE = {
  ok: ["paid", "verified_full", "allow", "done", "rate_target_conversion", "recurring_bill_paid", "signed", "verified", "valid", "intact"],
  warn: ["held", "verified_low", "registry_checked", "pending", "shortfall", "low_runway", "late_income", "watching", "awaiting_approval",
    "planned", "rate_target_needs_approval", "recurring_bill_held", "rate_move", "rate_target", "awaiting_parent_consent", "waiting", "stale", "needs_approval"],
  bad: ["frozen", "rejected", "needs_verification", "unverified", "blocked", "broken", "invalid", "failed", "deny", "reject", "rate_target_blocked"],
  info: ["proposed", "accepted", "executing", "scheduled"],
};
export const toneOf = (s) => Object.keys(TONE).find((k) => TONE[k].includes(s)) || "neutral";
export function Pill({ status, children }) {
  return <span className={`pill ${toneOf(status)}`}>{children ?? tl("status", status)}</span>;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); document.body.removeChild(ta); return ok;
  } catch { return false; }
}
/** Long hash/id: truncated display, full value on hover, copy button. `what` is the (already translated) name of the value. */
export function Hash({ value, n = 8, what }) {
  const [state, setState] = useState("");
  if (!value) return null;
  const v = String(value);
  const name = what ?? t("hash.value");
  const shown = v.length > n * 2 + 2 ? `${v.slice(0, n)}…${v.slice(-4)}` : v;
  const copy = async () => {
    const ok = await copyText(v);
    setState(ok ? "done" : "fail"); announce(ok ? t("hash.copied.announce", { what: name }) : t("hash.failed.announce", { what: name }));
    setTimeout(() => setState(""), 1600);
  };
  return (
    <span className="hashwrap">
      <code className="hash" title={v}>{shown}</code>
      <button type="button" className={`copy ghost ${state}`} onClick={copy} aria-label={t("hash.copy.aria", { what: name })}>
        {state === "done" ? t("hash.copied") : state === "fail" ? t("hash.failed") : t("hash.copy")}
      </button>
    </span>
  );
}

/* ---------------------------------------------------------------- six-step pipeline */
export const STEPS = ["understand", "plan", "verify", "commit", "execute", "prove"];
const KEYS = ["Understand", "Plan", "Verify", "Commit", "Execute", "Prove"];
const ZH_STEP = { 理解: "Understand", 规划: "Plan", 验证: "Verify", 决定: "Commit", 执行: "Execute", 证明: "Prove" };
const stepLabel = (i) => t(`pipe.${STEPS[i]}`);

/** Derive the per-step trail of one payment outcome from its trace lines, status and verification. In Chinese the API sends
    the trace already translated (`trace_localized`); the step is recognised from either spelling. */
export function trailOf(o) {
  const by = {};
  (o.trace_localized || o.trace || []).forEach((line) => {
    const m = /^(Understand|Plan|Verify|Commit|Execute|Prove|理解|规划|验证|决定|执行|证明)(?![A-Za-z])[^:：]*[:：]\s*(.*)$/.exec(line);
    if (m) (by[ZH_STEP[m[1]] || m[1]] ||= []).push(m[2]);
  });
  const route = (name) => t("pipe.d.route", { route: tm(name) });
  if (!by.Plan && o.savings?.route) by.Plan = [route(o.savings.route)];   // only when the outcome carries route info
  const present = KEYS.map((k) => !!by[k]);
  const lastPresent = present.lastIndexOf(true);
  const verifyBad = o.verification && (o.verification.account_changed || ["unverified", "needs_verification"].includes(o.verification.level));
  const stopped = ["frozen", "rejected"].includes(o.status);
  let stopIdx = -1;
  if (stopped) stopIdx = o.canary_hits?.length ? 0 : verifyBad ? 2 : Math.max(lastPresent, 0);
  const f = o.fields, dec = o.decision, ver = o.verification;
  const nice = {
    Understand: () => o.canary_hits?.length ? t("pipe.d.decoy", { kinds: o.canary_hits.map((h) => h.kind).join(", ") })
      : f ? t(o.risk ? "pipe.d.read.risk" : "pipe.d.read", { amount: cny(f.amount), payee: f.payee_name, risk: o.risk?.score }) : "",
    Plan: () => (by.Plan?.[0] || (o.savings?.route ? route(o.savings.route) : t("pipe.d.single"))),
    Verify: () => ver ? `${tl("level", ver.level)}${ver.account_changed ? t("pipe.d.acct_differs") : ""}${ver.reasons?.[0] ? `${t("misc.colon")}${ver.reasons[0]}` : ""}` : "",
    Commit: () => dec ? `${dec.action === "hold" ? t("pipe.d.held") : tl("action", dec.action)} ${t("pipe.d.by", { rule: dec.rule })}${dec.required_approvals?.length ? `${t("misc.colon")}${t("pipe.d.needs", { what: needsText(dec.required_approvals) })}` : ""}` : "",
    Execute: () => by.Execute?.[0] || "",
    Prove: () => by.Prove?.[0] || "",
  };
  return KEYS.map((k, i) => {
    const lines = by[k] || [];
    const detail = (lines.length || k === "Plan") && nice[k] ? nice[k]() || lines[0] || "" : lines[0] || "";
    const base = { key: k, detail, full: lines.join(" | ") };
    if (stopIdx >= 0) {
      if (i < stopIdx) return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? t("pipe.s.passed") : t("pipe.s.na") };
      if (i === stopIdx) {
        const text = k === "Understand" && o.canary_hits?.length ? t("pipe.s.tripwire") : k === "Verify" ? t("pipe.s.mismatch") : o.status === "frozen" ? t("pipe.s.frozen") : t("pipe.s.rejected");
        return { ...base, state: "stop", text, detail: i === 2 && o.verification?.reasons?.[0] ? o.verification.reasons[0] : detail };
      }
      return { ...base, state: "idle", text: t("pipe.s.notreached"), detail: "" };
    }
    if (o.status === "held") {
      if (k === "Commit") {
        const req = o.decision?.required_approvals || [];
        const text = req.includes("risk_review") ? t("pipe.s.review") : req.includes("duplicate_confirmation") ? t("pipe.s.duplicate")
          : req.length && !approvable(req) ? t("pipe.s.outside") : t("pipe.s.waiting");
        return { ...base, state: "warn", text };
      }
      if (i < 3) return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? t("pipe.s.passed") : t("pipe.s.na") };
      return { ...base, state: "idle", text: t("pipe.s.notyet"), detail: "" };
    }
    return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? t("pipe.s.done") : t("pipe.s.na") };
  });
}

export function PipelineTrail({ outcome }) {
  if (!outcome?.trace?.length) return null;
  const steps = trailOf(outcome);
  const max = locale().startsWith("en") ? 96 : 60;
  return (
    <div>
      <ol className="trail" aria-label={t("pipe.aria")}>
        {steps.map((s, i) => (
          <li key={s.key} className={`${s.state}`}>
            <div className="node"><span className="dot" aria-hidden="true">{s.state === "ok" ? "✓" : s.state === "stop" ? "✕" : s.state === "warn" ? "!" : i + 1}</span><span className="bar" aria-hidden="true" /></div>
            <div className="name">{stepLabel(i)}</div>
            <div className="st">{s.text}</div>
            {s.detail && <div className="why" title={s.full}>{s.detail.length > max ? `${s.detail.slice(0, max)}…` : s.detail}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Compact marker of which steps a scripted demo step exercises. */
export function MiniTrail({ items }) {
  return (
    <ol className="minitrail" aria-label={t("pipe.mini.aria")}>
      {STEPS.map((k, i) => <li key={k} className={items?.includes(k) ? "on" : ""}>{stepLabel(i)}{items?.includes(k) && <span className="sr-only"> {t("pipe.mini.exercised")}</span>}</li>)}
    </ol>
  );
}
