"""Shared contract: observation records, HTTP with bounded retries, raw archiving, append-only writers.

Data contract (perp-dex-analysis #2):
date_utc,venue,metric,value,unit,period,source_uri,fetched_at_utc,coverage_status,schema_version
plus provenance extras: null_reason, instrument, market_id, raw_sha256, http_status, observed_kind.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from typing import Any, Callable, Optional

from . import SCHEMA_VERSION

CONTRACT_COLUMNS = [
    "date_utc", "venue", "metric", "value", "unit", "period", "source_uri",
    "fetched_at_utc", "coverage_status", "schema_version",
]
EXTRA_COLUMNS = ["null_reason", "instrument", "market_id", "raw_sha256", "http_status", "observed_kind"]
ALL_COLUMNS = CONTRACT_COLUMNS + EXTRA_COLUMNS

# coverage_status vocabulary. not_reported / fetch_failed / zero are deliberately distinct.
COVERAGE = {
    "observed",              # value present in venue/provider response
    "zero",                  # provider explicitly reported 0
    "zero_suspected_gap",    # provider reported 0 but a documented coverage change makes it unreliable
    "not_reported",          # source does not publish this metric (value null)
    "fetch_failed",          # request failed / non-JSON / malformed payload (value null)
    "not_implemented",       # a source may exist but v1 does not collect it (value null)
    "unit_unverified",       # value present but unit semantics not confirmed in public docs
}
PERIODS = {"point_in_time", "rolling_24h", "completed_utc_day"}
OBSERVED_KINDS = {"venue_api", "aggregator_api", "token_market_api", "derived", "annotation"}


@dataclass
class Observation:
    date_utc: str
    venue: str
    metric: str
    value: Optional[float]
    unit: str
    period: str
    source_uri: str
    fetched_at_utc: str
    coverage_status: str
    schema_version: str = SCHEMA_VERSION
    null_reason: Optional[str] = None
    instrument: Optional[str] = None
    market_id: Optional[str] = None
    raw_sha256: Optional[str] = None
    http_status: Optional[int] = None
    observed_kind: str = "venue_api"

    def validate(self) -> "Observation":
        if self.coverage_status not in COVERAGE:
            raise ValueError(f"bad coverage_status {self.coverage_status}")
        if self.period not in PERIODS:
            raise ValueError(f"bad period {self.period}")
        if self.observed_kind not in OBSERVED_KINDS:
            raise ValueError(f"bad observed_kind {self.observed_kind}")
        date.fromisoformat(self.date_utc)
        if not self.unit:
            raise ValueError("unit required")
        if self.value is None:
            if self.coverage_status in ("observed", "zero", "unit_unverified"):
                raise ValueError(f"{self.metric}: null value with status {self.coverage_status}")
            if not self.null_reason:
                raise ValueError(f"{self.metric}: null value requires null_reason")
        else:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(f"{self.metric}: numeric value required")
            if not math.isfinite(self.value):
                raise ValueError(f"{self.metric}: non-finite values are invalid")
            # Net protocol revenue can legitimately be negative, but stock,
            # volume, fees and OI measures cannot.
            if self.value < 0 and self.metric not in ("revenue_usd", "holders_revenue_usd"):
                raise ValueError(f"{self.metric}: negative value invalid")
            if self.coverage_status in ("not_reported", "fetch_failed", "not_implemented"):
                raise ValueError(f"{self.metric}: value present with null status")
            if self.value == 0 and self.coverage_status not in ("zero", "zero_suspected_gap"):
                raise ValueError(f"{self.metric}: literal 0 must be status zero")
            if self.value != 0 and self.coverage_status in ("zero", "zero_suspected_gap"):
                raise ValueError(f"{self.metric}: zero status with nonzero value")
        return self

    def key(self) -> tuple:
        return (self.date_utc, self.venue, self.metric, self.period, self.instrument or "", self.source_uri)

    def row(self) -> dict:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_float(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def obs_value(venue, metric, value, unit, period, src, fetched, date_utc, *, kind="venue_api",
              status=None, raw_sha=None, http_status=None, instrument=None, market_id=None,
              null_reason_if_missing="field absent from response") -> Observation:
    """Build an observation; automatically maps None -> not_reported and 0 -> zero."""
    if value is None:
        st, reason = (status if status in ("fetch_failed", "not_implemented") else "not_reported"), null_reason_if_missing
    elif value == 0:
        st, reason = (status if status == "zero_suspected_gap" else "zero"), None
    else:
        st, reason = (status if status == "unit_unverified" else "observed"), None
    return Observation(date_utc, venue, metric, value, unit, period, src, fetched, st,
                       null_reason=reason, instrument=instrument, market_id=market_id,
                       raw_sha256=raw_sha, http_status=http_status, observed_kind=kind).validate()


def null_obs(venue, metric, unit, period, src, fetched, date_utc, status, reason, *, kind="venue_api",
             http_status=None, raw_sha=None) -> Observation:
    return Observation(date_utc, venue, metric, None, unit, period, src, fetched, status,
                       null_reason=reason, http_status=http_status, raw_sha256=raw_sha,
                       observed_kind=kind).validate()


# ---------------------------------------------------------------- HTTP
@dataclass
class FetchResult:
    url: str
    status: Optional[int]
    body: Optional[bytes]
    error: Optional[str]
    attempts: int
    fetched_at: str
    sha256: Optional[str] = None

    def json(self) -> Any:
        if self.body is None:
            raise ValueError(self.error or "no body")
        return json.loads(self.body.decode("utf-8"))


Transport = Callable[[str, Optional[bytes], dict, float], tuple]  # -> (status, body bytes)


def urllib_transport(url, data, headers, timeout):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


RETRYABLE = {429, 500, 502, 503, 504}


def fetch(url, *, data: Optional[dict] = None, transport: Transport = urllib_transport,
          sleep: Callable[[float], None] = time.sleep, max_attempts: int = 3,
          base_backoff: float = 1.0, max_backoff: float = 8.0, timeout: float = 20.0,
          min_interval: float = 0.0, clock: Callable[[], datetime] = utc_now) -> FetchResult:
    """GET/POST with bounded retries and exponential backoff. Never raises on network errors."""
    body_bytes = json.dumps(data).encode() if data is not None else None
    headers = {"User-Agent": "perp-dex-analysis-collectors/1 (+github.com/Starrkiing/perp-dex-analysis)",
               "Accept": "application/json"}
    if body_bytes:
        headers["Content-Type"] = "application/json"
    last_status, last_err = None, None
    if min_interval:
        sleep(min_interval)
    for attempt in range(1, max_attempts + 1):
        fetched = iso(clock())
        try:
            status, body = transport(url, body_bytes, headers, timeout)
        except Exception as e:  # network error
            status, body, last_err = None, None, f"{type(e).__name__}: {e}"
        last_status = status
        if status is not None and 200 <= status < 300:
            return FetchResult(url, status, body, None, attempt, fetched, hashlib.sha256(body).hexdigest())
        if status is not None and status not in RETRYABLE:
            return FetchResult(url, status, None, f"HTTP {status}", attempt, fetched)
        if status is not None:
            last_err = f"HTTP {status}"
        if attempt < max_attempts:
            sleep(min(max_backoff, base_backoff * 2 ** (attempt - 1)))
    return FetchResult(url, last_status, None, last_err or "exhausted", max_attempts, iso(clock()))


def fetch_json(url, **kw):
    """Fetch + parse. Returns (FetchResult, parsed or None, error or None). Non-JSON => fetch_failed."""
    r = fetch(url, **kw)
    if r.body is None:
        return r, None, r.error
    try:
        return r, r.json(), None
    except (ValueError, UnicodeDecodeError) as e:
        return r, None, f"non-JSON response ({type(e).__name__})"


# ---------------------------------------------------------------- archive & writers
def archive_raw(r: FetchResult, raw_dir: str) -> Optional[str]:
    """Content-addressed immutable archive. Requests carry no credentials, so bodies hold no secrets."""
    if r.body is None or r.sha256 is None:
        return None
    os.makedirs(raw_dir, exist_ok=True)
    p = os.path.join(raw_dir, f"{r.sha256}.json")
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(r.body)
    idx = os.path.join(raw_dir, "index.jsonl")
    with open(idx, "a") as f:
        f.write(json.dumps({"sha256": r.sha256, "url": r.url, "http_status": r.status,
                            "fetched_at_utc": r.fetched_at, "attempts": r.attempts}) + "\n")
    return r.sha256


def exclude_incomplete_day(obs: list, now: datetime) -> list:
    today = now.astimezone(timezone.utc).date().isoformat()
    return [o for o in obs if not (o.period == "completed_utc_day" and o.date_utc >= today)]


def dedupe(obs: list) -> list:
    seen, out = set(), []
    for o in obs:
        k = o.key() + (o.fetched_at_utc,)
        if k in seen:
            continue
        seen.add(k)
        out.append(o)
    return out


def _existing_keys(jsonl_path):
    keys = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path) as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    keys.add(_hist_key(d))
    return keys


def _hist_key(d: dict):
    # Keep old observed *vintages* immutable, not the metric forever.
    # A provider revision or a later successful fetch after a null/failure
    # must append a new dated record. Re-fetches with unchanged values/status
    # do not add a duplicate. Analysts select latest fetched_at per metric/date.
    # Keep raw hash out of this key: source chart bodies can change while
    # the historic value for this specific date remains identical.
    base = (d["date_utc"], d["venue"], d["metric"], d.get("instrument") or "",
            d.get("market_id") or "", d["source_uri"])
    if d["period"] == "completed_utc_day":
        return ("H",) + base + (d.get("value"), d["coverage_status"], d.get("null_reason"))
    return ("S",) + base + (d["fetched_at_utc"],)


def append(obs: list, out_dir: str, stem: str = "observations") -> int:
    """Append-only: never rewrites existing lines; historic revisions become new vintages."""
    os.makedirs(out_dir, exist_ok=True)
    jp, cp = os.path.join(out_dir, f"{stem}.jsonl"), os.path.join(out_dir, f"{stem}.csv")
    keys = _existing_keys(jp)
    new = []
    for o in dedupe(obs):
        o.validate()
        d = o.row()
        k = _hist_key(d)
        if k in keys:
            continue
        keys.add(k)
        new.append(d)
    write_header = not os.path.exists(cp)
    with open(jp, "a") as jf, open(cp, "a", newline="") as cf:
        w = csv.DictWriter(cf, fieldnames=ALL_COLUMNS)
        if write_header:
            w.writeheader()
        for d in new:
            jf.write(json.dumps(d, sort_keys=True) + "\n")
            w.writerow({k: ("" if d[k] is None else d[k]) for k in ALL_COLUMNS})
    return len(new)
