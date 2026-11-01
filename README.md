# Perp DEX analysis: Extended (XTEN), Hyperliquid and peers

Compares on-chain perpetual exchanges on real economic activity (volume, open interest, fees, revenue) against token valuation, and tracks how their prices and volumes co-move. Purpose: find exchanges whose activity grows faster than their token's valuation, and separate organic activity from incentive or wash-driven volume.

Interactive Page: https://cursor.com/canvas/store-88589650-4feb-4356-9c8b-e0d3326570d0/fefdf8c6-289e-403b-bdcc-72cf9adfb6ff

Exchanges: Hyperliquid, Variational, Lighter, Aster, GMX, edgeX, Grvt, Pacifica, Extended, dYdX.

## Data sources (all pulled Nov 1, 2026, ~3:17-3:22 PM ET)
- DeFiLlama perps rankings (`defillama.com/perps`, page data): 30-day perp volume, open interest. The free `api.llama.fi/overview/derivatives` endpoint is now paywalled.
- DeFiLlama `api.llama.fi/overview/fees` (dailyFees and dailyRevenue): 30-day fees and revenue.
- DeFiLlama `defillama.com/protocol/perps/{slug}` page data: daily perp volume history.
- CoinGecko `/coins/markets`: token price, FDV, market cap. CoinGecko `/coins/{id}/market_chart?days=200&interval=daily`: daily prices.

## Files
- `data/valuation_snapshot_2026-11-01.csv`: per-exchange volume, OI, fees, revenue, token valuation and ratios (ratios rounded to 4 dp).
- `compute.py`: fetches price and volume history and computes the rolling correlations.
- `data/prices_daily.csv`: daily USD prices for BTC, HYPE, LIT, EDGE, DYDX, GMX, ASTER.
- `data/price_corr_14d.csv`: trailing 14-day correlation of daily returns, 8 pairs, May 3 - Nov 1, 2026.
- `data/perp_volume_daily.csv`: daily perp volume, 10 exchanges, full DeFiLlama history.
- `data/volume_change_corr_14d.csv`: trailing 14-day correlation of day-over-day volume % changes, Hyperliquid vs each peer, May 2 - Oct 31, 2026.

## Methods
- Annualized = 30-day value x 365/30.
- FDV / annualized revenue is a P/S-style multiple; FDV / annualized fees where revenue is unreported.
- Turnover = average daily volume (30d / 30) / current open interest.
- Share of Hyperliquid = exchange value / Hyperliquid value.
- Multi-product protocols use perp sub-protocols only: Lighter = Lighter Perps + Lighter Robinhood Perps; GMX = GMX EVM + GMX Solana; Hyperliquid = Hyperliquid Perps.
- Rolling correlation: Pearson correlation over a trailing 14-observation window of daily returns (prices) or daily % changes (volume). Days with missing data yield NaN for every window that covers them.

## Key findings: valuation
1. Extended's figures check out: $6.95B 30d volume = 3.12% of Hyperliquid's $222.6B; OI $94.9M = 1.27% of Hyperliquid's $7.45B.
2. Turnover is far higher at several venues than at Hyperliquid (1.0x): Pacifica 6.4x, edgeX 4.8x, GMX 3.5x, Lighter 3.3x, Variational 2.7x, Extended 2.4x. Consistent with active trading but also with incentive-driven or wash activity.
3. FDV / annualized revenue: HYPE ~104x, LIT ~51x, DYDX ~34x, EDGE ~18x, GMX 1.6x (flattered by GMX Solana revenue). Hyperliquid retains ~2.9 bps of volume as revenue vs ~0.7-0.8 bps at Lighter and edgeX.
4. XTEN at the illustrative $280M FDV is 0.0033x annualized volume and 24x annualized fees ($11.5M); Extended revenue is not reported, so no P/S.

## Key findings: correlation
1. HYPE/BTC sat at 0.73-0.82 through late October, then fell to -0.31 in the last three days; HYPE/LIT fell to -0.25. Likely a single HYPE-specific move in a 14-point window.
2. Other tokens are highly BTC-correlated now (EDGE 0.76, ASTER 0.75, LIT 0.67, GMX 0.67, DYDX 0.61), but DYDX and EDGE spent long stretches near or below zero earlier (DYDX -0.75 in July).
3. Volume changes at most venues track Hyperliquid closely (30-day mean: Lighter 0.91, edgeX 0.91, Aster 0.88, Pacifica 0.84, Variational 0.79, Extended 0.79): mostly market-wide volume.
4. Grvt decoupled: 0.6-0.9 until mid-September, then negative (30-day mean -0.26, low -0.62), consistent with venue-specific drivers such as incentive campaigns.

## Caveats
- XTEN is prelaunch. Its $0.28 price x 1B supply = $280M FDV is illustrative, not a market quote.
- Returns are daily, not hourly: CoinGecko's free tier gives hourly data only for the last 90 days and Binance klines were geo-blocked from the fetch machine. A 14-day daily window has only 14 observations and is noisy.
- DeFiLlama has no Hyperliquid volume for Aug 1, 2026, so all volume-correlation series have a 15-day gap (Aug 1-15).
- Reported volume is not normalized for incentives or wash trading. Variational and Grvt have no fee/revenue data; Aster and Extended report fees but not revenue; Variational, Grvt and Pacifica have no trading token.
- FDV includes locked supply (HYPE FDV is 4x market cap, LIT 3.9x, ASTER 3.1x).
- Snapshot data; values change daily.
