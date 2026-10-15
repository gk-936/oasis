import qrcode from "qrcode-generator";
/* Curated PDF reports for the Numbers page: only the latest results, with charts. Each builder returns the report body as an
   HTML string; api.js `downloadPdf` wraps it in the branded page. Every figure comes from the saved evaluation files served by
   /api/benchmark (eval/reports/*.json), and each report repeats the caveats that go with them. English only (the official language). */
export const qrSvg = (text) => { const q = qrcode(0, "M"); q.addData(text); q.make(); return q.createSvgTag({ cellSize: 3, margin: 1, scalable: true }); };
export const esc = (x) => String(x ?? "").replace(/[&<>]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[m]);
const n0 = (v) => Math.round(Number(v) || 0).toLocaleString("en-US");
const cny = (v) => `¥${n0(v)}`;
const pct = (v, d = 0) => `${(Number(v) * 100).toFixed(d)}%`;

export const kpis = (items) => `<div class="kpis">${items.map(([k, v, s]) => `<div class="kpi"><span>${esc(k)}</span><b>${esc(v)}</b>${s ? `<small>${esc(s)}</small>` : ""}</div>`).join("")}</div>`;
export const section = (title, body) => `<h3>${esc(title)}</h3>${body}`;
const caveats = (list) => section("Caveats", `<ul>${list.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`);
export const table = (head, rows, numCols = []) => `<table><thead><tr>${head.map((h, i) => `<th class="${numCols.includes(i) ? "r" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
  <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${numCols.includes(i) ? "r" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;

/** Horizontal bar chart. rows: [{label, values:[v, v2], text:[...]}]; series: [{name, color}]; max: axis maximum. */
function bars(rows, series, max, note) {
  const legend = series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : "";
  return `<div class="chart">${legend}${rows.map((r) => `<div class="brow"><div class="blabel">${esc(r.label)}</div><div class="bcol">${r.values.map((v, i) =>
    `<div class="btrack"><div class="bfill" style="width:${Math.max(0.8, (v / (max || 1)) * 100).toFixed(1)}%;background:${series[i].color}"></div><span class="bval">${esc(r.text[i])}</span></div>`).join("")}</div></div>`).join("")}${note ? `<p class="cnote">${esc(note)}</p>` : ""}</div>`;
}
const CYAN = "#0891b2", NAVY = "#0B0F1E", GREY = "#94a3b8", RED = "#e11d48", GREEN = "#059669";

export function planReport(b) {
  const L = b.planning?.live;
  if (!L) return null;
  const s = L.summary;
  const plans = s.scenarios_run;
  return [
    kpis([["Valid plans", pct(s.valid_plan_rate), `${plans} of ${plans} plans`], ["Deadlines met", `${s.deadlines_met}/${s.deadlines_total}`, "every payment on time"],
      ["Fees vs typical bank", `${s.fee_reduction_vs_bank_pct}% lower`, `${cny(s.fees_cny)} vs ${cny(s.bank_fees_cny)}`], ["Planner fallbacks", String(s.fallbacks), `${s.valid_without_fallback} of ${plans} valid without fallback`]]),
    section("Conversion fees across all plans", bars([{ label: "Typical bank route", values: [s.bank_fees_cny], text: [cny(s.bank_fees_cny)] }, { label: "Oasis plans", values: [s.fees_cny], text: [cny(s.fees_cny)] }],
      [{ name: "CNY", color: CYAN }, { name: "CNY", color: CYAN }].slice(0, 1), s.bank_fees_cny, "Total conversion fees summed over every plan in the run (lower is better).")),
    section("Plan outcomes", bars([{ label: "Valid without fallback", values: [s.valid_without_fallback], text: [`${s.valid_without_fallback} of ${plans}`] }, { label: "Fell back to the deterministic plan", values: [s.fallbacks], text: [String(s.fallbacks)] }],
      [{ name: "Plans", color: GREEN }], plans)),
    section("Deadlines", bars([{ label: "Deadlines met", values: [s.deadlines_met], text: [`${s.deadlines_met} of ${s.deadlines_total}`] }], [{ name: "Deadlines", color: GREEN }], s.deadlines_total)),
    section("Run details", table(["Measure", "Result"], [["Planner", L.planner], ["Model", L.model || "—"], ["Run date", L.date], ["Plans evaluated", `${plans} (8 scenarios × ${plans / 8} repeats)`],
      ["Mean proposals to first valid plan", `${s.mean_iterations_to_valid} (max ${s.max_iterations_to_valid})`], ["Tokens / model calls", `${n0(s.tokens)} / ${n0(s.model_calls)}`]])),
    caveats(["Eight hand-written scenarios, repeated. A pass shows the planner and the validator agree on these cases, not general optimality.",
      "The validator checks feasibility and the stated rules; it does not search for the globally cheapest plan. “Fees vs bank” compares with the typical bank route only.",
      "Corridor figures (SAFE quota, LRS, TCS) are researched, not officially confirmed. All money, rates and registries are simulated (MOCK).",
      "A live result is a small number of samples from one model, cached on disk. It is not a robustness claim."]),
  ].join("");
}

export function benchReport(b) {
  const B = b.benchmark;
  if (!B) return null;
  const f = B.summary.full, m = B.meta;
  const layers = [["baseline", "No protection (baseline)"], ["+verification", "+ payee verification"], ["+intents+policy", "+ signed intents and policy"], ["full", "Full Oasis"]];
  const cats = Object.entries(f.by_category).filter(([, v]) => v.blocked != null);
  const ok = Object.entries(f.by_category).filter(([, v]) => v.completed != null);
  const nice = (k) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  return [
    kpis([["Attacks blocked", pct(f.attack_block_rate), `${f.attacks} attack scenarios`], ["Money lost", cny(f.money_lost_cny), "across all attacks"], ["Legitimate payments completed", pct(f.legit_completion_rate), `${f.legit} scenarios · ${pct(f.false_block_rate)} falsely blocked`],
      ["Red-team attempts blocked", pct(f.redteam_block_rate), `${f.redteam_attacks} adversarial attempts`]]),
    section("Attack block rate by protection layer", bars(layers.map(([k, l]) => ({ label: l, values: [B.summary[k].attack_block_rate], text: [pct(B.summary[k].attack_block_rate)] })), [{ name: "Blocked", color: CYAN }], 1,
      "Each row adds one layer on the same 32 attacks, so the gain is attributable to that layer.")),
    section("Money lost by protection layer (CNY)", bars(layers.map(([k, l]) => ({ label: l, values: [B.summary[k].money_lost_cny], text: [cny(B.summary[k].money_lost_cny)] })), [{ name: "Lost", color: RED }], B.summary.baseline.money_lost_cny)),
    section("Full system: attacks blocked by category", bars(cats.map(([k, v]) => ({ label: `${nice(k)} (${v.blocked}/${v.n})`, values: [v.blocked / v.n], text: [pct(v.blocked / v.n)] })), [{ name: "Blocked", color: GREEN }], 1)),
    section("Full system: legitimate scenarios completed", table(["Scenario", "Completed", "Total"], ok.map(([k, v]) => [nice(k), String(v.completed), String(v.n)]), [1, 2])),
    section("Run details", table(["Measure", "Result"], [["Run", m.run_at], ["Engine", m.llm], ["Ruleset", m.ruleset], ["Scenarios", `${m.attacks} attacks · ${m.legit} legitimate · ${m.redteam} red-team`],
      ["Mean time to resolve a legitimate payment", `${f.mean_minutes_to_resolve_legit} min (simulated)`], ["Decoy (canary) detections", String(f.canary_detections)]])),
    caveats(["Scenarios are hand-written and the engine here is deterministic (offline), so this shows how the mechanism behaves, not accuracy against unseen real-world fraud.",
      "Money lost counts simulated yuan in a sandbox. No real settlement takes place and all identities and registries are MOCK."]),
  ].join("");
}

export function simReport(b) {
  const S = b.simulation;
  if (!Array.isArray(S) || !S.length) return null;
  const mx = Math.max(...S.map((p) => p.manual.fees_cny));
  const saved = S.reduce((a, p) => a + p.fees_saved_cny, 0), manual = S.reduce((a, p) => a + p.manual.fees_cny, 0), oasis = S.reduce((a, p) => a + p.oasis.fees_cny, 0);
  const late = S.reduce((a, p) => a + p.manual.late_payment_days - p.oasis.late_payment_days, 0);
  const stopped = S.reduce((a, p) => a + p.scams_stopped, 0);
  return [
    kpis([["Fees saved", cny(saved), `${pct(saved / manual)} lower across ${S.length} students`], ["Late-payment days avoided", String(late), "versus managing manually"], ["Scams stopped", String(stopped), "forged or changed payment details"], ["Fees with Oasis", cny(oasis), `vs ${cny(manual)} manually`]]),
    section("Fees per student: manual vs Oasis (CNY)", bars(S.map((p) => ({ label: `${p.persona} — ${p.note}`, values: [p.manual.fees_cny, p.oasis.fees_cny], text: [cny(p.manual.fees_cny), cny(p.oasis.fees_cny)] })),
      [{ name: "Managing manually (typical bank)", color: GREY }, { name: "With Oasis", color: CYAN }], mx)),
    section("Fees saved per student (CNY)", bars(S.map((p) => ({ label: p.persona, values: [p.fees_saved_cny], text: [cny(p.fees_saved_cny)] })), [{ name: "Saved", color: GREEN }], Math.max(...S.map((p) => p.fees_saved_cny)))),
    section("Student by student", table(["Student", "Situation", "Fees manual", "Fees Oasis", "Saved", "Late days manual → Oasis", "Scams stopped"],
      S.map((p) => [p.persona, p.note, cny(p.manual.fees_cny), cny(p.oasis.fees_cny), cny(p.fees_saved_cny), `${p.manual.late_payment_days} → ${p.oasis.late_payment_days}`, String(p.scams_stopped)]), [2, 3, 4, 5, 6])),
    caveats(["This is a model with stated assumptions (see eval/simulator.py), not a measurement of real students or real payment rails.",
      "Event scenarios (landlord change, forged invoice) run through the real Oasis pipeline; fee and timing figures use the simulator’s MOCK rates and routes.",
      "Five personas illustrate the mechanism. The totals are not a forecast of savings for any individual."]),
  ].join("");
}
