"""Incentive annotations (only where documented by a cited source) and derived wash-risk indicators.
A turnover ratio is a risk indicator, not proof of wash trading."""
from __future__ import annotations

from .common import obs_value, null_obs

INCENTIVES = [  # (venue, label, source_uri). Only cited programs; absence here != no incentives.
    ("extended", "points program active (points carried over in Arc migration)",
     "https://docs.extended.exchange/about-extended/migration-from-starknet-to-arc"),
]


def turnover_indicator(snapshot_obs, fetched, date_utc):
    """volume_24h / open_interest per venue. High values flag elevated wash/incentive risk for review."""
    by = {}
    for o in snapshot_obs:
        if o.metric in ("perp_volume_24h_usd", "open_interest_usd"):
            by.setdefault(o.venue, {})[o.metric] = o
    out = []
    for venue, m in sorted(by.items()):
        v, oi = m.get("perp_volume_24h_usd"), m.get("open_interest_usd")
        src = "derived:perp_volume_24h_usd/open_interest_usd"
        if v is None or oi is None or v.value is None or not oi.value:
            out.append(null_obs(venue, "wash_risk_turnover_24h", "ratio", "rolling_24h", src, fetched, date_utc,
                                "not_reported", "volume or OI unavailable", kind="derived"))
        else:
            o = obs_value(venue, "wash_risk_turnover_24h", v.value / oi.value, "ratio", "rolling_24h", src,
                          fetched, date_utc, kind="derived",
                          status="unit_unverified" if "unit_unverified" in (v.coverage_status, oi.coverage_status) else None)
            out.append(o)
    return out


def incentive_annotations(fetched, date_utc):
    return [obs_value(v, "incentive_program_documented", 1, "flag", "point_in_time", src, fetched, date_utc,
                      kind="annotation", instrument=label) for v, label, src in INCENTIVES]
