import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { t } from "../i18n/index.js";
import { cny, ErrorBox, fmt, fmtDate, Mock, pct, Skeleton } from "../ui.jsx";

/** Round, evenly spaced axis ticks that cover [lo, hi] (about n of them). */
function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1, raw = span / (n - 1), mag = 10 ** Math.floor(Math.log10(raw)), norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const out = [];
  for (let v = Math.floor(lo / step) * step; ; v += step) { out.push(+v.toFixed(6)); if (v >= hi - 1e-9) break; }   // last tick is at or above hi
  return out;
}
const compact = (v) => (Math.abs(v) >= 1e6 ? `${fmt(v / 1e6, 1)}M` : Math.abs(v) >= 1e3 ? `${fmt(v / 1e3, v % 1e3 ? 1 : 0)}k` : fmt(v));

/** Smooth line through the points without overshoot (monotone cubic), as an SVG path. */
function smooth(pts) {
  const n = pts.length;
  if (n < 3) return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const dx = [], m = [], tg = [];
  for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; m[i] = (pts[i + 1][1] - pts[i][1]) / (dx[i] || 1); }
  tg[0] = m[0]; tg[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) tg[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { tg[i] = tg[i + 1] = 0; continue; }
    const a = tg[i] / m[i], b = tg[i + 1] / m[i], q = a * a + b * b;
    if (q > 9) { const k = 3 / Math.sqrt(q); tg[i] = k * a * m[i]; tg[i + 1] = k * b * m[i]; }
  }
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3, [x0, y0] = pts[i], [x1, y1] = pts[i + 1];
    d += `C${(x0 + h).toFixed(1)},${(y0 + tg[i] * h).toFixed(1)},${(x1 - h).toFixed(1)},${(y1 - tg[i + 1] * h).toFixed(1)},${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  return d;
}

/** Fan chart of the simulated balance: p10..p90 band, median line, gridlines, readable axes, a legend and a hover read-out.
    It draws at the width it is given (re-measured on resize), so text stays crisp and the plot never gets squashed. The summary
    is in the aria-label for screen readers. */
function Fan({ fan }) {
  const box = useRef(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState(null);
  useLayoutEffect(() => {
    const el = box.current;
    const ro = new ResizeObserver(() => setW(Math.max(280, Math.round(el.clientWidth))));
    ro.observe(el); setW(Math.max(280, Math.round(el.clientWidth)));
    return () => ro.disconnect();
  }, []);
  const H = Math.round(Math.min(360, Math.max(230, w * 0.36))), PAD = { l: 50, r: 16, t: 14, b: 34 };
  const maxD = fan[fan.length - 1].day || 1;
  const yt = niceTicks(Math.min(0, ...fan.map((f) => f.p10)), Math.max(...fan.map((f) => f.p90), 1), 5);
  const lo = yt[0], hi = yt[yt.length - 1];
  const xt = niceTicks(0, maxD, w < 420 ? 4 : 7).filter((v) => v >= 0 && v <= maxD);
  const x = (d) => PAD.l + (d / maxD) * (w - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);
  const pts = (k) => fan.map((f) => [x(f.day), y(f[k])]);
  const top = smooth(pts("p90")), bottomRev = smooth(pts("p10").reverse());
  const band = `${top}L${bottomRev.slice(1)}Z`;
  const median = smooth(pts("p50"));
  const last = fan[fan.length - 1];
  const over = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const d = ((e.clientX - r.left) / r.width * w - PAD.l) / (w - PAD.l - PAD.r) * maxD;
    let best = 0;
    fan.forEach((f, i) => { if (Math.abs(f.day - d) < Math.abs(fan[best].day - d)) best = i; });
    setHover(best);
  };
  const hv = hover === null ? null : fan[hover];
  return (
    <div className="twin-chart" ref={box}>
      <svg width={w} height={H} viewBox={`0 0 ${w} ${H}`} role="img" aria-label={t("twin.fan.aria", { p50: cny(last.p50), p10: cny(last.p10), p90: cny(last.p90) })}
        onPointerMove={over} onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="twArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#06b6d4" stopOpacity=".2" /><stop offset="1" stopColor="#06b6d4" stopOpacity="0" /></linearGradient>
        </defs>
        {yt.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(v)} y2={y(v)} stroke="rgba(255,255,255,0.06)" strokeDasharray={v === 0 ? "" : "3 3"} />
            <text className="tw-axis" x={PAD.l - 10} y={y(v) + 4} textAnchor="end">{v < 0 ? "-" : ""}¥{compact(Math.abs(v))}</text>
          </g>))}
        {xt.map((d) => <text className="tw-axis" key={d} x={x(d)} y={H - PAD.b + 19} textAnchor="middle">{d}</text>)}
        <text className="tw-axis" x={w - PAD.r} y={H - 3} textAnchor="end">{t("twin.fan.x")}</text>
        <path d={band} fill="rgba(34,211,238,0.07)" stroke="none"><title>{t("twin.p10")} - {t("twin.p90")}</title></path>
        <path d={`${median}L${x(maxD).toFixed(1)},${y(lo).toFixed(1)}L${x(0).toFixed(1)},${y(lo).toFixed(1)}Z`} fill="url(#twArea)" stroke="none" />
        <path d={median} fill="none" stroke="#22d3ee" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><title>{t("twin.p50")}</title></path>
        {hv && (
          <g pointerEvents="none">
            <line x1={x(hv.day)} x2={x(hv.day)} y1={PAD.t} y2={H - PAD.b} stroke="rgba(255,255,255,0.2)" strokeWidth="1" />
            <circle cx={x(hv.day)} cy={y(hv.p50)} r={4} fill="#0B0F1E" stroke="#22d3ee" strokeWidth={2} />
          </g>)}
        <rect x={PAD.l} y={PAD.t} width={w - PAD.l - PAD.r} height={H - PAD.t - PAD.b} fill="transparent" />
      </svg>
      {hv && (
        <div className="twin-tip" style={{ left: `${Math.min(Math.max(x(hv.day), 90), w - 90)}px` }} role="status">
          <b>{t("twin.fan.x")}: {hv.day}</b>
          <span><i className="sw hi" />{t("twin.p90")} <em>{cny(hv.p90)}</em></span>
          <span><i className="sw mid" />{t("twin.p50")} <em>{cny(hv.p50)}</em></span>
          <span><i className="sw lo" />{t("twin.p10")} <em>{cny(hv.p10)}</em></span>
        </div>)}
      <div className="twin-legend">
        <span><i className="sw band" />{t("twin.p10")} – {t("twin.p90")}</span>
        <span><i className="sw line" />{t("twin.p50")}</span>
      </div>
    </div>
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
        </div>
        <div className="card">
          <h3>{t("twin.mit")}</h3>
          <p>{best ? t("twin.mit.best", { m: mname(best), from: pct(b.p_all_met), to: pct(best.p_all_met), d: fmt(best.improvement * 100, 1) }) : t("twin.mit.none")}</p>
          <div className="tbl"><table aria-label={t("twin.mit")}><thead><tr><th>{t("twin.col.mit")}</th><th className="r">{t("twin.col.to")}</th><th className="r">{t("twin.col.d")}</th></tr></thead>
            <tbody>{r.mitigations.map((m) => <tr key={m.id}><td>{mname(m)}</td><td className="r num">{pct(m.p_all_met)}</td><td className="r num">{m.improvement >= 0 ? "+" : ""}{fmt(m.improvement * 100, 1)}</td></tr>)}</tbody></table></div>
        </div>
        <div className="card twin-controls">
          <label className="field">{t("twin.seed")}
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} /></label>
          <label className="check twin-rescue"><input type="checkbox" checked={rescue} onChange={(e) => setRescue(e.target.checked)} /> <span>{t("twin.rescue")}</span></label>
          <button type="button" onClick={load}>{t("twin.rerun")}</button>
        </div>
      </>)}
    </section>
  );
}
