import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { t, useLang } from "../i18n/index.js";
import { cny, ErrorBox, Mock, Skeleton } from "../ui.jsx";

export function Netting() {
  useLang();
  const [bench, setBench] = useState(null);
  const [size, setSize] = useState(50);
  const [sim, setSim] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => { setErr(null); api("/netting/benchmark").then(setBench).catch(setErr); }, []);
  useEffect(() => { load(); }, [load]);
  const run = () => {
    const n = Number(size);
    if (!Number.isInteger(n) || n < 1 || n > 2000) { setSim(null); setErr(new Error(t("net.size.invalid"))); return; }   // QA: a bad size left the old result on screen and showed a raw 422
    setErr(null); api("/netting/simulate", { pool_size: n }).then(setSim).catch(setErr);
  };
  return (
    <section aria-labelledby="net-h" className="stack">
      <div>
        <h2 id="net-h">{t("net.title")}</h2>
        <p className="lead"><Mock /> {t("net.lead")}</p>
        <p className="muted small">{t("net.disclaimer")}</p>
      </div>
      <ErrorBox error={err} onRetry={load} />
      <div className="card net-form">
        <div className="formgrid">
          <label className="c6">{t("net.size")} <input type="number" min="1" max="2000" value={size} onChange={(e) => setSize(e.target.value)} /></label>
          <div className="c3"><button type="button" className="cta" onClick={run}>{t("net.run")}</button></div>
        </div>
        {sim && (
          <div className="kpis">
            <div className="kpi"><div className="k">{t("net.matched")}</div><div className="v">{cny(sim.matched_volume_cny)}</div></div>
            <div className="kpi"><div className="k">{t("net.alone")}</div><div className="v">{cny(sim.cost_alone_cny)}</div></div>
            <div className="kpi"><div className="k">{t("net.netted")}</div><div className="v">{cny(sim.cost_netted_cny)}</div></div>
            <div className="kpi"><div className="k">{t("net.saving")}</div><div className="v">{cny(sim.saving_cny)} ({sim.saving_pct}%)</div></div>
          </div>)}
        {sim && Number(size) === 1 && <p className="muted small">{t("net.solo")}</p>}
      </div>
      <div className="card">
        <h3>{t("net.bench")}</h3>
        {!bench && !err && <Skeleton rows={4} />}
        {bench && (
          <div className="tbl"><table className="metrics" aria-label={t("net.bench")}>
            <thead><tr><th>{t("net.col.size")}</th><th className="r">{t("net.col.matched")}</th><th className="r">{t("net.col.saving")}</th><th className="r">{t("net.col.pct")}</th></tr></thead>
            <tbody>{bench.rows.map((r) => <tr key={r.pool_size}><td>{r.pool_size}</td><td className="r num">{r.matched_pct}%</td><td className="r num">{cny(r.saving_cny)}</td><td className="r num">{r.saving_pct}%</td></tr>)}</tbody>
          </table></div>)}
      </div>
    </section>
  );
}
