# Extra corridors: regulation research and moving route prices from MOCK to real

Corridors: CNY→USD, INR→USD, EUR→USD, INR→EUR, CNY→EUR (next to INR→CNY). Data: `oasis/trust/rules/corridors.yaml`.
Research date: 2026-10-13. **Not legal advice.** Every row carries its source and status in the app (`/api/corridors/check`).

## What the research found

| Side | Finding | Status | Source |
|---|---|---|---|
| China (out) | USD 50,000 per person per calendar year for foreign exchange settlement and purchase, covers studying abroad | confirmed-primary | SAFE, "The SAFE Further Improves Administration of Foreign Exchange Settlement and Sale Business for Individuals" (safe.gov.cn/en/2009/1223/913.html, 2009) |
| China (out) | Splitting a large sum into small amounts to stay under the quota can be refused or examined by the bank | confirmed-primary (2009 page) | same page |
| China (out) | Above the quota, tuition is supported by an admission letter and fee statement or invoice | researched-secondary | Caixin Global 2017-01-03; tuition-payment guides. The SAFE page does not list the documents |
| India (out) | LRS USD 250,000 per financial year; TCS above INR 10 lakh (2% self-funded education, 0% specified loan, 20% other) | as in `inr_cny.yaml` | RBI Master Direction; Income-tax Act 2025 s.394 (secondary) |
| India (out) | Form A2, PAN and proof of purpose are expected; education purpose code S0305 | researched-secondary | razorpay, paasa, flywire. Sources conflict on some TCS details |
| Euro area (out) | Payments and capital movements to third countries are in principle free (Art. 63 TFEU); no general outbound cap modelled | researched-secondary | EUR-Lex Art. 63 TFEU; European Parliament fact sheet FTU 2.1.3 (read as search summaries) |
| Euro area (out) | Payer and payee data must accompany transfers (Reg. (EU) 2023/1113, applicable from 2024-12-30) | researched-secondary | EUR-Lex summary; EBA/GL/2024/11 |
| USD (in) | Incoming wires often cost the recipient about USD 0 to 25; intermediary banks may deduct charges | researched-secondary | Wise bank pages; mybanktracker.com |
| EUR (in) | Recipient-side charges | unconfirmed | none read |

