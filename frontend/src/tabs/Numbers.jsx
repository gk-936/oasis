import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { t, tl, useLang } from "../i18n/index.js";
import { cny, Empty, ErrorBox, fmt, Mock, R, Skeleton } from "../ui.jsx";

const METRICS = [["num.m.block", "attack_block_rate"], ["num.m.lost", "money_lost_cny"], ["num.m.detect", "detection_rate"],
  ["num.m.legit", "legit_completion_rate"], ["num.m.false", "false_block_rate"],
  ["num.m.canary", "canary_detections"], ["num.m.minutes", "mean_minutes_to_resolve_legit"],
  ["num.m.redteam", "redteam_block_rate"]];
const metric = (k, v) => v == null ? t("misc.na") : k === "money_lost_cny" ? cny(v) : k.endsWith("_rate") ? `${+(v * 100).toFixed(1)}%` : k.startsWith("mean_minutes") ? t("num.min", { n: v }) : fmt(v, 1);

export function Numbers() {
  const { lang } = useLang();
  const [b, setB] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => { setErr(null); api("/benchmark").then(setB).catch(setErr); }, []);
  useEffect(() => { load(); }, [load]);
  const bm = b?.benchmark;
  const cfgs = ["baseline", "+verification", "+intents+policy", "full"];
  const full = bm?.summary.full, base = bm?.summary.baseline;
  const english = lang !== "en" ? <span className="muted small"> {t("num.reports.english")}</span> : null;
  return (
    <section aria-labelledby="num-h" className="stack">
      <div>
        <h2 id="num-h">{t("num.title")}</h2>
        <p className="lead"><Mock /> {t("num.lead")}</p>
      </div>
      <ErrorBox error={err} onRetry={load} />
      {!bm && !err && !b && <Skeleton rows={5} />}
      {bm && (
        <>
          <div className="kpis">
            <div className="kpi"><div className="k">{t("num.kpi.block")}</div><div className="v">{metric("attack_block_rate", full.attack_block_rate)}</div><div className="small muted">{t("num.baseline", { v: metric("attack_block_rate", base.attack_block_rate) })}</div></div>
            <div className="kpi"><div className="k">{t("num.kpi.lost")}</div><div className="v">{metric("money_lost_cny", full.money_lost_cny)}</div><div className="small muted">{t("num.baseline", { v: metric("money_lost_cny", base.money_lost_cny) })}</div></div>
            <div className="kpi"><div className="k">{t("num.kpi.legit")}</div><div className="v">{metric("legit_completion_rate", full.legit_completion_rate)}</div><div className="small muted">{t("num.falseblocks", { v: metric("false_block_rate", full.false_block_rate) })}</div></div>
            <div className="kpi"><div className="k">{t("num.kpi.redteam")}</div><div className="v">{metric("redteam_block_rate", full.redteam_block_rate)}</div><div className="small muted">{t("num.baseline", { v: metric("redteam_block_rate", base.redteam_block_rate) })}</div></div>
          </div>
          <p className="muted small">{t("num.meta", { at: bm.meta.run_at, llm: bm.meta.llm, rs: bm.meta.ruleset, attacks: bm.meta.attacks, legit: bm.meta.legit, red: bm.meta.redteam, repeats: bm.meta.repeats })}</p>
          <div className="card">
            <h3>{t("num.layers")}</h3>
            <div className="tbl"><table className="metrics" aria-label={t("num.table.aria")}><thead><tr><th>{t("num.col.metric")}</th>{cfgs.map((c) => <th key={c} className={`r ${c === "full" ? "full" : ""}`}>{tl("cfg", c)}</th>)}</tr></thead>
              <tbody>{METRICS.map(([l, k]) => <tr key={k}><td>{t(l)}</td>{cfgs.map((c) => <td key={c} className={`r num ${c === "full" ? "full" : ""}`}>{metric(k, bm.summary[c][k])}</td>)}</tr>)}</tbody></table></div>
          </div>
          <div className="grid">
            <div className="card"><h3>{t("num.canaries.title")}</h3>
              <p>{R("num.canaries.text", { extra: bm.summary.canaries.extra_attacks_blocked, early: bm.summary.canaries.attacks_detected_earlier })}</p></div>
            <div className="card"><h3>{t("num.scorer.title")}</h3>
              <p>{t("num.scorer.text", { a: Math.round(bm.summary.risk_scorer.attack_flag_rate * 100), l: Math.round(bm.summary.risk_scorer.legit_flag_rate * 100), acc: Math.round(bm.summary.risk_scorer.accuracy * 100), p: bm.summary.risk_scorer.precision, r: bm.summary.risk_scorer.recall })}</p></div>
          </div>
        </>
      )}
      {b && !bm && <Empty title={t("num.empty.title")}>{R("num.empty.text")}</Empty>}
      {b?.planning_md && <details><summary>{b.planning?.live ? t("num.planning.live", { n: b.planning.live.summary.scenarios_run }) : t("num.planning")}</summary>{english}<pre className="md">{b.planning_md}</pre></details>}
      {b?.benchmark_md && <details><summary>{t("num.full")}</summary>{english}<pre className="md">{b.benchmark_md}</pre></details>}
      {b?.simulation_md && <details><summary>{t("num.sim")}</summary>{english}<pre className="md">{b.simulation_md}</pre></details>}
    </section>
  );
}
