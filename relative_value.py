"""Point-in-time perp DEX relative activity analytics.

Inputs: Grok's archived daily USD-volume CSV and token-price CSV. No network
requests or fabricated data. Every output is derived from those two archives.

Do not equate transaction volume or open interest with net capital inflow.
A volume-share increase is an activity signal, not evidence of token value capture.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

WINDOWS = (14, 30, 60)


def read_daily(path: str | Path) -> pd.DataFrame:
    """Read a UTC date-indexed wide CSV, retaining missingness and rejecting invalids."""
    frame = pd.read_csv(path, index_col=0)
    try:
        dates = pd.to_datetime(frame.index, errors="raise", utc=True)
    except Exception as exc:
        raise ValueError(f"Invalid date index: {path}") from exc
    if dates.has_duplicates:
        raise ValueError(f"Duplicate UTC dates in {path}")
    if not dates.is_monotonic_increasing:
        raise ValueError(f"Dates out of order in {path}")
    if len(frame.columns) != len(set(frame.columns)):
        raise ValueError(f"Duplicate columns in {path}")
    frame.index = dates.normalize().tz_localize(None)
    if frame.index.has_duplicates:
        raise ValueError(f"Duplicate calendar days in {path}")
    frame = frame.apply(pd.to_numeric, errors="coerce").astype(float)
    frame = frame.replace([np.inf, -np.inf], np.nan)
    if (frame < 0).any().any():
        raise ValueError(f"Negative USD values in {path}")
    return frame.mask(frame <= 0)


def complete_days(frame: pd.DataFrame, *, as_of: str, include_asof: bool = False) -> pd.DataFrame:
    """Exclude the as-of day by default: today's exchange volume may be partial.

    Historical missing days remain missing; we NEVER forward-fill or interpolate.
    """
    cutoff = pd.Timestamp(as_of).normalize()
    return frame.loc[frame.index <= cutoff if include_asof else frame.index < cutoff].copy()


def log_changes(frame: pd.DataFrame) -> pd.DataFrame:
    """One-calendar-day log changes, only for adjacent positive observations."""
    daily = frame.asfreq("D")
    return np.log(daily).diff(1)


def rolling_pair_correlations(changes: pd.DataFrame, base: str, windows=WINDOWS) -> pd.DataFrame:
    """Pearson correlations of observed changes; each window needs all observations."""
    if base not in changes:
        raise ValueError(f"Missing benchmark: {base}")
    result = pd.DataFrame(index=changes.index)
    for column in changes.columns:
        if column == base:
            continue
        for w in windows:
            result[f"{column}__{base}__corr_{w}d"] = changes[column].rolling(w, min_periods=w).corr(changes[base])
    return result.replace([np.inf, -np.inf], np.nan)


def comparable_volume_share(volume: pd.DataFrame, venues: list[str], window: int = 30) -> pd.DataFrame:
    """Fixed-peer-panel trailing-volume share; invalidate days with any missing peer.

    Restricting to the same peers avoids false increases when another venue is
    missing. All 30 daily observations are required for every venue.
    """
    panel = volume[venues].asfreq("D")
    complete = panel.notna().all(axis=1)
    panel = panel.where(complete)
    trailing = panel.rolling(window, min_periods=window).sum()
    return trailing.div(trailing.sum(axis=1, min_count=len(venues)), axis=0)


def leave_one_out_activity_residual(volume: pd.DataFrame, venue: str, peers: list[str],
                                    training_days: int = 60) -> pd.DataFrame:
    """Point-in-time activity surprise vs all *other* exchanges.

    Regress dlog(venue volume) on dlog(sum of other venue volumes) with an
    intercept. Fit beta and alpha using the PRIOR 60 daily observations only;
    today's data never enters the fit. This is descriptive, not causal, and
    requires continuous positive daily observations for the entire fixed panel.
    """
    if venue not in peers or len(peers) < 3:
        raise ValueError("venue must belong to at least three fixed peers")
    fixed = volume[peers].asfreq("D")
    fixed = fixed.where(fixed.notna().all(axis=1))
    others = fixed[[p for p in peers if p != venue]].sum(axis=1, min_count=len(peers)-1)
    y = np.log(fixed[venue]).diff()
    x = np.log(others).diff()
    beta = y.rolling(training_days, min_periods=training_days).cov(x) / x.rolling(training_days, min_periods=training_days).var()
    alpha = y.rolling(training_days, min_periods=training_days).mean() - beta * x.rolling(training_days, min_periods=training_days).mean()
    beta = beta.shift(1)
    alpha = alpha.shift(1)
    residual = (y - alpha - beta * x).where(np.isfinite(beta) & np.isfinite(alpha))
    return pd.DataFrame({"venue_log_volume_change":y,
                         "peer_log_volume_change":x,
                         "prior_beta":beta,
                         "prior_alpha":alpha,
                         "activity_residual":residual,
                         "activity_residual_30d":residual.rolling(30, min_periods=30).sum()})


def run(volume_path: Path, prices_path: Path, out: Path, as_of: str,
        venues: list[str] | None = None) -> dict[str, Path]:
    vol = complete_days(read_daily(volume_path), as_of=as_of)
    px = complete_days(read_daily(prices_path), as_of=as_of)
    venues = venues or list(vol.columns)
    missing = sorted(set(venues) - set(vol.columns))
    if missing:
        raise ValueError(f"Unknown volume venues: {', '.join(missing)}")
    if len(venues) < 3:
        raise ValueError("At least three venues required")
    if "hyperliquid" not in venues:
        raise ValueError("Hyperliquid must be part of the comparison panel")
    if "BTC" not in px.columns:
        raise ValueError("BTC column required for token-price benchmark")
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    metrics = {
        "volume_log_change_correlations.csv": rolling_pair_correlations(log_changes(vol), "hyperliquid"),
        "price_log_return_correlations.csv": rolling_pair_correlations(log_changes(px), "BTC"),
    }
    share = comparable_volume_share(vol, venues)
    metrics["fixed_panel_volume_share_30d.csv"] = share
    metrics["fixed_panel_share_change_30d.csv"] = share.diff(30)
    for venue in venues:
        metrics[f"activity_residual_{venue}.csv"] = leave_one_out_activity_residual(vol, venue, venues)
    for name, df in metrics.items():
        path = out / name
        df.to_csv(path, float_format="%.10g")
        files[name] = path
    meta = out / "METHODS.txt"
    meta.write_text(
        f"as_of_utc={as_of}\n"
        "Volume includes only completed UTC days strictly before as_of.\n"
        "Prices also include only completed UTC days strictly before as_of.\n"
        f"fixed_panel={','.join(venues)}\n"
        "Sources=input archived CSVs, NOT live-verified during this run.\n"
        "Missing dates propagate as missing. No interpolation, no forward-fill.\n"
        "Correlations are contemporaneous and descriptive; no causality or forward-return inference.\n"
        "Activity residual is leave-one-out, past-60-observation linear fit requiring 60 daily samples.\n"
        "Residual momentum requires 30 additional consecutive observations.\n"
        "Missing market-wide OI history, token-holder revenue, token unlocks and fee incentives.\n"
        "Prelaunch XTEN FDV is illustrative; no XTEN spot return history exists here.\n",
        encoding="utf-8")
    files["METHODS.txt"] = meta
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", default="data/perp_volume_daily.csv")
    parser.add_argument("--prices", default="data/prices_daily.csv")
    parser.add_argument("--out", default="data/derived")
    parser.add_argument("--as-of", required=True, help="UTC as-of date YYYY-MM-DD")
    parser.add_argument("--venues", nargs="+", help="Fixed panel; default is all input exchanges")
    a = parser.parse_args()
    paths = run(Path(a.volume), Path(a.prices), Path(a.out), a.as_of, a.venues)
    print(f"Wrote {len(paths)} outputs under {a.out}")


if __name__ == "__main__":
    main()
