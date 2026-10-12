import { useCallback, useState } from "react";
import { signApproval } from "./crypto.js";
import { getLang, t } from "./i18n/index.js";
import { ApiError, formatDetail } from "./ui.jsx";

/* Hooks the app shell installs: a 401 (or a 403 about the ROLE) returns the user to the login screen; a 410 (draft expired)
   refreshes the pending list. The role problem is recognised by the server's language-neutral `code`, not by its wording. */
const handlers = { unauth: () => {}, expired: () => {} };
export const setApiHandlers = (h) => Object.assign(handlers, h);

/** Every request carries the interface language (X-Oasis-Lang), so the server's own text (why-cards, plans, errors) arrives in it. */
export const api = async (path, body) => {
  let r;
  const headers = { "X-Oasis-Lang": getLang() };
  try {
    r = await fetch(`/api${path}`, body === undefined ? { headers } : {
      method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: typeof body === "string" ? body : JSON.stringify(body),
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
  try { return await r.json(); } catch { throw new ApiError(502, t("err.unreadable")); }
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
