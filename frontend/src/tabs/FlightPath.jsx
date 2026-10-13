import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { t, useLang } from "../i18n/index.js";
import { cny, ErrorBox, inr, Mock, Skeleton } from "../ui.jsx";

const EVENTS = ["credit", "delay", "reject", "short_credit"];

function Bench({ b }) {
  if (b === null) return <p className="muted">{t("fp.bench.none")}</p>;
  const rows = [["fp.bench.short", (x) => `${Math.round(x.recipient_short_rate * 100)}%`], ["fp.bench.dup", (x) => x.duplicate_payments],
    ["fp.bench.flagged", (x) => x.preventable_issues_flagged], ["fp.bench.mae", (x) => x.recipient_amount_mae_cny]];
  return (
    <div className="card">
      <h3><Mock /> {t("fp.bench.title")}</h3>
      <div className="tbl"><table className="metrics"><thead><tr><th>{t("num.col.metric")}</th><th className="r">{t("fp.bench.baseline")}</th><th className="r full">{t("fp.bench.fp")}</th></tr></thead>
        <tbody>{rows.map(([l, f]) => <tr key={l}><td>{t(l)}</td><td className="r num">{f(b.baseline)}</td><td className="r num full">{f(b.flightpath)}</td></tr>)}</tbody></table></div>
      <p className="muted small">{b.label}. {t("fp.bench.caveat")}</p>
    </div>
  );
}

function Journey({ v, act }) {
  const j = v.journey;
  return (
    <div className="card">
      <h4>{j.id} · {j.route_id} · {j.stage}</h4>
      <p className="small">{t("fp.finding")}: {v.finding.detail}</p>
      <p className="small">{t("fp.advice")}: {v.advice.reason} {v.advice.resend_allowed ? t("fp.resend.yes") : t("fp.resend.no")}</p>
      <div className="seg" role="group" aria-label={t("fp.sim")}>
        {EVENTS.map((e) => <button key={e} type="button" onClick={() => act(`/flightpath/journeys/${j.id}/simulate`, { event: e })}>{t(`fp.ev.${e}`)}</button>)}
        {j.stage === "rejected" && <button type="button" onClick={() => act(`/flightpath/journeys/${j.id}/refund`, { confirmed: true })}>{t("fp.refund")}</button>}
      </div>
    </div>
  );
}

export function FlightPath() {
  useLang();
  const [req, setReq] = useState("1000");
  const [due, setDue] = useState("");
  const [opts, setOpts] = useState(null);
  const [bench, setBench] = useState(undefined);
  const [js, setJs] = useState({});
  const [err, setErr] = useState(null);
  const loadJ = useCallback(async () => {
    const { journeys } = await api("/flightpath/journeys");
    const out = {};
    for (const j of journeys) out[j.id] = await api(`/flightpath/journeys/${j.id}/advice`);
    setJs(out);
  }, []);
  useEffect(() => { api("/flightpath/benchmark").then(setBench).catch(setErr); loadJ().catch(setErr); }, [loadJ]);
  const dueN = due === "" ? null : +due;
  const compare = (e) => { e.preventDefault(); setErr(null); api("/flightpath/compare", { required_cny: +req, due_in_days: dueN }).then((r) => setOpts(r.options)).catch(setErr); };
  const put = (v) => setJs((s) => ({ ...s, [v.journey.id]: v }));
  const start = (o) => api("/flightpath/journeys", { route_id: o.route_id, required_cny: +req, send_inr: o.send_inr, due_in_days: dueN }).then(put).catch(setErr);
  const act = (path, body) => api(path, body).then(put).catch(setErr);
  const status = (o) => !o.on_time ? t("fp.late") : o.meets_target ? t("fp.ok") : t("fp.short");
  return (
    <section aria-labelledby="fp-h" className="stack">
      <div><h2 id="fp-h">{t("fp.title")}</h2><p className="lead"><Mock /> {t("fp.lead")}</p></div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      <form className="card" onSubmit={compare}>
        <label>{t("fp.required")} <input type="number" min="1" step="any" required value={req} onChange={(e) => setReq(e.target.value)} /></label>{" "}
        <label>{t("fp.due")} <input type="number" min="0" value={due} onChange={(e) => setDue(e.target.value)} /></label>{" "}
        <button type="submit">{t("fp.compare")}</button>
      </form>
      {opts && (
        <div className="tbl"><table className="metrics"><thead><tr><th>{t("fp.col.route")}</th><th className="r">{t("fp.col.send")}</th><th className="r">{t("fp.col.expected")}</th><th className="r">{t("fp.col.worst")}</th><th className="r">{t("fp.col.days")}</th><th>{t("fp.col.status")}</th><th /></tr></thead>
          <tbody>{opts.map((o) => <tr key={o.route_id}><td>{o.route}</td><td className="r num">{inr(o.send_inr)}</td><td className="r num">{cny(o.recipient_expected_cny, 2)}</td><td className="r num">{cny(o.recipient_worst_cny, 2)}</td><td className="r num">{o.arrives_in_days}</td><td>{status(o)}</td><td><button type="button" onClick={() => start(o)}>{t("fp.start")}</button></td></tr>)}</tbody></table></div>)}
      <div><h3>{t("fp.journeys")}</h3>
        {Object.keys(js).length === 0 ? <p className="muted">{t("fp.journeys.none")}</p> : Object.values(js).map((v) => <Journey key={v.journey.id} v={v} act={act} />)}</div>
      {bench === undefined ? <Skeleton rows={3} /> : <Bench b={bench} />}
    </section>
  );
}
