# collectors/: point-in-time public perp-DEX observations (v1)

Owner: Grok (engineering), per [perp-dex-analysis #2](https://github.com/Starrkiing/perp-dex-analysis/issues/2) and [ai-bridge #156](https://github.com/Starrkiing/ai-bridge/issues/156).
Scope: ingestion and provenance only. No modelling, no `research/`, `compute.py` or `relative_value.py` changes.

## Contract
Output files: `data/observations/observations.jsonl` and `observations.csv`. Both are append-only: existing lines are never rewritten, and completed UTC days are immutable once written.

Contract columns (exact order):
`date_utc,venue,metric,value,unit,period,source_uri,fetched_at_utc,coverage_status,schema_version`

Provenance extras: `null_reason,instrument,market_id,raw_sha256,http_status,observed_kind`.

- **period**: `point_in_time` (snapshot at `fetched_at_utc`), `rolling_24h` (venue's trailing 24h at fetch time, not a UTC day), `completed_utc_day` (closed UTC days only; the current, incomplete UTC day is always dropped).
- **coverage_status**: `observed`; `zero` (source explicitly reported 0); `zero_suspected_gap` (source reported 0 but a documented coverage break makes it unreliable); `not_reported` (source does not publish it); `fetch_failed` (HTTP error, non-JSON or malformed payload); `not_implemented` (a source probably exists but v1 does not collect it); `unit_unverified` (value present, units not confirmed in public docs). Every null carries a `null_reason`; nulls are never written as 0.
- **observed_kind**: `venue_api` (first-party), `aggregator_api` (DefiLlama JSON API), `token_market_api` (CoinGecko), `derived` (ratio of other rows), `annotation` (cited incentive program).
- **Raw responses**: content-addressed by sha256 in `data/observations/raw/<sha>.json`. The index (`raw/index.jsonl`: URL, status, attempts, time) is committed; the bodies (~4 MB per run) are kept locally and not committed in v1. Requests send no credentials, so bodies contain no secrets.
- **HTTP**: standard library only. Bounded retries (3 attempts), exponential backoff 1 s, 2 s (cap 8 s), only on 429/5xx/network errors; 4xx is not retried. DefiLlama calls are spaced 0.3 s apart.

## Run
```
python -m collectors.run --live --out data/observations   # MANUAL live smoke only
python -m pytest -q tests/collector_tests                   # offline; sockets are blocked
```
CI (`.github/workflows/collectors-tests.yml`) runs the offline tests and validates every committed row. It never touches the network.

## Per-venue coverage (live smoke 2026-11-01T21:11:46Z, run log `data/observations/runs/smoke-20261101T211146Z.json`)

| Venue | Endpoint (HTTP) | 24h vol | Current OI | Avg OI | TVL | Daily fees / revenue / holder rev (DefiLlama) | Token (CoinGecko) |
|---|---|---|---|---|---|---|---|
| Hyperliquid | info `metaAndAssetCtxs` (200) | observed | observed (coins x mark) | null | not_implemented | fees, revenue, holders: observed | HYPE observed |
| Extended | `api.starknet.extended.exchange/api/v1/info/markets` (200) | observed | observed (`openInterest` field; definition unverified) | null | not_implemented | fees observed through 2026-10-22; zero_suspected_gap from 2026-10-23; revenue/holders not_reported (HTTP 400) | none: no XTEN spot listing; premarket not treated as spot |
| Lighter | `orderBookDetails` (200) | observed (`daily_quote_token_volume`) | observed (`open_interest_usd`) | null | not_implemented | all three observed | LIT observed |
| Pacifica | `/info/prices` (200) | unit_unverified | unit_unverified (base x mark) | null | not_reported | fees, revenue observed; holders not_reported | none listed |
| Aster | `/fapi/v1/ticker/24hr` (200) | unit_unverified (USDT quoteVolume) | not_implemented (needs per-symbol calls) | null | not_reported | fees, holders observed; revenue not_reported | ASTER observed |
| GMX (Arbitrum) | `/markets/info` (200) | not_reported | observed (30-dec USD) | null | not_implemented | all three observed | GMX observed |
| dYdX | indexer `/v4/perpetualMarkets` (200) | observed | observed (base x oracle) | null | not_reported | all three observed | DYDX observed |
| Variational | `omni-client-api.../metadata/stats` (200) | observed | observed | null | observed | none (HTTP 400) | none listed |
| GRVT | `all_instruments` (200) | not_implemented | not_implemented | null | not_reported | fees/revenue not_reported; holders reported 0 for 5 days | none listed |
| edgeX | `pro.edgex.exchange/api/v1/public/meta/getMetaData`: HTTP 200 but an HTML web page | fetch_failed | fetch_failed | fetch_failed | fetch_failed | all three observed | EDGE observed |

Historical average OI is null for every venue: v1 uses no documented free historical OI endpoint, and current OI is never relabelled as an average.

DefiLlama `/summary/derivatives/*` (daily perp volume history) returned **HTTP 402 (paid)** for every venue, so v1 has no completed-day volume history. Paid services are not authorized.

Token unlock schedules: `not_implemented` (no free documented API found).

## Extended: Starknet vs Arc fee coverage (checked 2026-11-01)
- Extended moved settlement from Starknet to Circle's Arc on **2026-10-22 13:00 UTC** ([Extended docs](https://docs.extended.exchange/about-extended/migration-from-starknet-to-arc)).
- DefiLlama's Extended fee adapter reports `chains: ["Starknet"]`; its methodology sums Trade/Liquidation events on the Starknet trading contract, and it reports revenue as unreported (maker rebates are internal and can't be netted).
- Observed series: last nonzero day **2026-10-22 = $28,629** (a partial day; 2026-10-21 was $58,342). From 2026-10-23 onward it shows **0 every day**.
- Interpretation: post-migration fees are **not covered** (an Arc gap), not evidence of zero fees. Those rows are tagged `zero_suspected_gap`.
- The collector does not estimate Arc fees. Any XTEN fee multiple built on DefiLlama data after 2026-10-22 is invalid until an Arc-aware source exists.
- The first-party API host is still `api.starknet.extended.exchange` and returns live market stats after the migration.

## Reproducible Extended-vs-Hyperliquid date: 2026-10-21 (last full UTC day before the Arc cutover)
| venue | metric | value (USD) | source_uri | fetched_at_utc | raw_sha256 (prefix) |
|---|---|---|---|---|---|
| hyperliquid | fees_usd | 2,982,380 | https://api.llama.fi/summary/fees/hyperliquid?dataType=dailyFees | 2026-11-01T21:11:52Z | 32492878f2a1 |
| hyperliquid | revenue_usd | 2,251,711 | https://api.llama.fi/summary/fees/hyperliquid?dataType=dailyRevenue | 2026-11-01T21:11:53Z | 32a7529c9c83 |
| hyperliquid | holders_revenue_usd | 2,251,711 | https://api.llama.fi/summary/fees/hyperliquid?dataType=dailyHoldersRevenue | 2026-11-01T21:11:53Z | 20c3350e54a6 |
| extended | fees_usd | 58,342 | https://api.llama.fi/summary/fees/extended?dataType=dailyFees | 2026-11-01T21:11:54Z | dae477134865 |
| extended | revenue_usd | null (DefiLlama HTTP 400: not reported) | https://api.llama.fi/summary/fees/extended?dataType=dailyRevenue | 2026-11-01T21:11:54Z | - |

To reproduce: GET each URL, take the `totalDataChart` point with timestamp `1792540800` (2026-10-21T00:00Z), and compare against the committed row. Extended's 2026-10-21 fees are about 1.96% of Hyperliquid's. DefiLlama can revise past values, so the committed rows preserve what was observed at `fetched_at_utc`.

Snapshot on the same run (rolling 24h, not a UTC day): Hyperliquid volume $2.039B, OI $10.62B; Extended volume $175.2M, OI $186.7M. Extended's OI is the sum of the venue's `openInterest` field and is about twice DefiLlama's earlier ~$95M figure, so the field's definition (one side or both, units) needs confirming with Extended. That discrepancy is unresolved.

## Wash and incentive indicators
- `wash_risk_turnover_24h` = 24h volume / current OI. A review flag, not proof.
- Incentive annotations are limited to cited documents (currently: Extended points, per its migration doc). No annotation does **not** mean no incentives.
