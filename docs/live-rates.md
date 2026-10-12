# Live exchange rates

Oasis can use a real INR to CNY mid-market rate instead of the simulated sine curve, plus real USD, EUR, GBP and AUD
crosses for the multi-currency wallet. It is **on in the Docker image** (`OASIS_RATES=live`) and **off by default
locally** (`OASIS_RATES=mock`) so tests, the benchmark and the judge scripts stay deterministic; the scripted demo always
uses the mock. The rate is fetched by the server, so a user's own network (for example a judge in mainland China) never
needs to reach the providers; only the host does, and if it cannot, the cached or MOCK fallback keeps everything working.
Code: `oasis/market/live_rates.py`; factory `make_rates()`.

## Sources

| Role | Source | Terms |
|---|---|---|
| Primary | **Frankfurter** (`api.frankfurter.dev/v1`), ECB euro foreign exchange reference rates | Free, no key. The API is open source (MIT). Underlying data are the ECB reference rates, published once per working day around 16:00 CET and free to reuse with source attribution. Reference rates are informational, not transactable. |
| Secondary | **fawazahmed0 currency-api** via jsDelivr CDN | Free, no key, no rate limit stated; repository licence is CC0 1.0 (public domain). Direct `inr -> cny` quote, daily snapshots. |

Checked but not used: open.er-api.com (ExchangeRate-API open endpoint) is free but requires visible attribution and
a link back, and is rate limited per IP; fine as a future third source.

ECB publishes INR and CNY, each against EUR (there is no direct ECB INR/CNY pair). The primary path requests
`base=EUR&symbols=INR,CNY,USD,GBP,AUD` and computes the cross rate itself: `CNY per INR = CNY_per_EUR / INR_per_EUR`.
From the same response it derives the wallet crosses as units per USD (`X_per_EUR / USD_per_EUR`, and EUR = `1 / USD_per_EUR`);
the secondary source does the same from its `inr` table (`inr->x / inr->usd`). Each cross is range-checked
(CNY 4 to 12, EUR 0.5 to 1.5, GBP 0.4 to 1.3, AUD 0.9 to 2.5 per USD); if any is missing or implausible, the crosses fall
back to the frozen ECB snapshot of 2026-10-09 in `oasis/mock/fx.py` while the live INR→CNY mid is kept. Checked live on
2026-10-12: both providers answered and agreed within about 0.1%.
The secondary source quotes INR/CNY directly. The two differ by a few basis points to ~0.5 percent
(ECB is a once-daily fixing; the other is an aggregated daily snapshot), which is far below the mock route spreads (0.4 to 3 percent).

## What is real and what is not

* Real: the mid-market INR to CNY rate (today and past days) and the USD, EUR, GBP and AUD wallet crosses.
* Mock, and labelled so: every route's rate spread, fixed and percentage fees, delivery days and reliability, and the
  wallet conversion spread and fee.
  They are applied on top of the live mid exactly as before.
* Not done, by design: **no rate prediction**. Day offsets in the future (the simulation clock runs ahead of real time)
  reuse the latest live rate held flat. Past offsets (`day_index < 0`, used by the 7-day rate-move trigger) call the
  provider's dated endpoint, so the trigger works on real history. ECB dates fall back to the previous working day;
  the quote's `as_of` shows the provider's actual date.

## Quote shape

`{rate, source, fetched_at, as_of, stale}`: `rate` is CNY per 1 INR; `source` is `frankfurter`, `fawazahmed0` or `MOCK`;
`fetched_at` is UTC ISO-8601; `as_of` is the provider's date; `stale` is true when served from cache after a failed refresh.

## Caching and fallback order

Cache file: `<DATA_DIR>/rates_cache.json` (default `data/rates_cache.json`). It holds the latest quote plus immutable
per-date history entries. TTL for the latest quote is 1 hour; history entries never expire.

1. Fresh cache (under 1 hour): use it, no network.
2. Fetch primary (Frankfurter), then secondary (jsDelivr). Short 5 s timeout; implausible or malformed data (not 0.01 to 1.0 CNY per INR,
   missing fields, bad JSON) counts as a failure.
3. Both fail: serve the last cached quote with `stale: true`. A failure backoff of 60 s stops every call retrying the network.
4. No cache at all: `MockRates` with `source: "MOCK"`. For a historical day with no data, the live rate is used flat if known, else MOCK. A made-up number is never labelled live.

## How the UI should label it

Show a badge next to every INR to CNY figure, from `state.rates.label`:

* Live: `INR→CNY 0.0692 · live · ECB via Frankfurter · as of 2026-10-09 · fetched 14:05 UTC`
* Stale: `INR→CNY 0.0692 · STALE · live · ECB via Frankfurter · as of 2026-10-09 · fetched 11:02 UTC` (warning colour)
* Mock: `INR→CNY 0.0700 · MOCK (offline fallback, not a market rate)` (neutral/grey)

Add a second line or tooltip from `state.rates.spreads_and_fees`: route spreads and fees are MOCK in every mode.
Attribution line for live mode: "Rates: ECB reference rates via Frankfurter. Informational mid-market rate, not a transactable quote."

Note: when `OASIS_RATES=live`, outputs are non-deterministic and the audit-chain head of the scripted demo will differ; keep the
demo and benchmark on `mock`.

## Wiring and the mock base

`World` builds its rates with `make_rates(seed, mode="mock" if deterministic else rates_mode)`, so `OASIS_RATES=live` affects only the API's student world; the scripted demo, scenario worlds, the red-team sandbox, the benchmark, the simulator and the tests are always mock. `GET /api/state` carries `rates` (the provenance dict above) and the UI shows it as a badge (green live, amber STALE, grey MOCK) with a footnote that route spreads and fees are mock. `get_rates` (planning tool) and the plan validator's `rate_basis` say "live" or "mock" accordingly.

The mock path is `MockRates.BASE * (1 + 0.012 sin((day + seed) / 6))` with `BASE = 0.0692`, the ECB-derived INR→CNY cross rate on 2026-10-09 (Frankfurter: CNY per EUR / INR per EUR). It was 0.0845 until 2026-10-10, which overstated the rate by about 22%. It is a frozen snapshot, not a live value.
