"""CLI. Live fetching is MANUAL ONLY (`--live`); CI never runs it.

    python -m collectors.run --live --out data/observations
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta

from .common import (fetch_json, archive_raw, append, exclude_incomplete_day, null_obs, utc_now, iso)
from .venues import VENUES, SNAPSHOT_METRICS, UNITS, PERIOD, Ctx, MalformedPayload
from .history import LLAMA, SERIES, llama_url, parse_llama_series, not_reported_series
from .tokens import TOKENS, cg_url, parse_coingecko
from .annotations import turnover_indicator, incentive_annotations


def collect_venue(v, now: datetime, raw_dir, **fkw):
    date_utc = now.date().isoformat()
    if v.parser is None:
        r, payload, err = fetch_json(v.url, data=v.body, **fkw)
        reason = f"{v.blocked_reason}; this run: HTTP {r.status}, {err or 'parsed but no parser'}"
        return [null_obs(v.name, m, UNITS[m], PERIOD[m], v.url, r.fetched_at, date_utc, "fetch_failed", reason,
                         http_status=r.status) for m in SNAPSHOT_METRICS], {"venue": v.name, "url": v.url,
                                                                            "http_status": r.status, "error": reason}
    r, payload, err = fetch_json(v.url, data=v.body, **fkw)
    log = {"venue": v.name, "url": v.url, "http_status": r.status, "attempts": r.attempts, "error": err,
           "raw_sha256": r.sha256}
    if payload is None:
        return fail_all(v, r, date_utc, err), log
    sha = archive_raw(r, raw_dir) if raw_dir else r.sha256
    try:
        return v.parser(payload, Ctx(v.name, v.url, r.fetched_at, date_utc, sha, r.status)), log
    except (MalformedPayload, KeyError, TypeError, AttributeError) as e:
        log["error"] = f"malformed payload: {e}"
        return fail_all(v, r, date_utc, f"malformed payload: {e}"), log


def fail_all(v, r, date_utc, err):
    return [null_obs(v.name, m, UNITS[m], PERIOD[m], v.url, r.fetched_at, date_utc, "fetch_failed", str(err),
                     http_status=r.status) for m in SNAPSHOT_METRICS]


def collect_history(now, raw_dir, history_days=30, **fkw):
    obs, logs = [], []
    for venue, slug in LLAMA.items():
        for metric, (kind, dtype) in SERIES.items():
            url = llama_url(slug, kind, dtype)
            r, payload, err = fetch_json(url, min_interval=0.3, **fkw)
            logs.append({"venue": venue, "url": url, "http_status": r.status, "error": err})
            if payload is None:
                if r.status in (400, 404):
                    st, why = "not_reported", f"DefiLlama has no such series for this protocol ({err})"
                elif r.status == 402:
                    st, why = "not_reported", "DefiLlama now gates this endpoint behind a paid plan (HTTP 402); paid services not authorized"
                else:
                    st, why = "fetch_failed", f"DefiLlama: {err}"
                obs.append(not_reported_series(venue, metric, url, r.fetched_at, now.date().isoformat(), st, why, r.status))
                continue
            sha = archive_raw(r, raw_dir) if raw_dir else r.sha256
            try:
                obs += parse_llama_series(payload, venue, metric, url, r.fetched_at, now, sha, r.status)
            except ValueError as e:
                obs.append(not_reported_series(venue, metric, url, r.fetched_at, now.date().isoformat(),
                                               "fetch_failed", f"malformed payload: {e}", r.status))
    obs = exclude_incomplete_day(obs, now)
    if history_days:
        cutoff = (now.date() - timedelta(days=history_days)).isoformat()
        obs = [o for o in obs if o.period != "completed_utc_day" or o.date_utc >= cutoff or o.value is None]
    return obs, logs


def collect_tokens(now, raw_dir, **fkw):
    url = cg_url([c for c in TOKENS.values() if c])
    r, payload, err = fetch_json(url, **fkw)
    log = {"venue": "coingecko", "url": url, "http_status": r.status, "error": err}
    if payload is None:
        return [], log
    sha = archive_raw(r, raw_dir) if raw_dir else r.sha256
    return parse_coingecko(payload, url, r.fetched_at, now.date().isoformat(), sha, r.status), log


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="perform real network requests (manual smoke only)")
    ap.add_argument("--out", default="data/observations")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--history-days", type=int, default=30, help="completed UTC days to keep (0 = all)")
    a = ap.parse_args(argv)
    if not a.live:
        ap.error("refusing to run without --live (CI uses offline fixtures via pytest)")
    now = utc_now()
    raw = os.path.join(a.out, "raw")
    snap, logs = [], []
    for v in VENUES:
        o, l = collect_venue(v, now, raw)
        snap += o
        logs.append(l)
    tok, tl = collect_tokens(now, raw)
    logs.append(tl)
    hist, hl = ([], []) if a.no_history else collect_history(now, raw, a.history_days)
    logs += hl
    fetched = iso(now)
    allobs = snap + tok + hist + turnover_indicator(snap, fetched, now.date().isoformat()) + \
        incentive_annotations(fetched, now.date().isoformat())
    n = append(allobs, a.out)
    os.makedirs(os.path.join(a.out, "runs"), exist_ok=True)
    with open(os.path.join(a.out, "runs", f"smoke-{now.strftime('%Y%m%dT%H%M%SZ')}.json"), "w") as f:
        json.dump({"label": "MANUAL LIVE SMOKE FETCH", "started_at_utc": fetched, "appended_rows": n,
                   "requests": logs}, f, indent=1)
    print(f"appended {n} rows")


if __name__ == "__main__":
    main()
