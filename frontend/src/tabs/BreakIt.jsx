import React, { useEffect, useState } from "react";
import { api, useGuard } from "../api.js";
import { Card, SAMPLE_ATTACK } from "../common.jsx";
import { t } from "../i18n/index.js";
import { announce, cny, ErrorBox, Loading, Mock } from "../ui.jsx";

function Verdict({ v }) {
  return (
    <div className="card">
      <p><b className={v.blocked ? "ok" : "bad"}>{v.blocked ? t("brk.blocked") : t("brk.got_through")}</b> · {v.status} · {t("brk.rules")}: <code>{v.rules.join(", ") || "-"}</code></p>
      {v.reasons?.length > 0 && <ul>{v.reasons.map((r, i) => <li key={i}>{String(r)}</li>)}</ul>}
      {v.why_card && <details><summary>{t("brk.why")}</summary><Card card={v.why_card} /></details>}
    </div>
  );
}

function ExecAttacks() {
  const [list, setList] = useState([]);
  const [res, setRes] = useState({});
  const { busy, err, setErr, run } = useGuard();
  useEffect(() => { api("/breakit/executor").then((r) => setList(r.attacks)).catch(() => {}); }, []);
  const one = async (id) => { const r = await api("/breakit/executor", { attack: id }); setRes((m) => ({ ...m, [id]: r })); return r; };
  const all = () => run(async () => { const r = await api("/breakit/executor/all", {}); setRes(Object.fromEntries(r.results.map((x) => [x.attack, x]))); announce(t("brk.exec.all")); });
  return (
    <div className="card">
      <h3>{t("brk.exec.title")}</h3>
      <p className="small">{t("brk.exec.lead")}</p>
      <ul className="small">{list.map((a) => {
        const r = res[a.id];
        return (
          <li key={a.id}>
            <button className="ghost" disabled={busy} onClick={() => run(() => one(a.id))}>{t("brk.exec.run")}</button>{" "}
            {a.label}
            {r && <> → <b className={a.id === "control" ? (r.blocked ? "bad" : "ok") : (r.blocked ? "ok" : "bad")}>{a.id === "control" ? (r.blocked ? t("brk.exec.refused") : t("brk.exec.control")) : (r.blocked ? t("brk.exec.refused") : t("brk.got_through"))}</b> ({r.status}) · {t("brk.exec.moved")}: {cny(r.extra_money_moved, 2)}
              <div><code>{(r.reasons || []).join("; ")}</code></div></>}
          </li>
        );
      })}</ul>
      <div className="row"><button disabled={busy || !list.length} onClick={all}>{t("brk.exec.all")}</button></div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
    </div>
  );
}

export function BreakIt() {
  const [text, setText] = useState(SAMPLE_ATTACK);
  const [v, setV] = useState(null);
  const [gen, setGen] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  const attack = () => run(async () => { const r = await api("/breakit/attack", { text }); setV(r); announce(r.blocked ? t("brk.blocked") : t("brk.got_through")); });
  const generate = () => run(async () => { setGen(await api("/breakit/generate", { n: 8 })); });
  const sb = gen?.scoreboard;
  return (
    <section aria-labelledby="brk-h" className="stack">
      <div>
        <h2 id="brk-h">{t("brk.title")}</h2>
        <p className="lead">{t("brk.lead")} <Mock /></p>
      </div>
      <div className="card">
        <label>{t("brk.text.label")}
          <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <div className="row">
          <button disabled={busy || !text.trim()} onClick={attack}>{t("brk.attack")}</button>
          <button className="ghost" disabled={busy} onClick={generate}>{t("brk.generate")}</button>
          {busy && <Loading>{t("brk.running")}</Loading>}
        </div>
        <ErrorBox error={err} onDismiss={() => setErr(null)} />
      </div>
      {v && <Verdict v={v} />}
      <ExecAttacks />
      {sb && (
        <div className="card" aria-live="polite">
          <div className="kpis">
            <div className="kpi"><div className="k">{t("brk.score")}</div><div className="v">{sb.blocked}/{sb.total}</div></div>
            <div className="kpi"><div className="k">{t("brk.saved")}</div><div className="v">{cny(sb.cny_saved, 2)}</div></div>
            <div className="kpi"><div className="k">{t("brk.lost")}</div><div className="v">{cny(sb.money_lost, 2)}</div></div>
          </div>
          <ul className="small">{gen.variants.map((r) => <li key={r.id}>#{r.id} {String(r.kind).replace(/_/g, " ")}: {r.blocked ? t("brk.blocked") : t("brk.got_through")} ({r.rules.join(", ") || "-"})</li>)}</ul>
        </div>
      )}
    </section>
  );
}
