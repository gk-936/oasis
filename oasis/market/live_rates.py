"""Live INR->CNY mid-market rate with a cache and the deterministic mock as the offline fallback.

Sources (keyless, free; see docs/live-rates.md):
  primary   Frankfurter (ECB euro foreign exchange reference rates). INR and CNY are both quoted against EUR, so the
            INR->CNY mid is the cross rate  CNY_per_EUR / INR_per_EUR.
  secondary fawazahmed0 currency-api via jsDelivr (direct inr->cny, CC0).
Past days use the provider's dated endpoint. Future (simulated) days hold the latest live rate flat: Oasis never
predicts exchange rates. Route spreads and fees are NOT live; they stay mock and are applied on top of the live mid.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..mock.rates import MockRates

TTL_SECONDS = 3600
RETRY_BACKOFF_SECONDS = 60          # after a total network failure, do not hammer the network on every mid() call
FRANKFURTER = "https://api.frankfurter.dev/v1/{when}?base=EUR&symbols=INR,CNY"
FAWAZ = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{when}/v1/currencies/inr.json"

SOURCE_LABELS = {
    "frankfurter": "ECB via Frankfurter",
    "fawazahmed0": "fawazahmed0 currency-api via jsDelivr",
    "MOCK": "MOCK",
}
FEES_NOTE = "MOCK (illustrative route spreads and fees applied on top of the mid-market rate)"

Transport = Callable[[str], str]


def urllib_transport(url: str, timeout: float = 5.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "oasis-hackathon/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https URLs above)
        return r.read().decode("utf-8")


@dataclass
class RateQuote:
    rate: float            # CNY per 1 INR, mid-market
    source: str            # "frankfurter" | "fawazahmed0" | "MOCK"
    fetched_at: str        # UTC ISO-8601, when we fetched it
    as_of: str             # provider's own date (ISO date); "" for MOCK
    stale: bool = False    # True when served from cache after a failed refresh

    def label(self) -> str:
        if self.source == "MOCK":
            return f"INR→CNY {self.rate:.4f} · MOCK (offline fallback, not a market rate)"
        t = self.fetched_at[11:16]
        flag = "STALE · " if self.stale else ""
        return (f"INR→CNY {self.rate:.4f} · {flag}live · {SOURCE_LABELS.get(self.source, self.source)} · "
                f"as of {self.as_of} · fetched {t} UTC")


def cross_rate(inr_per_eur: float, cny_per_eur: float) -> float:
    """CNY per INR from two EUR-based reference rates."""
    if inr_per_eur <= 0 or cny_per_eur <= 0:
        raise ValueError("non-positive reference rate")
    return cny_per_eur / inr_per_eur


def _parse_frankfurter(text: str) -> tuple[float, str]:
    d = json.loads(text)
    r = d["rates"]
    return cross_rate(float(r["INR"]), float(r["CNY"])), str(d["date"])


def _parse_fawaz(text: str) -> tuple[float, str]:
    d = json.loads(text)
    return float(d["inr"]["cny"]), str(d["date"])


_PROVIDERS = (("frankfurter", FRANKFURTER, _parse_frankfurter), ("fawazahmed0", FAWAZ, _parse_fawaz))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class LiveRates(MockRates):
    """Drop-in for MockRates (same mid()/route_rate() interface). Day 0 = today, negative = past, positive = held flat."""

    def __init__(self, seed: int = 7, cache_path: str | Path | None = None, transport: Transport | None = None,
                 ttl: float = TTL_SECONDS, clock: Callable[[], float] = time.time):
        super().__init__(seed)
        if cache_path is None:
            from .. import config
            cache_path = Path(config.DATA_DIR) / "rates_cache.json"
        self.cache_path = Path(cache_path)
        self.transport = transport or urllib_transport
        self.ttl = ttl
        self.clock = clock
        self._fail_until = 0.0
        self.last_quote: RateQuote | None = None
        self._cache = self._load()

    # --- cache -----------------------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            c = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(c, dict):
                c.setdefault("history", {})
                c.setdefault("latest", None)
                return c
        except (OSError, ValueError):
            pass
        return {"latest": None, "latest_ts": 0.0, "history": {}}

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, indent=1), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError:
            pass  # the cache is an optimisation; never fail a rate lookup because the disk is unwritable

    # --- network ---------------------------------------------------------------------------------
    def _fetch(self, when: str) -> RateQuote | None:
        """Try primary then secondary. `when` is 'latest' or an ISO date. None if both fail or are malformed."""
        for name, url, parse in _PROVIDERS:
            try:
                rate, as_of = parse(self.transport(url.format(when=when)))
                if not (0.01 < rate < 1.0):          # sanity: INR→CNY is ~0.07; reject garbage
                    raise ValueError(f"implausible rate {rate}")
                return RateQuote(round(rate, 6), name, _now_iso(), as_of)
            except Exception:  # network, HTTP, JSON, schema: all just mean "try the next source"
                continue
        return None

    # --- public API ------------------------------------------------------------------------------
    def latest(self) -> RateQuote:
        now = self.clock()
        c = self._cache
        try:
            cached = RateQuote(**c["latest"]) if c.get("latest") else None
        except TypeError:
            cached = None
        if cached and now - c.get("latest_ts", 0) < self.ttl:
            return cached
        if now >= self._fail_until:
            q = self._fetch("latest")
            if q:
                self._cache["latest"], self._cache["latest_ts"] = asdict(q), now
                self._save()
                return q
            self._fail_until = now + RETRY_BACKOFF_SECONDS
        if cached:
            cached.stale = True
            return cached
        return self._mock_quote(0)

    def quote(self, day: int = 0) -> RateQuote:
        """Provenance-carrying quote for a day offset."""
        if day >= 0:
            q = self.latest()                       # today and future days: latest rate, held flat (no prediction)
        else:
            today = datetime.fromtimestamp(self.clock(), timezone.utc).date()
            q = self._historical(today + timedelta(days=day), day)
        self.last_quote = q
        return q

    def _historical(self, d: date, day: int) -> RateQuote:
        key = d.isoformat()
        hit = self._cache["history"].get(key)
        if hit:
            return RateQuote(**hit)
        if self.clock() >= self._fail_until:
            q = self._fetch(key)
            if q:
                self._cache["history"][key] = asdict(q)
                self._save()
                return q
            self._fail_until = self.clock() + RETRY_BACKOFF_SECONDS
        # No history available: use the live rate if we have one (flat), else mock. Never invent a market rate.
        lq = self.latest()
        return lq if lq.source != "MOCK" else self._mock_quote(day)

    def _mock_quote(self, day: int) -> RateQuote:
        return RateQuote(MockRates.mid(self, day), "MOCK", _now_iso(), "", stale=False)

    def mid(self, day: int = 0) -> float:
        return self.quote(day).rate

    def provenance(self) -> dict:
        """For the API state field `rates`: what the UI badge shows."""
        q = self.last_quote or self.quote(0)
        return {**asdict(q), "mode": "mock" if q.source == "MOCK" else "live", "label": q.label(),
                "spreads_and_fees": FEES_NOTE}


def make_rates(seed: int = 7, mode: str | None = None, **kw) -> MockRates:
    """OASIS_RATES=live|mock (default mock, so tests, the benchmark and the scripted demo stay deterministic)."""
    mode = (mode or os.environ.get("OASIS_RATES", "mock")).strip().lower()
    return LiveRates(seed, **kw) if mode == "live" else MockRates(seed)


def provenance(rates: MockRates, day: int = 0) -> dict:
    """Provenance dict for any rates object (live or mock)."""
    if isinstance(rates, LiveRates):
        return rates.provenance()
    q = RateQuote(rates.mid(day), "MOCK", _now_iso(), "")
    return {**asdict(q), "mode": "mock", "label": q.label(), "spreads_and_fees": FEES_NOTE}
