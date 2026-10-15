import { useCallback, useState } from "react";
import { signApproval } from "./crypto.js";
import { getLang, t } from "./i18n/index.js";
import { ApiError, formatDetail } from "./ui.jsx";

/* Hooks the app shell installs: a 401 (or a 403 about the ROLE) returns the user to the login screen; a 410 (draft expired)
   refreshes the pending list. The role problem is recognised by the server's language-neutral `code`, not by its wording. */
const handlers = { unauth: () => {}, expired: () => {} };
export const setApiHandlers = (h) => Object.assign(handlers, h);

/** Every request carries the interface language (X-Oasis-Lang), so the server's own text (why-cards, plans, errors) arrives in it. */
/* Signed documents (proof packs, Evidence Passports) must go back to the server byte for byte: the server signs numbers like 6000.0,
   and a JavaScript parse + stringify turns them into 6000, which breaks every signature and hash ("only a passport that verifies ...
   can be shared"). The exact response text is kept for each parsed object and sent back whenever that object is posted. */
const RAW = new WeakMap();
function stringifyRaw(body) {
  const subs = [];
  const s = JSON.stringify(body, (k, v) => {
    if (v && typeof v === "object" && RAW.has(v)) { subs.push(RAW.get(v)); return `__oasis_raw_${subs.length - 1}__`; }
    return v;
  });
  return s.replace(/"__oasis_raw_(\d+)__"/g, (_, i) => subs[+i]);
}

export const api = async (path, body) => {
  let r;
  const headers = { "X-Oasis-Lang": getLang() };
  try {
    r = await fetch(`/api${path}`, body === undefined ? { headers } : {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: typeof body === "string" ? body : stringifyRaw(body),
    });
  } catch {
    throw new ApiError(0, "Network error");
  }
  if (!r.ok) {
    let msg = await r.text().catch(() => ""), code;
    try {
      const j = JSON.parse(msg);
      code = j.code;
      msg = formatDetail(j.detail ?? msg);
    } catch { /* plain text */ }
    if (typeof msg !== "string") msg = JSON.stringify(msg);
    const authPath = path.startsWith("/auth/login") || path.startsWith("/auth/passkey/login") || path === "/auth/me";
    if (!authPath && (r.status === 401 || (r.status === 403 && code === "role_not_allowed"))) handlers.unauth(r.status);   // other 403s (bad signature, cross-origin) stay inline
    if (r.status === 410) handlers.expired();
    throw new ApiError(r.status, msg || r.statusText, r.headers.get("Retry-After"), code);
  }
  try {
    const text = await r.text(), obj = JSON.parse(text);
    if (obj && typeof obj === "object") RAW.set(obj, text);
    return obj;
  } catch { throw new ApiError(502, t("err.unreadable")); }
};

/** Upload one file as multipart (email intake); same language header and error handling as `api`. */
export const upload = async (path, file) => {
  const fd = new FormData();
  fd.append("file", file);
  let r;
  try { r = await fetch(`/api${path}`, { method: "POST", headers: { "X-Oasis-Lang": getLang() }, body: fd }); }
  catch { throw new ApiError(0, "Network error"); }
  if (!r.ok) {
    let msg = await r.text().catch(() => "");
    try { msg = formatDetail(JSON.parse(msg).detail ?? msg); } catch { /* plain text */ }
    throw new ApiError(r.status, (typeof msg === "string" ? msg : JSON.stringify(msg)) || r.statusText);
  }
  try { return await r.json(); } catch { throw new ApiError(502, t("err.unreadable")); }
};

// Signed approvals: the device key signs the exact draft; the server verifies against the role's registered public key.
export const signedApprove = (role, id, draft) => api("/approve", { pending_id: id, ...signApproval(role, draft) });
export const markSession = (on) => { try { on ? localStorage.setItem("oasis.session", "1") : localStorage.removeItem("oasis.session"); } catch { /* storage blocked */ } };
export const short4 = (k) => (k ? `${k.slice(0, 4)}…` : "?");

/** Run an async action with busy + error state. */
export function useGuard() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const run = useCallback(async (fn) => {
    setBusy(true); setErr(null);
    try { return await fn(); } catch (e) { setErr(e); return undefined; } finally { setBusy(false); }
  }, []);
  return { busy, err, setErr, run };
}

export const downloadJson = (obj, name) => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/** "Download as PDF" without a library: a formatted report opens in a hidden frame and the browser's print dialog saves it as a PDF.
    `title` is the document title (also the suggested file name); `heading` and `subtitle` are shown in the report header. */
