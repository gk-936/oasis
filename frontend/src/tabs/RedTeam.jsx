import React, { useState } from "react";
import { api, useGuard } from "../api.js";
import { Outcome, SAMPLE_ATTACK } from "../common.jsx";
import { t, tl, tm } from "../i18n/index.js";
import { announce, cny, Empty, ErrorBox, fmt, Loading, Mock, R } from "../ui.jsx";

const MAX_BYTES = 4000;

export function RedTeam({ onProof }) {
  const [text, setText] = useState(SAMPLE_ATTACK);
  const [poison, setPoison] = useState("");
  const [o, setO] = useState(null);
  const [log, setLog] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const bytes = new TextEncoder().encode(text).length;
  const go = () => run(async () => {
    const body = { text };
    if (poison.trim()) body.tool_poison = { account_ref: poison.trim() };
    const res = await api("/redteam", body);
    setO(res); announce(t("red.announce", { status: tl("status", res.status), amount: cny(res.money_lost_this_attempt, 2) }));
    setLog(await api("/redteam/log"));
  });
  return (
    <section aria-labelledby="rt-h" className="stack">
      <div>
        <h2 id="rt-h">{t("red.title")}</h2>
        <p className="lead">{R("red.lead.pre")} <Mock />{R("red.lead.post")}</p>
      </div>
      <div className="card">
        <label>{t("red.text.label")}
          <textarea rows={9} value={text} onChange={(e) => setText(e.target.value)} aria-describedby="rt-bytes" /></label>
        <p id="rt-bytes" className={`small ${bytes > MAX_BYTES ? "bad" : "muted"}`}>{t("red.bytes", { n: fmt(bytes), max: fmt(MAX_BYTES) })}{bytes > MAX_BYTES ? t("red.toolong") : ""}</p>
        <label>{t("red.poison.label")}
          <input value={poison} onChange={(e) => setPoison(e.target.value)} placeholder={t("red.poison.ph")} /></label>
        <div className="row">
          <button disabled={busy || bytes > MAX_BYTES || !text.trim()} onClick={go}>{t("red.run")}</button>
          <button className="ghost" disabled={busy} onClick={() => { setText(SAMPLE_ATTACK); setPoison(""); }}>{t("red.reset")}</button>
          {busy && <Loading>{t("red.running")}</Loading>}
        </div>
        <ErrorBox error={err} onDismiss={() => setErr(null)} />
      </div>
      {o && (
        <div className="card" aria-live="polite">
          <div className="kpis">
            <div className="kpi"><div className="k">{t("red.kpi.lost")}</div><div className="v">{cny(o.money_lost_this_attempt, 2)}</div></div>
            {log && <div className="kpi"><div className="k">{t("red.kpi.attempts")}</div><div className="v">{log.attempts.length}</div></div>}
            {log && <div className="kpi"><div className="k">{t("red.kpi.total")}</div><div className="v">{cny(log.total_lost, 2)}</div></div>}
          </div>
          {log?.isolation && <p className="muted small">{t("red.isolation", { text: tm(log.isolation) })}</p>}
          <Outcome o={o} onProof={onProof} />
        </div>
      )}
      {!o && !busy && <Empty title={t("red.empty.title")}>{t("red.empty.text")}</Empty>}
    </section>
  );
}
