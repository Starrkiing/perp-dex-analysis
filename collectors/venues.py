"""Per-venue snapshot collectors. Each parser is a pure function payload -> observations,
so offline fixture tests exercise exactly the code used live.

Every venue emits the same metric set; unsupported metrics are null with a reason (never 0).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .common import obs_value, null_obs, to_float

VOL, OI, OI_AVG, TVL, NMKT = ("perp_volume_24h_usd", "open_interest_usd", "open_interest_avg_usd",
                              "collateral_tvl_usd", "perp_market_count")
SNAPSHOT_METRICS = [VOL, OI, OI_AVG, TVL, NMKT]
UNITS = {VOL: "USD", OI: "USD", OI_AVG: "USD", TVL: "USD", NMKT: "count"}
PERIOD = {VOL: "rolling_24h", OI: "point_in_time", OI_AVG: "point_in_time", TVL: "point_in_time",
          NMKT: "point_in_time"}
OI_AVG_REASON = "no documented public historical OI endpoint used in v1; current OI is NOT substituted for average OI"


@dataclass
class Ctx:
    venue: str
    src: str
    fetched: str
    date_utc: str
    sha: Optional[str]
    status: Optional[int]


class MalformedPayload(ValueError):
    pass


def _emit(ctx: Ctx, values: dict, reasons: dict, status_override: dict | None = None):
    out = []
    status_override = status_override or {}
    for m in SNAPSHOT_METRICS:
        v = values.get(m)
        if v is None:
            reason = reasons.get(m) or (OI_AVG_REASON if m == OI_AVG else "not published by this endpoint")
            st = "not_implemented" if reason.startswith("not_implemented") else "not_reported"
            out.append(null_obs(ctx.venue, m, UNITS[m], PERIOD[m], ctx.src, ctx.fetched, ctx.date_utc,
                                st, reason, http_status=ctx.status, raw_sha=ctx.sha))
        else:
            out.append(obs_value(ctx.venue, m, v, UNITS[m], PERIOD[m], ctx.src, ctx.fetched, ctx.date_utc,
                                 status=status_override.get(m), raw_sha=ctx.sha, http_status=ctx.status))
    return out


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


# --------------------------------------------------------------------------- parsers
def parse_hyperliquid(p, ctx):
    if not (isinstance(p, list) and len(p) == 2 and "universe" in p[0]):
        raise MalformedPayload("expected [meta, assetCtxs]")
    uni, ctxs = p[0]["universe"], p[1]
    if len(uni) != len(ctxs):
        raise MalformedPayload("universe/assetCtxs length mismatch")
    vol, oi, n = [], [], 0
    for u, c in zip(uni, ctxs):
        if u.get("isDelisted"):
            continue
        n += 1
        vol.append(to_float(c.get("dayNtlVlm")))
        px, coins = to_float(c.get("markPx")), to_float(c.get("openInterest"))
        oi.append(px * coins if px is not None and coins is not None else None)
    return _emit(ctx, {VOL: _sum(vol), OI: _sum(oi), NMKT: n},
                 {TVL: "not_implemented: HLP vault/bridge TVL not in info.metaAndAssetCtxs; not collected in v1"})


def parse_extended(p, ctx):
    if not (isinstance(p, dict) and p.get("status") == "OK" and isinstance(p.get("data"), list)):
        raise MalformedPayload("expected {status: OK, data: [...]}")
    seen, vol, oi = set(), [], []
    for m in p["data"]:
        if m.get("type") != "PERPETUAL" or not m.get("active") or m.get("status") != "ACTIVE":
            continue
        if m["name"] in seen:
            continue
        seen.add(m["name"])
        s = m.get("marketStats") or {}
        vol.append(to_float(s.get("dailyVolume")))
        oi.append(to_float(s.get("openInterest")))
    return _emit(ctx, {VOL: _sum(vol), OI: _sum(oi), NMKT: len(seen)},
                 {TVL: "not_implemented: vault/collateral TVL not in /info/markets"})


def parse_lighter(p, ctx):
    if not (isinstance(p, dict) and isinstance(p.get("order_book_details"), list)):
        raise MalformedPayload("expected order_book_details list")
    seen, vol, oi = set(), [], []
    for m in p["order_book_details"]:  # spot books live in spot_order_book_details and are excluded
        if m.get("market_type") != "perp" or m.get("status") != "active":
            continue
        if m["market_id"] in seen:
            continue
        seen.add(m["market_id"])
        vol.append(to_float(m.get("daily_quote_token_volume")))
        oi.append(to_float(m.get("open_interest_usd")))
    return _emit(ctx, {VOL: _sum(vol), OI: _sum(oi), NMKT: len(seen)},
                 {TVL: "not_implemented: LLP/collateral TVL not in orderBookDetails"})


def parse_pacifica(p, ctx):
    if not (isinstance(p, dict) and p.get("success") and isinstance(p.get("data"), list)):
        raise MalformedPayload("expected {success, data}")
    seen, vol, oi = set(), [], []
    for m in p["data"]:
        if m["symbol"] in seen:
            continue
        seen.add(m["symbol"])
        vol.append(to_float(m.get("volume_24h")))
        mark, base = to_float(m.get("mark")), to_float(m.get("open_interest"))
        oi.append(mark * base if mark is not None and base is not None else None)
    # volume_24h / open_interest unit semantics are not stated in the public docs we reviewed:
    # OI treated as base units x mark; volume reported as-is and flagged unit_unverified.
    return _emit(ctx, {VOL: _sum(vol), OI: _sum(oi), NMKT: len(seen)},
                 {TVL: "not published by /info/prices"},
                 {VOL: "unit_unverified", OI: "unit_unverified"})


def parse_aster(p, ctx):
    if not isinstance(p, list):
        raise MalformedPayload("expected ticker list")
    seen, vol = set(), []
    for t in p:
        s = t.get("symbol", "")
        if s in seen or not s.endswith("USDT"):
            continue
        seen.add(s)
        vol.append(to_float(t.get("quoteVolume")))
    return _emit(ctx, {VOL: _sum(vol), NMKT: len(seen)},
                 {OI: "not_implemented: OI requires per-symbol /fapi/v1/openInterest calls (500+ requests); not run in v1",
                  TVL: "not published by ticker endpoint"},
                 {VOL: "unit_unverified"})  # quoteVolume is USDT-denominated, treated ~USD


def parse_gmx(p, ctx):
    if not (isinstance(p, dict) and isinstance(p.get("markets"), list)):
        raise MalformedPayload("expected markets list")
    seen, oi = set(), []
    for m in p["markets"]:
        if not m.get("isListed") or m["marketToken"] in seen:
            continue
        seen.add(m["marketToken"])
        lo, sh = to_float(m.get("openInterestLong")), to_float(m.get("openInterestShort"))
        oi.append((lo + sh) / 1e30 if lo is not None and sh is not None else None)  # GMX USD values use 30 decimals
    return _emit(ctx, {OI: _sum(oi), NMKT: len(seen)},
                 {VOL: "not published by /markets/info (Arbitrum only in v1)",
                  TVL: "not_implemented: GM pool TVL needs token pricing; not collected in v1"})


def parse_dydx(p, ctx):
    if not (isinstance(p, dict) and isinstance(p.get("markets"), dict)):
        raise MalformedPayload("expected markets dict")
    vol, oi, n = [], [], 0
    for tkr, m in p["markets"].items():
        if m.get("status") != "ACTIVE":
            continue
        n += 1
        vol.append(to_float(m.get("volume24H")))
        px, base = to_float(m.get("oraclePrice")), to_float(m.get("openInterest"))
        oi.append(px * base if px is not None and base is not None else None)
    return _emit(ctx, {VOL: _sum(vol), OI: _sum(oi), NMKT: n},
                 {TVL: "not published by /v4/perpetualMarkets"})


def parse_variational(p, ctx):
    if not (isinstance(p, dict) and "total_volume_24h" in p):
        raise MalformedPayload("expected stats object")
    return _emit(ctx, {VOL: to_float(p.get("total_volume_24h")), OI: to_float(p.get("open_interest")),
                       TVL: to_float(p.get("tvl")), NMKT: to_float(p.get("num_markets"))}, {})


def parse_grvt(p, ctx):
    if not (isinstance(p, dict) and isinstance(p.get("result"), list)):
        raise MalformedPayload("expected result list")
    n = len({i["instrument"] for i in p["result"] if i.get("kind") == "PERPETUAL"})
    r = "not_implemented: requires per-instrument /full/v1/ticker calls; not run in v1"
    return _emit(ctx, {NMKT: n}, {VOL: r, OI: r, TVL: "not published by all_instruments"})


@dataclass
class Venue:
    name: str
    url: str
    parser: Optional[Callable]
    body: Optional[dict] = None
    docs: str = ""
    blocked_reason: Optional[str] = None


VENUES = [
    Venue("hyperliquid", "https://api.hyperliquid.xyz/info", parse_hyperliquid, {"type": "metaAndAssetCtxs"},
          "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals"),
    Venue("extended", "https://api.starknet.extended.exchange/api/v1/info/markets", parse_extended, None,
          "http://api.docs.extended.exchange/"),
    Venue("lighter", "https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails", parse_lighter, None,
          "https://apidocs.lighter.xyz/"),
    Venue("pacifica", "https://api.pacifica.fi/api/v1/info/prices", parse_pacifica, None,
          "https://docs.pacifica.fi/api-documentation/api"),
    Venue("aster", "https://fapi.asterdex.com/fapi/v1/ticker/24hr", parse_aster, None,
          "https://github.com/asterdex/api-docs"),
    Venue("gmx", "https://arbitrum-api.gmxinfra.io/markets/info", parse_gmx, None,
          "https://docs.gmx.io/docs/api/rest-v2"),
    Venue("dydx", "https://indexer.dydx.trade/v4/perpetualMarkets", parse_dydx, None,
          "https://docs.dydx.xyz/indexer-client/http"),
    Venue("variational", "https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats",
          parse_variational, None, "https://docs.variational.io/"),
    Venue("grvt", "https://market-data.grvt.io/full/v1/all_instruments", parse_grvt, {"is_active": True},
          "https://api-docs.grvt.io/"),
    Venue("edgex", "https://pro.edgex.exchange/api/v1/public/meta/getMetaData", None, None,
          "https://edgex-1.gitbook.io/edgeX-documentation/api",
          blocked_reason="endpoint returned an HTML web-app page (HTTP 200, non-JSON) on 2026-11-01; documented public API host not confirmed"),
]
