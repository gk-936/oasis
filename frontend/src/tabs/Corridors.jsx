import React, { useEffect, useState } from "react";
import { api, useGuard } from "../api.js";
import { t } from "../i18n/index.js";
import { ErrorBox, Loading, Mock, Pill } from "../ui.jsx";

/* More corridors beyond INR->CNY: compare routes on the amount the recipient must receive, and see the rules with their status. MOCK prices. */
const num = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export function Corridors({ initial, onReset }) {
  const [list, setList] = useState(null);
  const [cid, setCid] = useState(initial || "INR-USD");
  useEffect(() => { if (initial) { setCid(initial); setRes(null); setChk(null); } }, [initial]);
  const [required, setRequired] = useState(5000);
  const [res, setRes] = useState(null);
  const [chk, setChk] = useState(null);
  const { busy, err, setErr, run } = useGuard();
  useEffect(() => { api("/corridors").then((r) => { setList(r.corridors); }).catch(setErr); }, [setErr]);
  const c = list?.find((x) => x.id === cid);
  const dirty = !!(res || chk) || cid !== "INR-USD" || +required !== 5000;
  const clear = () => { setRes(null); setChk(null); setErr(null); setCid("INR-USD"); setRequired(5000); onReset?.(); };
  const go = () => run(async () => {
    const r = await api("/corridors/compare", { corridor: cid, required: +required });
    setRes(r);
    setChk(await api("/corridors/check", { corridor: cid, amount: r.options[0].send, purpose: "tuition" }));
  });
  if (!list) return <div className="card"><h3>{t("co.title")}</h3>{err ? <ErrorBox error={err} /> : <Loading />}</div>;
  return (
    <div className="card wide" data-testid="corridors">
      <div className="hd"><h3>{t("co.title")}</h3><Mock>{t("mock.sandbox")}</Mock></div>
      <p className="muted small">{t("co.intro")}</p>
      <div className="row">
        <label>{t("co.corridor")}<select value={cid} onChange={(e) => { setCid(e.target.value); setRes(null); setChk(null); }} data-testid="co-corridor">
          {list.map((x) => <option key={x.id} value={x.id}>{x.from} → {x.to}</option>)}</select></label>
        <label>{t("co.required", { cur: c?.to })}<input type="number" min={1} value={required} onChange={(e) => setRequired(e.target.value)} data-testid="co-required" /></label>
        <button disabled={busy || !(+required > 0)} onClick={go} style={{ alignSelf: "flex-end" }} data-testid="co-go">{t("co.compare")}</button>
        {dirty && <button type="button" className="ghost clear-x" onClick={clear} style={{ alignSelf: "flex-end" }} aria-label={t("co.clear")} title={t("co.clear")}>✕ <span>{t("co.clear")}</span></button>}
      </div>
      <ErrorBox error={err} onDismiss={() => setErr(null)} />
      {res && <>
        <div className="tbl"><table aria-label={t("co.title")}><thead><tr><th>{t("co.route")}</th><th className="r">{t("co.send", { cur: res.from })}</th><th className="r">{t("co.fee", { cur: res.from })}</th><th className="r">{t("co.worst", { cur: res.to })}</th><th className="r">{t("co.days")}</th></tr></thead>
          <tbody>{res.options.map((o) => (
            <tr key={o.route_id}><td>{o.route}{o.route_id === res.best && <> <Pill status="verified">{t("co.best")}</Pill></>}{o.typical_bank && <span className="muted"> {t("pass.typicalbank")}</span>} <span className="muted small" title={o.price_source}>· {t(`co.price.${o.price_status}`)}</span></td>
              <td className="r money">{num(o.send)}</td><td className="r money">{num(o.fee_src)}</td><td className="r money">{num(o.worst_received)}</td><td className="r num">{o.arrives_in_days}</td></tr>))}</tbody></table></div>
        <p className="muted small">{t("co.price.note")}</p>
        {res.saving_vs_bank && <p>{t("co.saving", { amount: num(res.saving_vs_bank.saved_src), cur: res.from, pct: res.saving_vs_bank.saved_pct })}</p>}
      </>}
      {chk && <>
        <h4>{t("co.rules")}</h4>
        {chk.findings.length === 0 ? <p className="muted">{t("co.rules.none")}</p> : (
          <ul className="feed">{chk.findings.map((f, i) => <li key={i}><Pill status={f.severity === "hold" ? "failed" : "pending"}>{f.severity}</Pill> {f.message} <span className="muted small">({f.status})</span></li>)}</ul>)}
        <p className="muted small">{t("co.disclaimer")}</p>
      </>}
    </div>
  );
}
