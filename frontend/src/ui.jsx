import React, { useEffect, useState } from "react";

/* ---------------------------------------------------------------- formatting */
const num = (n) => (typeof n === "number" ? n : Number(n ?? 0)) || 0;
export const fmt = (n, d = 0) => num(n).toLocaleString("en-US", { maximumFractionDigits: d });
/** Rupees with Indian digit grouping (12,34,567). d = fixed decimals. */
export const inr = (n, d = 0) => `₹${num(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
/** Yuan with standard grouping (1,234,567). */
export const cny = (n, d = 0) => `¥${num(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const pct = (x, d = 0) => `${(num(x) * 100).toFixed(d)}%`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-11-15" or an ISO timestamp -> "15 Nov 2026" (wall-clock date as written, no timezone shift). */
export function fmtDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || "");
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : s || "";
}
/** ISO timestamp -> "12 Oct 2026, 10:00" (wall-clock as written). */
export function fmtDateTime(s) {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(s || "");
  return m ? `${fmtDate(m[1])}, ${m[2]}` : fmtDate(s);
}
export const label = (s) => String(s ?? "").replace(/_/g, " ");

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
  constructor(status, detail, retryAfter) { super(`${status} ${detail}`); this.status = status; this.detail = detail; this.retryAfter = retryAfter; }
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
/** Plain words for approval requirements that are not an approver's signature. */
export const REQ_LABEL = {
  risk_review: "review outside this document",
  out_of_band_verification: "confirmation outside this document",
  duplicate_confirmation: "your explicit Pay again",
  corrected_cny_invoice: "a corrected CNY invoice",
  verification: "recipient verification",
};
export const APPROVER_ROLES = ["student", "parent"];
export const approvable = (req) => (req || []).length > 0 && req.every((r) => APPROVER_ROLES.includes(r));
export const needsText = (req) => (req || []).map((r) => REQ_LABEL[r] || r).join(" + ");

export function describeError(e) {
  if (!e) return null;
  if (e instanceof ApiError) {
    const d = e.detail;
    if (e.status === 0) return { title: "Can't reach the Oasis API", text: "The server did not answer. Check that it is running (port 8000) and that you are online, then try again.", retry: true };
    if (e.status === 429) return { title: "Rate limit reached", text: `${d}${/[.!?]$/.test(d) ? "" : "."}${e.retryAfter ? ` Try again in about ${e.retryAfter} seconds.` : " Wait a moment, then try again."}`, tone: "warn" };
    if (e.status === 410) return { title: "Draft expired", text: "That draft expired \u2014 submit the invoice again." };
    if (e.status === 401) return { title: "Not allowed", text: d };
    if (e.status === 403) return { title: /signature|signed approval/i.test(d) ? "Approval not accepted" : /cross-origin/i.test(d) ? "Request refused" : "Not allowed", text: d };
    if (e.status >= 500) return { title: "The server hit an error", text: `${d} Nothing was paid. Try again, and check the API log if it repeats.`, retry: true };
    if (e.status === 413) return { title: "Input too large", text: d };
    if (e.status === 422) return { title: "That input was not accepted", text: typeof d === "string" ? d : formatDetail(d) };
    return { title: `Request refused (${e.status})`, text: d };
  }
  return { title: "Something went wrong", text: String(e.message || e) };
}
export function ErrorBox({ error, onRetry, onDismiss }) {
  const d = describeError(error);
  if (!d) return null;
  return (
    <div className={`error ${d.tone || ""}`} role="alert">
      <div className="msg"><b>{d.title}</b>{d.text}</div>
      {onRetry && d.retry !== false && <button type="button" onClick={onRetry}>Try again</button>}
      {onDismiss && <button type="button" onClick={onDismiss} aria-label="Dismiss message">Dismiss</button>}
    </div>
  );
}
export function Loading({ children = "Loading…" }) {
  return <div className="loading" role="status"><span className="spinner" aria-hidden="true" />{children}</div>;
}
export function Skeleton({ rows = 3 }) {
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ width: `${95 - i * 12}%` }} />)}</div>;
}
export function Empty({ title, children }) {
  return <div className="empty"><b>{title}</b>{children}</div>;
}

