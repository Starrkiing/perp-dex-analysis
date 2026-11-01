"""Token market data from CoinGecko's documented free /coins/markets endpoint (spot only).
No XTEN spot history is fabricated: if no CoinGecko listing exists, fields are null with a reason."""
from __future__ import annotations

from .common import obs_value, null_obs

TOKENS = {  # venue -> CoinGecko id (None = no listed token / not verified)
    "hyperliquid": "hyperliquid", "lighter": "lighter", "aster": "aster-2", "gmx": "gmx",
    "dydx": "dydx-chain", "edgex": "edgex", "extended": None, "pacifica": None, "grvt": None, "variational": None,
}
FIELDS = {"token_price_usd": ("current_price", "USD"), "token_circulating_supply": ("circulating_supply", "tokens"),
          "token_total_supply": ("total_supply", "tokens"), "token_fdv_usd": ("fully_diluted_valuation", "USD"),
          "token_market_cap_usd": ("market_cap", "USD")}
UNLOCK_REASON = "not_implemented: unlock schedules not available from a free documented API; not collected"


def cg_url(ids):
    return "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + ",".join(sorted(ids))


def parse_coingecko(payload, src, fetched, date_utc, sha=None, status=None):
    if not isinstance(payload, list):
        raise ValueError("expected list")
    by_id = {c.get("id"): c for c in payload}
    out = []
    for venue, cid in TOKENS.items():
        c = by_id.get(cid) if cid else None
        for metric, (field, unit) in FIELDS.items():
            if c is None:
                reason = ("no listed spot token verified for this venue (XTEN premarket not treated as spot)"
                          if cid is None else f"CoinGecko id {cid} missing from response")
                out.append(null_obs(venue, metric, unit, "point_in_time", src, fetched, date_utc,
                                    "not_reported", reason, kind="token_market_api", http_status=status, raw_sha=sha))
            else:
                o = obs_value(venue, metric, c.get(field), unit, "point_in_time", src, fetched, date_utc,
                              kind="token_market_api", raw_sha=sha, http_status=status)
                o.instrument = cid
                out.append(o)
        out.append(null_obs(venue, "token_unlocks_next_30d", "tokens", "point_in_time", src, fetched, date_utc,
                            "not_implemented", UNLOCK_REASON, kind="token_market_api"))
    return out
