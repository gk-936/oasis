import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { Signed } from "../common.jsx";
import { t, tl, tm, tp } from "../i18n/index.js";
import { announce, cny, money, Empty, ErrorBox, Hash, Loading, Mock, Pill, R, Skeleton } from "../ui.jsx";

/* Edit a copy of the loaded pack and verify it: any change must make the checks fail. The text is the server's own bytes,
   only re-indented (re-serialising through JS would turn 30000.0 into 30000 and break the signed canonical form). */
function prettyJson(raw) {
  let out = "", ind = 0, inStr = false, esc = false;
  const nl = () => "\n" + "  ".repeat(ind);
  for (const ch of raw) {
    if (inStr) { out += ch; if (esc) esc = false; else if (ch === "\\") esc = true; else if (ch === '"') inStr = false; continue; }
    if (ch === '"') { inStr = true; out += ch; }
    else if (ch === "{" || ch === "[") { ind++; out += ch + nl(); }
    else if (ch === "}" || ch === "]") { ind--; out += nl() + ch; }
    else if (ch === ",") out += ch + nl();
    else if (ch === ":") out += ": ";
    else out += ch;
  }
  return out.replace(/([{[])\s+([}\]])/g, "$1$2");
}

function TamperLab({ id }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    setRes(null); setErr(null);
    fetch(`/api/proof/${id}`).then((r) => r.text()).then((x) => { if (live) setText(prettyJson(x)); }).catch(() => {});
    return () => { live = false; };
  }, [id]);
  const go = async () => {
    setBusy(true); setErr(null);
    try { JSON.parse(text); setRes(await api("/proof/verify", text)); announce(t("tamper.announce")); }
    catch (e) { setErr(e instanceof SyntaxError ? new Error(t("err.badjson")) : e); setRes(null); }
    finally { setBusy(false); }
  };
  const fails = res ? Object.entries(res).filter(([k, v]) => k !== "pinned_fingerprint" && k !== "ok" && v === false).map(([k]) => k) : [];
  return (
    <details><summary>{t("tamper.summary")}</summary>
      <p className="muted small">{R("tamper.intro")}</p>
      <label>{t("tamper.label")}<textarea rows={10} value={text} spellCheck={false} onChange={(e) => setText(e.target.value)} /></label>
      <div className="row"><button className="ghost" disabled={busy || !text} onClick={go}>{t("tamper.verify")}</button>
        {res && (res.ok ? <Pill status="verified">{t("tamper.ok")}</Pill> : <Pill status="failed">{t("tamper.rejected", { fails: fails.join(", ") || t("tamper.notok") })}</Pill>)}</div>
      {err && <ErrorBox error={err} onDismiss={() => setErr(null)} />}
    </details>
  );
}