/* ---------------------------------------------------------------- small pieces */
export function Mock({ children = "MOCK" }) {
  return <span className="mocktag" title="Simulated sandbox data, not real money, rates or institutions">{children}</span>;
}

const TONE = {
  ok: ["paid", "verified_full", "allow", "done", "rate_target_conversion", "recurring_bill_paid", "signed", "verified", "valid", "intact"],
  warn: ["held", "verified_low", "registry_checked", "pending", "shortfall", "low_runway", "late_income", "watching", "awaiting_approval",
    "planned", "rate_target_needs_approval", "recurring_bill_held", "rate_move", "rate_target", "awaiting_parent_consent", "waiting", "stale", "needs_approval"],
  bad: ["frozen", "rejected", "needs_verification", "unverified", "blocked", "broken", "invalid", "failed", "deny", "reject"],
  info: ["proposed", "accepted", "executing", "scheduled"],
};
export const toneOf = (s) => Object.keys(TONE).find((t) => TONE[t].includes(s)) || "neutral";
export function Pill({ status, children }) {
  return <span className={`pill ${toneOf(status)}`}>{children ?? label(status)}</span>;
}

async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; } catch { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = t; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); document.body.removeChild(ta); return ok;
  } catch { return false; }
}
/** Long hash/id: truncated display, full value on hover, copy button. */
export function Hash({ value, n = 8, what = "value" }) {
  const [state, setState] = useState("");
  if (!value) return null;
  const v = String(value);
  const shown = v.length > n * 2 + 2 ? `${v.slice(0, n)}…${v.slice(-4)}` : v;
  const copy = async () => {
    const ok = await copyText(v);
    setState(ok ? "done" : "fail"); announce(ok ? `Copied ${what}` : `Could not copy ${what}`);
    setTimeout(() => setState(""), 1600);
  };
  return (
    <span className="hashwrap">
      <code className="hash" title={v}>{shown}</code>
      <button type="button" className={`copy ghost ${state}`} onClick={copy} aria-label={`Copy full ${what}`}>
        {state === "done" ? "Copied" : state === "fail" ? "Failed" : "Copy"}
      </button>
    </span>
  );
}

/* ---------------------------------------------------------------- six-step pipeline */
export const STEPS = [
  ["understand", "Understand", "Read the request as untrusted data"],
  ["plan", "Plan", "Fit it into the student's obligations"],
  ["verify", "Verify", "Check payee and account against the registry"],
  ["commit", "Commit", "Signed intent and policy decision"],
  ["execute", "Execute & watch", "Pay through the rail, watch for tampering"],
  ["prove", "Prove", "Proof pack, audit chain, anchor"],
];
const KEYS = ["Understand", "Plan", "Verify", "Commit", "Execute", "Prove"];