const REPORT_CSS = `
@page { size: A4; margin: 18mm 14mm 18mm; @bottom-left { content: "Oasis — simulated data only"; font: 8pt system-ui, sans-serif; color: #667; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 8pt system-ui, sans-serif; color: #667; } }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font: 10.5pt/1.55 "Segoe UI", system-ui, -apple-system, sans-serif; color: #172033; margin: 0; }
.rp-head { background: #0B0F1E; color: #fff; padding: 18px 22px; border-radius: 8px; border-bottom: 4px solid #22d3ee; display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.rp-head img { height: 34px; display: block; }
.rp-head .meta { text-align: right; font-size: 8.5pt; color: #b6c2d9; line-height: 1.5; }
.rp-title { margin: 22px 0 4px; font-size: 20pt; line-height: 1.2; color: #0B0F1E; }
.rp-sub { margin: 0 0 14px; color: #556; font-size: 10pt; }
.rp-note { margin: 0 0 18px; padding: 8px 12px; border: 1px solid #e3c36a; background: #fff8e1; border-radius: 6px; font-size: 8.5pt; color: #6b4e00; }
h3, h4, h5 { color: #0B0F1E; margin: 18px 0 6px; break-after: avoid; }
h3 { font-size: 14pt; border-bottom: 2px solid #22d3ee; padding-bottom: 3px; }
h4 { font-size: 12pt; } h5 { font-size: 10.5pt; }
details { margin: 14px 0; }
summary { list-style: none; font-size: 13pt; font-weight: 700; color: #0B0F1E; border-bottom: 2px solid #22d3ee; padding-bottom: 3px; margin-bottom: 8px; break-after: avoid; }
summary::-webkit-details-marker, summary::marker { display: none; content: ""; }
p { margin: 6px 0; } ul { margin: 6px 0; padding-left: 20px; } li { margin: 2px 0; }
code { font: 9pt ui-monospace, Consolas, monospace; background: #eef2f7; border: 1px solid #d5dce6; border-radius: 3px; padding: 0 3px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0 14px; font-size: 8.8pt; border: 1px solid #98a4b8; }
thead { display: table-header-group; }
th { background: #0B0F1E; color: #fff; text-align: left; font-weight: 600; padding: 6px 8px; border: 1px solid #0B0F1E; }
td { padding: 5px 8px; border: 1px solid #c9d1de; vertical-align: top; }
tbody tr:nth-child(even) td { background: #f3f6fb; }
tr { break-inside: avoid; }
th.r, td.r { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { font-weight: 600; }
pre { font: 8pt/1.4 ui-monospace, Consolas, monospace; white-space: pre-wrap; word-break: break-all; border: 1px solid #c9d1de; background: #f7f9fc; border-radius: 6px; padding: 10px; }
.mock { color: #8a5a00; font-weight: 600; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0 8px; }
.kpi { border: 1px solid #c9d1de; border-top: 3px solid #22d3ee; border-radius: 6px; padding: 8px 10px; background: #f7f9fc; break-inside: avoid; }
.kpi span { display: block; font-size: 7.5pt; text-transform: uppercase; letter-spacing: .05em; color: #556; }
.kpi b { display: block; font-size: 15pt; color: #0B0F1E; margin: 2px 0; }
.kpi small { color: #667; font-size: 7.5pt; line-height: 1.3; display: block; }
.chart { border: 1px solid #c9d1de; border-radius: 6px; padding: 10px 12px; margin: 8px 0 12px; break-inside: avoid; }
.legend { display: flex; gap: 16px; font-size: 8pt; margin-bottom: 6px; color: #334; }
.legend i { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 5px; }
.brow { display: grid; grid-template-columns: 34% 1fr; gap: 10px; align-items: center; padding: 3px 0; }
.blabel { font-size: 8.8pt; color: #172033; }
.btrack { position: relative; height: 15px; margin: 2px 0; background: #eef2f7; border-radius: 3px; }
.bfill { height: 100%; border-radius: 3px; }
.bval { position: absolute; left: 6px; top: 0; line-height: 15px; font-size: 8pt; font-weight: 700; color: #0B0F1E; mix-blend-mode: normal; text-shadow: 0 0 3px #fff, 0 0 3px #fff; }
.qrbox { display: flex; gap: 16px; align-items: center; } .qrbox svg { width: 120px; height: 120px; flex: none; } .cnote { margin: 6px 0 0; font-size: 8pt; color: #667; }
`;
export const downloadPdf = (html, title, { heading, subtitle, note } = {}) => {
  const f = document.createElement("iframe");
  f.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(f);
  const esc = (x) => String(x ?? "").replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[m]);
  const d = f.contentWindow.document;
  d.open();
  d.write(`<!doctype html><meta charset="utf-8"><title>${esc(title)}</title><style>${REPORT_CSS}</style>
    <div class="rp-head"><img id="rp-logo" src="${location.origin}/oasis-logo.svg" alt="OASIS"><div class="meta">${esc(new Date().toISOString().slice(0, 10))}<br>${esc(location.host)}</div></div>
    ${heading ? `<h1 class="rp-title">${esc(heading)}</h1>` : ""}${subtitle ? `<p class="rp-sub">${esc(subtitle)}</p>` : ""}
    ${note ? `<p class="rp-note">${esc(note)}</p>` : ""}${html}`);
  d.close();
  const go = () => { f.contentWindow.focus(); f.contentWindow.print(); setTimeout(() => f.remove(), 2000); };
  const img = d.getElementById("rp-logo");
  let fired = false;
  const once = () => { if (!fired) { fired = true; go(); } };
  if (img && !img.complete) { img.onload = once; img.onerror = once; setTimeout(once, 1500); } else setTimeout(once, 150);
};
