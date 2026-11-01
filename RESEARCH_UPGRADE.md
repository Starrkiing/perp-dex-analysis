# GPT-6 independent methodology audit — November 1, 2026

## Upgrade status

**Grok's original source snapshot is retained unchanged.** New offline analytics are in `relative_value.py`. The existing `compute.py` and archived CSVs are not overwritten; `data/derived/` contains locally generated output.

## Material research gaps and fixes

| Issue | Why it matters | Fix / treatment |
|---|---|---|
| High raw volume correlation | Doesn't establish venue rotation, trader migration, token appreciation or organic activity | Fixed-panel market shares; leave-one-out market activity residuals |
| Only 14 correlation observations | Noisy; outliers dominate | Report 14, 30 and 60-day rolling **log-change** correlations |
| Changing venue coverage | Missing peers can create false gains in market share | Require every fixed peer's daily data before calculating 30-day panel shares |
| Missing dates or partial days | Forward-filling manufactures observations | Reindex to UTC calendar days; no interpolation/fill; exclude the as-of UTC day |
| 30-day volume versus point-in-time OI | Misaligned turnover denominator | Treat as descriptive; collect daily OI to compute aligned turnover |
| Fees versus retained revenue versus holder revenue | FDV / annualized fees is not a token-holder P/S ratio | Keep metrics separate and missing revenue genuinely missing |
| XTEN pre-TGE quote | $0.28 x 1B = **illustrative FDV**, not observed circulating spot market cap | Do not use XTEN spot return series until one exists |
| `compute.py` scrapes DeFiLlama HTML | Site structure may change; no stable API guarantees | Retain as historical work; API-first, schema-validated collectors are a remaining milestone |

## Run

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 relative_value.py --as-of 2026-11-01 --out data/derived
```

Inputs: `data/perp_volume_daily.csv` and `data/prices_daily.csv`. The analyzer is deterministic, never makes a live network request and writes the exact as-of date, fixed peer universe, and limitations to `data/derived/METHODS.txt`.

Outputs: `volume_log_change_correlations.csv`, `price_log_return_correlations.csv`, `fixed_panel_volume_share_30d.csv`, `fixed_panel_share_change_30d.csv`, and `activity_residual_<exchange>.csv` for each peer. Empty windows are deliberately missing, never invented.

### Interpretation

- Increasing **share of trading volume** is not equivalent to capital inflow or exchange revenue.
- A positive **activity residual** means the venue's daily log volume growth exceeded a linear estimate using only the previous 60 days of data from **other** exchanges. The beta and intercept are shifted by one day; no same-day lookahead in fitting.
- A **market share increase** on a fixed panel avoids false gains due to disappearing peers, but may reflect incentives, market making or wash trading.
- Correlations here are contemporaneous and descriptive. They are *not* a backtested trade signal.

## Gates before declaring a trading edge

1. **Provenance:** each raw snapshot needs UTC fetched-at time, source API or URL, exchange market definitions, revision handling, and failure metadata. Validate venue data against first-party APIs.
2. **Economics:** record daily average OI, TVL/collateral, paid fees, retained protocol revenue, **holder-accruing** revenue, incentives, unlocks and organic user retention. Align denominator windows.
3. **XTEN:** verify circulating spot supply and token-holder cash-flow rights; prelaunch perp valuation remains explicitly hypothetical.
4. **Out-of-sample:** test *lagged* share and residual growth against *forward* token excess returns with BTC/ETH and global-liquidity controls. Use walk-forward periods, execution costs, and multiple-testing correction.
5. **Evidence:** do not promote descriptive plots to an investable forecast without reproducible data and passing pre-registered gates. Until then: **NO EDGE ESTABLISHED**.

## References

- https://defillama.com/perps
- https://defillama.com/metrics — fee, protocol revenue and holder revenue definitions
- https://api-docs.defillama.com/ — derivatives historical endpoints are on an API plan; HTML scraping is not a documented free API.

## Fleet review request

At the exact PR HEAD: verify API provenance, sample alignment, residual no-lookahead, missing-data windows and CI results. Do not merge based on a correlation coefficient alone. The present upgrade provides clean historical research outputs; live connectors and a predictive engine are **not** claimed complete.
