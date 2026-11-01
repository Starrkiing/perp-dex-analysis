"""Walk-forward perp DEX factor study (research-only, no live trades).

Uses archived completed-UTC-day venue volume and token close data. Forecasts
future TOKEN log returns in excess of BTC using a lagged venue-sector market
share change. Inputs are historic observations, never inferred cash flows.

Decision at end of UTC day t; simulated entry is following UTC daily close
(t+1), exit at close t+1+h. A model fit at t uses ONLY training examples
whose exit/label is known at least one complete day before t. Output is an
exploratory out-of-sample diagnostic, NOT a claim of trading alpha.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

from relative_value import read_daily, complete_days, comparable_volume_share

# Immutable prespecified token-to-venue mapping; absence is not filled.
DEFAULT_TOKEN_MAP = {
    "hyperliquid": "HYPE", "lighter": "LIT", "aster": "ASTER",
    "gmx": "GMX", "edgex": "EDGE", "dydx": "DYDX",
}
DEFAULT_HORIZON = 7
DEFAULT_SHARE_LOOKBACK = 14
DEFAULT_TRAIN_DAYS = 45


def make_excess_labels(prices: pd.DataFrame, token: str, horizon: int) -> pd.Series:
    """Forward excess log return; end-of-day t signal, (t+1)->(t+1+h) label."""
    if horizon < 1:
        raise ValueError("horizon must be positive")
    if token not in prices or "BTC" not in prices:
        raise ValueError(f"Missing price token/BTC: {token}")
    p = prices[[token, "BTC"]].asfreq("D")
    enter = p.shift(-1)
    exit_ = p.shift(-(horizon + 1))
    return (np.log(exit_[token] / enter[token])
            - np.log(exit_["BTC"] / enter["BTC"])).rename("future_btc_excess_log_return")


def fit_predict_prior(
    signal: pd.Series, label: pd.Series, decision_day: pd.Timestamp,
    horizon: int = DEFAULT_HORIZON, minimum: int = DEFAULT_TRAIN_DAYS,
    ridge: float = 1.0,
) -> dict | None:
    """Time-purged one-factor ridge fit using only fully resolved past outcomes."""
    if minimum < 10 or ridge < 0 or horizon < 1:
        raise ValueError("minimum >=10, ridge >=0, horizon >=1 required")
    t = pd.Timestamp(decision_day)
    value = signal.get(t, np.nan)
    if not np.isfinite(value):
        return None
    aligned = pd.concat([signal.rename("x"), label.rename("y")], axis=1).dropna()
    # Training sample j's exit is at j+h+1 and requires an additional
    # complete UTC day before decision t: j <= t-(h+2).
    train = aligned.loc[aligned.index <= t - pd.Timedelta(days=horizon+2)]
    if len(train) < minimum:
        return None
    x = train["x"].to_numpy(float)
    y = train["y"].to_numpy(float)
    mx, my = float(np.mean(x)), float(np.mean(y))
    sx = float(np.std(x))
    if sx < 1e-12:
        prediction = my
    else:
        z = (x-mx)/sx
        slope = float(np.dot(z, y-my)/(np.dot(z, z)+ridge))
        prediction = my+slope*((float(value)-mx)/sx)
    return {
        "prediction": float(prediction),
        "train_n": int(len(train)),
        "train_first_utc": train.index[0].date().isoformat(),
        "train_last_utc": train.index[-1].date().isoformat(),
        "benchmark_prediction": my,
    }


def validate(
    volume: pd.DataFrame,
    prices: pd.DataFrame,
    as_of: str,
    venues: list[str],
    token_map: dict[str, str] | None = None,
    horizon: int = DEFAULT_HORIZON,
    share_lookback: int = DEFAULT_SHARE_LOOKBACK,
    min_train: int = DEFAULT_TRAIN_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return prediction rows and conservative nonoverlapping-window summary.

    Historic data are filtered STRICTLY before as_of; output predictions for
    days with unresolved future outcomes have missing labels. Metrics include
    only decisions spaced >= horizon+1 UTC days apart; no p-value claims.
    """
    token_map = token_map or DEFAULT_TOKEN_MAP
    if horizon < 1 or share_lookback < 1 or min_train < 10:
        raise ValueError("invalid horizon/lookback/training length")
    if len(set(venues)) != len(venues) or len(venues) < 3:
        raise ValueError("At least 3 distinct fixed peer venues required")
    if "hyperliquid" not in venues:
        raise ValueError("hyperliquid required for comparison")
    if any(v not in volume for v in venues):
        raise ValueError("unknown volume venue")
    vol = complete_days(volume, as_of=as_of).asfreq("D")
    px = complete_days(prices, as_of=as_of).asfreq("D")
    share = comparable_volume_share(vol, venues, window=30)
    # 14-day percentage-point share changes are features only at t.
    feature = share.diff(share_lookback)
    # Guard against missing intermediate share day, preserved from fixed panel.
    result_rows, summary_rows = [], []
    for venue, token in token_map.items():
        if venue not in venues or token not in px or "BTC" not in px:
            continue
        labels = make_excess_labels(px, token, horizon)
        x = feature[venue].rename("share_change")
        rows = []
        for t in x.dropna().index:
            fit = fit_predict_prior(x, labels, t, horizon=horizon, minimum=min_train)
            if fit is None:
                continue
            observed = float(labels.get(t, np.nan))
            row = {
                "decision_utc":t.date().isoformat(),
                "entry_utc":(t+pd.Timedelta(days=1)).date().isoformat(),
                "exit_utc":(t+pd.Timedelta(days=horizon+1)).date().isoformat(),
                "venue":venue, "token":token,
                "lagged_share_change":float(x[t]),
                "observed_excess_log_return":observed,
                **fit
            }
            rows.append(row)
            result_rows.append(row)
        # Nonoverlapping sample, deterministic start from earliest labeled row.
        evaluated = []
        last = None
        for r in rows:
            if not np.isfinite(r["observed_excess_log_return"]):
                continue
            day = pd.Timestamp(r["decision_utc"])
            if last is None or (day-last).days > horizon:
                evaluated.append(r)
                last = day
        n = len(evaluated)
        if n:
            errors = np.array([r["prediction"]-r["observed_excess_log_return"] for r in evaluated])
            baseline = np.array([r["benchmark_prediction"]-r["observed_excess_log_return"] for r in evaluated])
            hit = np.mean([np.sign(r["prediction"]) == np.sign(r["observed_excess_log_return"]) for r in evaluated])
            mae = float(np.mean(abs(errors)))
            baseline_mae = float(np.mean(abs(baseline)))
        else:
            mae = baseline_mae = hit = float("nan")
        summary_rows.append({
            "venue":venue, "token":token, "horizon_days":horizon,
            "nonoverlap_evaluations":n,
            "mae_log_return":mae,
            "baseline_mae_log_return":baseline_mae,
            "direction_hit_rate":float(hit),
            "verdict":"NO_EDGE_ESTABLISHED",
            "reason":"exploratory sample; no prespecified statistical acceptance or execution-cost gate",
        })
    predictions = pd.DataFrame(result_rows)
    if not predictions.empty:
        predictions = predictions.sort_values(["venue", "decision_utc"])
    summary = pd.DataFrame(summary_rows)
    return predictions, summary


