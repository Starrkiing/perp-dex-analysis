"""Completed-UTC-day history from DefiLlama's documented JSON API (api.llama.fi), not HTML scraping.
Separates fees, retained protocol revenue and holder-accruing revenue. Current UTC day is excluded."""
from __future__ import annotations

from datetime import datetime, timezone

from .common import obs_value, null_obs

LLAMA = {  # venue -> DefiLlama slug
    "hyperliquid": "hyperliquid", "extended": "extended", "lighter": "lighter", "pacifica": "pacifica",
    "aster": "aster", "gmx": "gmx", "edgex": "edgex", "grvt": "grvt", "dydx": "dydx", "variational": "variational",
}
SERIES = {  # metric -> (endpoint kind, dataType)
    "perp_volume_usd": ("derivatives", None),
    "fees_usd": ("fees", "dailyFees"),
    "revenue_usd": ("fees", "dailyRevenue"),
    "holders_revenue_usd": ("fees", "dailyHoldersRevenue"),
}
# Documented coverage break: Extended settlement moved Starknet -> Arc on 2026-10-22 13:00 UTC
# (docs.extended.exchange/about-extended/migration-from-starknet-to-arc). DefiLlama's Extended fee adapter
# reads the Starknet trading contract only, so post-migration zeros are a coverage gap, not zero fees.
EXTENDED_ARC_CUTOVER = "2026-10-22"


def llama_url(slug, kind, dtype):
    base = f"https://api.llama.fi/summary/{kind}/{slug}"
    return base + (f"?dataType={dtype}" if dtype else "")


def parse_llama_series(payload, venue, metric, src, fetched, now: datetime, sha=None, status=None):
    today = now.astimezone(timezone.utc).date().isoformat()
    chart = payload.get("totalDataChart") if isinstance(payload, dict) else None
    if not isinstance(chart, list):
        raise ValueError("expected totalDataChart list")
    chains = payload.get("chains") or []
    out = []
    for pt in chart:
        if not (isinstance(pt, list) and len(pt) == 2):
            raise ValueError("malformed chart point")
        d = datetime.fromtimestamp(int(pt[0]), timezone.utc).date().isoformat()
        if d >= today:
            continue  # incomplete current UTC day excluded
        v = pt[1]
        gap = (venue == "extended" and metric in ("fees_usd", "revenue_usd", "holders_revenue_usd")
               and d >= EXTENDED_ARC_CUTOVER and chains == ["Starknet"])
        if gap and (v is None or v == 0):
            out.append(obs_value(venue, metric, 0 if v == 0 else None, "USD", "completed_utc_day", src, fetched, d,
                                 kind="aggregator_api", status="zero_suspected_gap" if v == 0 else None,
                                 raw_sha=sha, http_status=status,
                                 null_reason_if_missing="Starknet-only adapter after Arc migration"))
        else:
            out.append(obs_value(venue, metric, v, "USD", "completed_utc_day", src, fetched, d,
                                 kind="aggregator_api", raw_sha=sha, http_status=status))
    return out


def not_reported_series(venue, metric, src, fetched, date_utc, status, reason, http_status=None):
    return null_obs(venue, metric, "USD", "completed_utc_day", src, fetched, date_utc, status, reason,
                    kind="aggregator_api", http_status=http_status)
