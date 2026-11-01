# Phase 2B: Forward-return research (GPT-6, independent of Grok ingestion)

This module is an **exploratory negative-control research harness**. It asks whether an exchange gaining 30-day **sector trading-volume share** relative to a fixed ten-venue panel precedes its token's price appreciation relative to BTC. It does **not** assume transaction turnover equals net cash invested, capital migration, profit, token-holder revenue, or token scarcity.

## Ownership / integration

- **Grok owns:** first-party public data collectors, historical OI, fees, retained vs holder revenue, token supply and unlocks, source provenance and collection CI. See project issue #2 and ai-bridge #156.
- **GPT-6 owns:** `research/` forward-return methodology, factor control and validation tests. This work reads existing archived CSVs only; it must not compete with Grok's collectors.
- No trades, backend deployment, refactoring original Grok `compute.py`, or capital-allocation recommendations.

## Reproducible offline run

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 -m research.forward_validation --as-of 2026-11-01 \
  --volume data/perp_volume_daily.csv \
  --prices data/prices_daily.csv \
  --out data/derived/forward
```

Creates `forward_predictions.csv`, `forward_diagnostics.csv`, and `forward_methodology.json`.

### Definitions / pre-data guardrails

1. Read only complete observed UTC days **strictly earlier** than the `--as-of` date. Missing records remain missing; zero in volume and prices is non-observation, never a free zero.
2. Define exchange feature on completed day **t**: `S_venue(t) - S_venue(t-14)`, where `S` is the venue's trailing 30-day volume divided by all fixed-panel venues' trailing 30-day volume. If any panel venue has a missing day, the 30-day panel observation is invalid rather than reweighted.
3. Define label from *hypothetical* next UTC close to later UTC close: `log(P_token(t+1+7)/P_token(t+1)) - log(P_BTC(t+1+7)/P_BTC(t+1))`. UTC closes are a **model convention**, not independently validated historical attainable executions.
4. For a prediction on decision day t, fit prior single-factor ridge regression on samples j ONLY if `j+h+1 < t`. This embargo avoids including future-known labels in the training fit. Expanding historical training, minimum 45 paired samples, ridge parameter 1; previous mean is the benchmark forecast.
5. Evaluation samples must have known full forward labels and be separated by **at least h+1 days** to reduce overlapping test windows. Evaluation counts and mean absolute error vs the same-history baseline are reported; no fabricated confidence level or p-value.
6. Never treat `HYPE/BTC` or other factor-adjusted correlation as evidence that XTEN has edge. XTEN has NO archived spot price history in the dataset. No XTEN predictor fit or extrapolation is authorized.
7. **NO EDGE ESTABLISHED** is always the research classification until a separate pre-registered prospective test defines effect size, data quality, economic edge, costs, multiple-testing controls and invalidation criteria before running.

### Methodology limitations (do not quietly suppress)

- Daily reporting and CoinGecko close snapshots may not correspond precisely to executable fixed UTC exchange prices. This is a *diagnostic*, not a tradable backtest.
- Forward token returns are residualized only against BTC in the present archive. No ETH, stablecoin liquidity, funding, leverage cycle, exchange token unlocks, or equity factors have yet been controlled.
- Daily volume and 30-day trailing shares may reflect incentives, wash trading, market-making or activity migrations unrelated to sustainable protocol revenue. No identity-level wash trade conclusion can follow from share alone.
- Future outcomes of cross-sectional venues share market shocks. Pooled inference would need clustered errors and multiple-test correction; do not infer significance from one venue or one 7-day window.
- The observation panel changes meaning if the set of venues changes; results are explicitly relative to the **fixed set** recorded in methodology.
- Complete historical OI, organic user retention, fee/revenue capture, buyback, unlock and circulating-supply data remain with Grok's engineering assignment. Actual XTEN spot post-TGE price/FDV would require verified separate feed.

### Next scientific test (not run)

Pre-register a lagged share/residual signal, matched counterfactual venues, cost/funding model, strict train/validation/test eras, falsification criterion and global liquidity controls. Reject or qualify any edge that disappears after factor adjustment or trading friction. Until then treat output as descriptive conditional relationships only.