/** Derive the per-step trail of one payment outcome from its trace lines, status and verification. */
export function trailOf(o) {
  const by = {};
  (o.trace || []).forEach((t) => {
    const m = /^(Understand|Plan|Verify|Commit|Execute|Prove)\b[^:]*:\s*(.*)$/.exec(t);
    if (m) (by[m[1]] ||= []).push(m[2]);
  });
  if (!by.Plan && o.savings?.route) by.Plan = [`route selected: ${o.savings.route} (single payment)`];   // only when the outcome carries route info
  const present = KEYS.map((k) => !!by[k]);
  const lastPresent = present.lastIndexOf(true);
  const verifyBad = o.verification && (o.verification.account_changed || ["unverified", "needs_verification"].includes(o.verification.level));
  const stopped = ["frozen", "rejected"].includes(o.status);
  let stopIdx = -1;
  if (stopped) stopIdx = o.canary_hits?.length ? 0 : verifyBad ? 2 : Math.max(lastPresent, 0);
  const f = o.fields, dec = o.decision, ver = o.verification;
  const nice = {
    Understand: () => o.canary_hits?.length ? `Decoy touched: ${o.canary_hits.map((h) => h.kind).join(", ")}`
      : f ? `Read ${cny(f.amount)} to ${f.payee_name} as untrusted data${o.risk ? `, risk ${o.risk.score}` : ""}` : "",
    Plan: () => (by.Plan?.[0] || (o.savings?.route ? `route selected: ${o.savings.route} (single payment)` : "Single payment, no schedule change")),
    Verify: () => ver ? `${label(ver.level)}${ver.account_changed ? ", account differs from registry" : ""}${ver.reasons?.[0] ? `: ${ver.reasons[0]}` : ""}` : "",
    Commit: () => dec ? `${dec.action === "hold" ? "Held" : label(dec.action)} by ${dec.rule}${dec.required_approvals?.length ? `: needs ${needsText(dec.required_approvals)}` : ""}` : "",
    Execute: () => by.Execute?.[0] || "",
    Prove: () => by.Prove?.[0] || "",
  };
  return KEYS.map((k, i) => {
    const lines = by[k] || [];
    const detail = (lines.length || k === "Plan") && nice[k] ? nice[k]() || lines[0] || "" : lines[0] || "";
    const base = { key: k, detail, full: lines.join(" | ") };
    if (stopIdx >= 0) {
      if (i < stopIdx) return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? "Passed" : "n/a" };
      if (i === stopIdx) {
        const text = k === "Understand" && o.canary_hits?.length ? "Tripwire fired, frozen" : k === "Verify" ? "Mismatch, stopped" : o.status === "frozen" ? "Frozen here" : "Rejected here";
        return { ...base, state: "stop", text, detail: i === 2 && o.verification?.reasons?.[0] ? o.verification.reasons[0] : detail };
      }
      return { ...base, state: "idle", text: "Not reached", detail: "" };
    }
    if (o.status === "held") {
      if (k === "Commit") {
        const req = o.decision?.required_approvals || [];
        const text = req.includes("risk_review") ? "Needs review outside this document" : req.includes("duplicate_confirmation") ? "Possible duplicate"
          : req.length && !approvable(req) ? "Held, needs action outside Oasis" : "Waiting for approval";
        return { ...base, state: "warn", text };
      }
      if (i < 3) return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? "Passed" : "n/a" };
      return { ...base, state: "idle", text: "Not yet", detail: "" };
    }
    if (o.status === "paid") return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? "Done" : "n/a" };
    return { ...base, state: present[i] ? "ok" : "off", text: present[i] ? "Done" : "n/a" };
  });
}

export function PipelineTrail({ outcome }) {
  if (!outcome?.trace?.length) return null;
  const steps = trailOf(outcome);
  return (
    <div>
      <ol className="trail" aria-label="Six-step pipeline outcome">
        {steps.map((s, i) => (
          <li key={s.key} className={`${s.state}`}>
            <div className="node"><span className="dot" aria-hidden="true">{s.state === "ok" ? "✓" : s.state === "stop" ? "✕" : s.state === "warn" ? "!" : i + 1}</span><span className="bar" aria-hidden="true" /></div>
            <div className="name">{STEPS[i][1]}</div>
            <div className="st">{s.text}</div>
            {s.detail && <div className="why" title={s.full}>{s.detail.length > 96 ? `${s.detail.slice(0, 96)}…` : s.detail}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Compact marker of which steps a scripted demo step exercises. */
export function MiniTrail({ items }) {
  return (
    <ol className="minitrail" aria-label="Pipeline steps exercised">
      {STEPS.map(([k, n]) => <li key={k} className={items?.includes(k) ? "on" : ""}>{n}{items?.includes(k) && <span className="sr-only"> (exercised)</span>}</li>)}
    </ol>
  );
}
