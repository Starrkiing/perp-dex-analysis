# Review request

Please review this analysis critically. Point out errors, weak assumptions, and what would make it decision-grade. Specific questions:

## Methodology
1. Is FDV / annualized 30-day revenue a sound P/S proxy for perp DEX tokens, or should we use market cap, holder-accruing revenue only (buybacks, staking), or a longer window?
2. Is average daily volume / current OI a reasonable turnover metric, or should OI be averaged over the same 30 days?
3. Is annualizing a single 30-day window (x 365/30) acceptable given volume seasonality?
4. Are 14-day windows of daily returns too noisy? What window or frequency (hourly, 30-day) would you recommend, and should we use log returns or rank correlation?
5. Is correlating day-over-day volume % changes the right way to test whether a venue's activity is organic vs market-driven? Would residuals after removing a market factor be better?

## Data quality
6. Are the sub-protocol groupings right (Lighter Perps + Robinhood Perps; GMX EVM + GMX Solana; Hyperliquid Perps only)?
7. How should the Aug 1 Hyperliquid volume gap be handled: forward-fill, drop the day, or interpolate?
8. Any known DeFiLlama reporting problems for these venues (double counting, off-chain reported volume, missing revenue for Extended and Aster)?

## Wash trading and incentives
9. Which signals beyond volume/OI turnover would you add: volume per active trader, fee per unit volume vs posted fee schedule, volume around points-program snapshots, self-trade detection on public order books?
10. Does Grvt's negative volume correlation to Hyperliquid since mid-September suggest incentive-driven volume, or is there another explanation?

## Valuation
11. Is the illustrative $280M XTEN FDV reasonable against peers at Extended's fee level (24x annualized fees)? What range would you consider?
12. How should token unlock schedules and FDV/market-cap gaps be reflected?

## What to add
13. Which metrics, exchanges, or charts are missing (e.g. TVL/deposits, unique traders, retention, revenue share to token holders, fee take rate trend)?
14. What would a simple screening model for "activity growing faster than valuation" look like with this data?
