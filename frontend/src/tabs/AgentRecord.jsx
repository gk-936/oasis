import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { t } from "../i18n/index.js";
import { cny, ErrorBox, Skeleton } from "../ui.jsx";

const STOP_MSG = { recurring_bill: "stop my autopay", rate_target: "remove the rate alert" };
const UNTIL_REVOKED = "until you revoke it";   // the server's own wording for "no expiry date"

/** The agent's record, read from GET /api/agent-scorecard. Every number comes from the endpoint; Stop only sends a chat message
    (the draft it creates is signed in the Chat tab), so nothing here ends an instruction by itself. `s` changes after every chat
    reply, approval and reset (the shell refreshes it), which reloads the record. */
export function AgentRecord({ s, role, onStop }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => api("/agent-scorecard").then((x) => { setD(x); setErr(null); }).catch((e) => { if (e.status !== 401 && e.status !== 403) setErr(e); }), []);
  useEffect(() => { load(); }, [load, s]);
  if (!d) return err ? <ErrorBox error={err} onRetry={load} /> : <Skeleton rows={4} />;
  const refusals = Object.entries(d.refusals_by_reason || {});
  const mandates = d.caps?.mandates || [];
  const recipients = s?.passport?.recipients || {};
  const counters = [
    ["agent.acted_alone", d.acted_alone_tier1], ["agent.waiting", d.drafts_waiting_for_you], ["agent.refusals", refusals.reduce((a, [, n]) => a + n, 0)],
    ["agent.scam", d.scam_warnings], ["agent.canary", d.canary_freezes], ["agent.money_lost", Number(d.money_lost_cny).toFixed(2)],
  ];
  return (
    <div className="card pp-card agent-record">
      <div className="hd"><h3>{t("agent.title")}</h3><button className="ghost" onClick={load}>{t("agent.refresh")}</button></div>
      <p className="muted small">{t("agent.subtitle")}</p>
      <blockquote className="agent-quote">{d.mandate_card}</blockquote>
      <p className="muted small">{t("agent.tier1", { n: cny(d.caps?.tier1_auto_limit_cny) })}</p>
      {mandates.length === 0 ? <p className="muted">{t("agent.no_mandate")}</p> : (
        <ul className="agent-mandates">{mandates.map((m) => (
          <li key={m.id}>
            <span><b>{m.kind === "rate_target" ? t("agent.kind.rate") : t("agent.kind.bill")}</b>
              {m.payee_id ? ` · ${recipients[m.payee_id]?.name || m.payee_id}` : ""}
              {m.rate ? ` · ${m.rate}` : ""}
              {` · ${t("agent.cap", { n: cny(m.cap_cny) })}`}
              {m.every_days ? ` · ${t("agent.every", { n: m.every_days })}` : ""}
              {` · ${m.expires === UNTIL_REVOKED ? t("agent.until_revoked") : m.expires}`}</span>
            {role === "student" && onStop && STOP_MSG[m.kind] && <button className="ghost" onClick={() => onStop(STOP_MSG[m.kind])}>{t("agent.stop")}</button>}
          </li>))}
        </ul>)}
      {role === "student" && mandates.length > 0 && <p className="muted small">{t("agent.stop_needs_signature")}</p>}
      <div className="agent-counters">{counters.map(([k, v]) => <div key={k}><span>{t(k)}</span><b>{v}</b></div>)}</div>
      <p className="small">{t("agent.audit_head")} <code>{String(d.audit_head || "").slice(0, 12)}</code>{" "}
        <span className={`agent-badge ${d.audit_chain_ok ? "ok" : "bad"}`}>{d.audit_chain_ok ? t("agent.chain_ok") : t("agent.chain_broken")}</span></p>
      <h4>{t("agent.refusals_by")}</h4>
      {refusals.length === 0 ? <p className="muted">{t("agent.no_refusals")}</p> : <ul>{refusals.map(([r, n]) => <li key={r}>{r.replace(/_/g, " ")}: <b>{n}</b></li>)}</ul>}
    </div>
  );
}
