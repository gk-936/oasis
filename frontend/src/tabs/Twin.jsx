import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { t } from "../i18n/index.js";
import { cny, ErrorBox, fmt, fmtDate, Mock, pct, Skeleton } from "../ui.jsx";

const W = 640, H = 240, PAD = { l: 64, r: 12, t: 12, b: 30 };

/** Accessible SVG fan chart: p10..p90 band and median line; the summary is in the aria-label. */
function Fan({ fan }) {
  const maxD = fan[fan.length - 1].day || 1;
  const lo = Math.min(0, ...fan.map((f) => f.p10)), hi = Math.max(...fan.map((f) => f.p90), 1);
  const x = (d) => PAD.l + (d / maxD) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const line = (k) => fan.map((f, i) => `${i ? "L" : "M"}${x(f.day).toFixed(1)},${y(f[k]).toFixed(1)}`).join("");
  const band = `${line("p90")}${fan.slice().reverse().map((f) => `L${x(f.day).toFixed(1)},${y(f.p10).toFixed(1)}`).join("")}Z`;
  const last = fan[fan.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" className="twin-fan" style={{ width: "100%", height: "auto" }}
      aria-label={t("twin.fan.aria", { p50: cny(last.p50), p10: cny(last.p10), p90: cny(last.p90) })}>
      {[lo, (lo + hi) / 2, hi].map((v) => <g key={v}><line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="currentColor" opacity="0.15" /><text x={PAD.l - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="currentColor">{fmt(v)}</text></g>)}
      <path d={band} fill="currentColor" opacity="0.3" stroke="currentColor" strokeOpacity="0.5" strokeWidth="1"><title>{t("twin.p10")} - {t("twin.p90")}</title></path>
      <path d={line("p50")} fill="none" stroke="currentColor" strokeWidth="2"><title>{t("twin.p50")}</title></path>
      <text x={(PAD.l + W - PAD.r) / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="currentColor">{t("twin.fan.x")}</text>
    </svg>
  );
}

export function Twin() {
  const [seed, setSeed] = useState(7);
  const [rescue, setRescue] = useState(false);
  const [r, setR] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => { setErr(null); api(`/twin?seed=${seed}&rescue=${rescue}`).then(setR).catch(setErr); }, [seed, rescue]);
  useEffect(() => { load(); }, [load]);
  const b = r?.baseline, best = r?.mitigations.find((m) => m.id === r.recommended);
  const mname = (m) => t(`twin.m.${m.id}`, { n: m.topup_cny ? cny(m.topup_cny) : "" });
  return (
    <section aria-labelledby="twin-h" className="stack">
      <div>
        <h2 id="twin-h">{t("twin.title")}</h2>
        <p className="lead"><Mock /> {t("twin.lead")}</p>
      </div>
      <ErrorBox error={err} onRetry={load} />
      {!r && !err && <Skeleton rows={5} />}
      {r && (<>
        <p className="muted small">{t("twin.assump", { vol: +(r.assumptions.fx_daily_vol * 100).toFixed(2), late: Math.round(r.assumptions.topup_late_prob * 100), short: Math.round(r.assumptions.short_credit_prob * 100), seed: r.seed, paths: r.paths })}</p>
        <div className="card">
          <h3>{t("twin.deadlines")}</h3>
          <div className="tbl"><table aria-label={t("twin.deadlines")}><thead><tr><th>{t("twin.col.deadline")}</th><th>{t("twin.col.due")}</th><th className="r">{t("twin.col.p")}</th></tr></thead>
            <tbody>{b.deadlines.map((d) => <tr key={d.id}><td>{d.label}</td><td>{fmtDate(d.due)}</td><td className="r num">{pct(d.p_met)}</td></tr>)}</tbody></table></div>
          <p><strong>{t("twin.all", { p: pct(b.p_all_met) })}</strong></p>
        </div>
        <div className="card">
          <h3>{t("twin.fan")}</h3>
          <Fan fan={b.fan} />
          <p className="muted small">{t("twin.p10")} / {t("twin.p50")} / {t("twin.p90")}</p>
        </div>
        <div className="card">
          <h3>{t("twin.mit")}</h3>
          <p>{best ? t("twin.mit.best", { m: mname(best), from: pct(b.p_all_met), to: pct(best.p_all_met), d: fmt(best.improvement * 100, 1) }) : t("twin.mit.none")}</p>
          <div className="tbl"><table aria-label={t("twin.mit")}><thead><tr><th>{t("twin.col.mit")}</th><th className="r">{t("twin.col.to")}</th><th className="r">{t("twin.col.d")}</th></tr></thead>
            <tbody>{r.mitigations.map((m) => <tr key={m.id}><td>{mname(m)}</td><td className="r num">{pct(m.p_all_met)}</td><td className="r num">{m.improvement >= 0 ? "+" : ""}{fmt(m.improvement * 100, 1)}</td></tr>)}</tbody></table></div>
        </div>
        <div className="row">
          <label>{t("twin.seed")} <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} /></label>
          <button type="button" onClick={load}>{t("twin.rerun")}</button>
          <label><input type="checkbox" checked={rescue} onChange={(e) => setRescue(e.target.checked)} /> {t("twin.rescue")}</label>
        </div>
      </>)}
    </section>
  );
}