export function Proof({ s, selected }) {
  const [id, setId] = useState("");
  const [pack, setPack] = useState(null);
  const [check, setCheck] = useState(null);
  const [audit, setAudit] = useState(null);
  const [fp, setFp] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => { api("/trust/fingerprint").then(setFp).catch(() => {}); }, [s]);
  const load = useCallback(async (pid) => {
    setId(pid); setLoading(true); setErr(null);
    try { setPack(await api(`/proof/${pid}`)); setCheck(await api(`/proof/${pid}/verify`)); announce(t("proof.announce", { id: pid })); }
    catch (e) { setErr(e); setPack(null); setCheck(null); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { if (selected) load(selected); }, [selected, load]);
  const newest = s?.proofs?.[s.proofs.length - 1];
  useEffect(() => { if (!selected && newest) load(newest); }, [newest]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api("/audit/verify").then(setAudit).catch(() => {}); }, [s]);
  const checks = check ? Object.entries(check).filter(([k]) => k !== "pinned_fingerprint") : [];
  const failed = checks.filter(([, v]) => v === false).length;
  const passed = checks.filter(([, v]) => v === true).length;
  const proofs = s?.proofs || [];
  return (
    <section aria-labelledby="proof-h" className="stack">
      <div>
        <h2 id="proof-h">{t("proof.title")}</h2>
        <p className="lead">{t("proof.lead")}</p>
      </div>
      <div className="card">
        <div className="hd">
          <h3>{t("proof.anchors")}</h3>
        </div>
        {fp ? <p className="muted">{t("proof.fp")} <Hash value={fp.fingerprint} n={12} what={t("hash.fingerprint")} />{" "}
          {fp.demo_keys ? <Pill status="held">{t("proof.keys.demo")}</Pill> : fp.persistent ? <Pill status="paid">{t("proof.keys.persistent")}</Pill> : <Pill status="neutral">{t("proof.keys.memory")}</Pill>}{fp.demo_keys && ` ${t("proof.keys.public")}`}</p> : <Skeleton rows={1} />}
        {audit && <p className="muted">{t("proof.audit")} <Pill status={audit.ok ? "intact" : "broken"}>{audit.ok ? t("status.intact") : t("proof.audit.broken", { n: audit.first_broken })}</Pill> · {tp("proof.entries", audit.entries)} · {t("proof.head")} <Hash value={audit.head} n={12} what={t("hash.audit")} /></p>}
      </div>
      <div className="row" role="group" aria-label={t("proof.packs.aria")}>
        {proofs.map((p) => <button key={p} aria-pressed={p === id} className={p === id ? "" : "ghost"} onClick={() => load(p)}>{p}</button>)}
      </div>
      {!s && <Skeleton rows={2} />}
      {s && proofs.length === 0 && <Empty title={t("proof.empty.title")}>{t("proof.empty.text")}</Empty>}
      <ErrorBox error={err} onRetry={id ? () => load(id) : undefined} onDismiss={() => setErr(null)} />
      {loading && <Loading>{t("proof.loading")}</Loading>}
      {pack && !loading && (
        <div className={`card ${failed ? "tone-bad" : "tone-ok"}`}>
          <div className="hd"><h3>{t("proof.pack")} <code>{id}</code></h3>
            {check && (failed ? <Pill status="invalid">{tp("proof.failed", failed)}</Pill> : <Pill status="verified">{tp("proof.passed", passed)}</Pill>)}</div>
          <p>{R("proof.paid", { amount: money(pack.intent.amount, pack.intent.currency, 2), acct: pack.intent.account_ref, purpose: tl("purpose", pack.intent.purpose) })}{pack.intent.approvals.length ? "" : t("proof.auto")}</p>
          <Signed approvals={pack.intent.approvals} />
          <p>{t("proof.signatures", { list: Object.keys(pack.intent.signatures).join(" + ") })}</p>
          {pack.decision && <p>{R("proof.decision", { action: tl("action", pack.decision.action), rule: pack.decision.rule, tier: pack.decision.tier })}</p>}
          {pack.anchor && (/NOT FISCO/i.test(pack.anchor.network || "")
            ? <p>{t("proof.anchor")} <Hash value={pack.anchor.tx_hash} n={12} what={t("hash.anchor")} /> {t("proof.anchor.on")} <b>{pack.anchor.network}</b> <Mock>{t("mock.simchain")}</Mock></p>
            : <p>{t("proof.anchor.tx")} <Hash value={pack.anchor.tx_hash} n={12} what={t("hash.anchor")} />{t("proof.anchor.block")} <b>{pack.anchor.block_number}</b> {t("proof.anchor.on")} <b>{pack.anchor.network}</b> <Mock>{t("mock.localchain")}</Mock></p>)}
          {pack.costs?.route && <p>{R("proof.route", { route: tm(pack.costs.route), saved: cny(pack.costs.saved_cny, 2) })} <Mock /></p>}
          <h4>{t("proof.checks")}</h4>
          <div className="tbl"><table aria-label={t("proof.checks")}><tbody>{checks.map(([k, v]) => (
            <tr key={k}><td><code>{k}</code></td><td>{v === null ? <Pill status="neutral">{t("proof.notchecked")}</Pill> : v ? <Pill status="verified">{t("proof.pass")}</Pill> : <Pill status="failed">{t("proof.fail")}</Pill>}</td></tr>))}</tbody></table></div>
          <details><summary>{t("proof.howto")}</summary>
            <p className="muted">{R("proof.howto.text")}</p></details>
          <TamperLab id={id} />
        </div>
      )}
    </section>
  );
}