Known gaps: the EUR-Lex pages and the Euro-area national rules were not read in full; the SAFE page is from 2009 and current
practice (the purpose declaration added in 2017) is not confirmed; no primary page was read for India Form A2 or the US wire
reporting rules (FinCEN's USD 3,000 recordkeeping figure was seen only in old news and is not used). Nothing here has been
confirmed by a bank or counsel.

## How to move a route price from MOCK to a real value

## How realistic the prices are now

No provider access was available, so prices were set from public fee ranges found on 2026-10-13. Each route type and override in
`corridors.yaml` carries `price_status`, `price_source` and `price_retrieved`, and the API and the UI show them.

| Route type | Numbers used | Status | Evidence |
|---|---|---|---|
| Typical bank SWIFT | fixed USD 45, 0.2% fee, 2.5% FX markup, 3 days, worst-case intermediary deduction USD 50 (expected half) | estimated | Corpay 2026 wire-fee guide (citing NerdWallet/Bankrate): USD 35-50 outgoing, 1-3% markup, USD 15-50 per intermediary; UK bank comparison 2-4%; ICBC London tariff 0.2% |
| Digital remitter, EUR→USD | EUR 1.54 + 0.47%, at mid-market | sourced | Wise's own fee statement (read through a search summary) |
| Digital remitter, INR→USD | 2.16% | sourced | Wise's public 'send money to USA' page, read 2026-10-13: INR 80,000 by bank transfer shows a cost of INR 1,726.53. One undated small-amount example; large payments are cheaper |
| Digital remitter, INR→EUR | 2.04% | sourced | same, 'send money to Germany' page: INR 1,632.11 on INR 80,000 |
| Digital remitter, China corridors | USD 1.7 + 0.65% | assumed | no China-specific figure found |
| Education specialist | 0.8% FX margin, no fixed fee | assumed | no published percentage found; Flywire fees depend on the institution |
| INR→CNY (original engine) | unchanged | mock | not recalibrated |

For scale, the World Bank's global average cost of sending USD 200 was 6.49% in March 2025; a large tuition payment costs a much
smaller share, which is why the percentages above are lower. Reliability and delivery days are assumptions, not measurements.
The ranking still orders routes by what to send, so an assumed price can influence it: the UI shows the status beside each route.

## How to move a route price to a real value

Replace the rows above as real quotes become available. To replace one:

1. **Pick a source for the route type.** Best to worst: the provider's own published fee table; a quote page for a specific
   corridor and amount; Wise's Comparisons API (price and speed estimates across providers; bank-transfer pay-in and pay-out
   only; access through Wise's affiliate program, so you need an account and terms apply).
2. **Take the mid-market rate for the same moment** (`/api/corridors/compare` returns `mid`, from live ECB rates with
   `OASIS_RATES=live`). Quotes must be taken at the same time as the mid, or the spread is wrong.
3. **Calibrate from one quote.** `corridors.core.implied_costs(send, mid, provider_received, fixed_fee_src)` returns the total
   cost and the variable cost (spread plus percentage fee) from what the provider says it delivers. Take two or three amounts
   to separate the fixed fee from the variable part.
4. **Write the numbers into `route_types`** (or a per-corridor override), then set `price_status: sourced`, and add
   `price_source` and `price_retrieved`. Keep the old mock numbers out of any README claim.
5. **Re-check on a schedule.** Provider prices change; a sourced price older than about 30 days should show as stale.
6. **Intermediary deductions** (`deduction_worst_usd`) cannot be read from a price page. Estimate them from real transfer
   receipts, and keep them labelled as an estimate.

Do not cite a number as real until its row says `sourced`, with the source and date. Oasis never predicts exchange rates.

## Live rates and the observed check

`OASIS_LLM=offline PYTHONPATH=. python -m eval.corridors_bench --live` fetches the free ECB reference rates (Frankfurter) and writes
`eval/reports/corridors_live.md` (the snapshot version is `corridors.md`). No model call is made. On 2026-10-13 the live
cross rates were within 0.5% of the rates shown on Wise's public pages (INR per USD +0.53%, INR per EUR +0.46%, EUR per USD +0.08%).
The two INR cost examples match the model by construction because the prices were set from them, so they are not an independent check.

## Confirmation checklist (what a bank or counsel still has to confirm)

| # | Item | Why it matters | Current status |
|---|---|---|---|
| 1 | Whether the USD 50,000 SAFE quota applies to a tuition payment sent from a CNY account, and which documents lift it | the CN-USD and CN-EUR corridors cap at the quota | applicability not established; documents secondary-sourced |
| 2 | India: Form A2, PAN and the education purpose code S0305 for a payment to a US or euro-area university | the bank's form | secondary only; sources conflict on some TCS details |
| 3 | India TCS: 2% on self-funded education above INR 10 lakh, 0% with a specified-institution loan, 20% otherwise | the tax shown in every INR plan | secondary-sourced, unconfirmed by the Income Tax Department |
| 4 | Euro area: purpose and document checks by the sending bank; Reg. (EU) 2023/1113 thresholds | the sending bank's questions | read through search summaries only |
| 5 | Incoming-wire fees at the receiving US bank, and whether intermediaries deduct charges | the worst-case deduction in every plan | public survey ranges, no bank tariff read |
| 6 | Provider quotes for CNY-USD, EUR-USD, CNY-EUR and the education-specialist route | route prices marked `assumed` or `estimated` | no quote obtained |

Stale-price rule: a `sourced` or `estimated` route price older than 30 days (by the simulated clock) is flagged `stale` in `/api/corridors/compare` and as a `price_stale` warning in a foreign-currency plan.

## Re-check of 2026-10-13 (primary pages reached)

| Finding | Source | Effect |
|---|---|---|
| China: overseas tuition may be bought outside the USD 50,000 quota; the individual chooses; outside it needs ID plus the admission notice | SAFE Tianjin bureau, "Individual foreign exchange (9)", safe.gov.cn/tianjin/2025/0714/2833.html (2025-07-14) | the CN-USD and CN-EUR corridors no longer treat the quota as a cap for tuition; other purposes still count against it |
| India: LRS USD 250,000 per financial year; studies abroad up to that without a fee estimate, more with the institution's estimate; Form A2 for every LRS purchase | RBI Master Direction, rbi.org.in `BS_ViewMasDirections.aspx?id=10192` (version of 6 Sep 2024) | Oasis keeps a hold at USD 250,000 even for education: a conservative policy stricter than RBI, labelled as such |
| India TCS on education: 2% per the Finance Act 2026 and the Budget 2026-27 summary, but the Income Tax Department's TCS rate page (uploaded 2026-04-30) still showed 5% | egazette.gov.in `WriteReadData/2026/271439.pdf` (PDF could not be fetched: certificate error) and incometaxindia.gov.in, both via search summaries | stays researched-secondary and flagged: primary sources disagree on what is current |
| Not reached | the PIB Budget page (HTTP 403), the RBI purpose-code PDF (no extractable text), Euro-area rules, a Chrome PQ-TLS test (no Caddy binary here) | unchanged |