def run(
    volume_path: Path, prices_path: Path, out: Path, as_of: str,
    venues: list[str] | None = None,
    horizon: int = DEFAULT_HORIZON,
) -> tuple[Path, Path]:
    volume = read_daily(volume_path)
    prices = read_daily(prices_path)
    peers = venues or list(volume.columns)
    predictions, summary = validate(volume, prices, as_of, peers, horizon=horizon)
    out.mkdir(parents=True, exist_ok=True)
    pred_path = out / "forward_predictions.csv"
    summary_path = out / "forward_diagnostics.csv"
    predictions.to_csv(pred_path, index=False, float_format="%.10g", na_rep="")
    summary.to_csv(summary_path, index=False, float_format="%.10g", na_rep="")
    metadata = {
        "as_of_utc":as_of, "complete_days_before_as_of_only":True,
        "peers":peers, "horizon_days":horizon,
        "entry_convention":"next UTC daily close (t+1)",
        "exit_convention":"UTC daily close (t+1+h)",
        "training_embargo":"train j only if j+h+1 < decision t",
        "fixed_panel_share_window_days":30,
        "share_change_lookback_days":DEFAULT_SHARE_LOOKBACK,
        "min_fit_observations":DEFAULT_TRAIN_DAYS,
        "ridge_alpha":1.0,
        "null_policy":"Never fill missing data, prices, or fees.",
        "coverage":"archived vendor-reported data, not authenticated capital flows",
        "xten_price":"no XTEN spot history in archived prices",
        "classification":"RESEARCH_ONLY_NO_EDGE_ESTABLISHED",
    }
    (out/"forward_methodology.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    return pred_path, summary_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--volume", default="data/perp_volume_daily.csv")
    p.add_argument("--prices", default="data/prices_daily.csv")
    p.add_argument("--out", default="data/derived/forward")
    p.add_argument("--as-of", required=True, help="Cutoff UTC date, e.g. 2026-11-01")
    p.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    p.add_argument("--venues", nargs="+", help="Fixed peers, otherwise all available")
    a = p.parse_args()
    paths = run(Path(a.volume), Path(a.prices), Path(a.out), a.as_of, a.venues, a.horizon)
    print("Wrote:", *(str(x) for x in paths))


if __name__ == "__main__":
    main()
