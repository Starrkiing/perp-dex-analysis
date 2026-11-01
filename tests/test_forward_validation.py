import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

from research.forward_validation import (
    fit_predict_prior, make_excess_labels, validate, run,
)


class ForwardValidationTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(420)
        self.dates = pd.date_range("2026-01-01", periods=230, freq="D")
        common = np.exp(np.cumsum(rng.normal(0, .035, 230)))
        self.volume = pd.DataFrame({
            "hyperliquid":common * 100_000_000,
            "lighter":common * 40_000_000 * np.exp(np.cumsum(rng.normal(0, .007, 230))),
            "gmx":common * 10_000_000 * np.exp(np.cumsum(rng.normal(0, .011, 230))),
        }, index=self.dates)
        btc = 55_000 * np.exp(np.cumsum(rng.normal(0, .015, 230)))
        self.prices = pd.DataFrame({
            "BTC":btc,
            "HYPE":30*np.exp(np.cumsum(rng.normal(0,.025,230))),
            "LIT":1.1*np.exp(np.cumsum(rng.normal(0,.03,230))),
            "GMX":8*np.exp(np.cumsum(rng.normal(0,.017,230))),
        }, index=self.dates)

    def test_forward_returns_use_next_close_not_same_day(self):
        p = pd.DataFrame({"BTC":[100]*15, "HYPE":[1., 9., 2., 4.]+[4.]*11},
                         index=pd.date_range("2026-01-01",periods=15))
        label = make_excess_labels(p, "HYPE", 1)
        self.assertAlmostEqual(label.iloc[0], np.log(2/9))
        # price at t changes, not t+1, must not change decision-t outcome
        p.iloc[0, p.columns.get_loc("HYPE")] = 1_000
        self.assertAlmostEqual(make_excess_labels(p, "HYPE",1).iloc[0], np.log(2/9))

    def test_prior_train_excludes_unmatured_labels(self):
        signal = pd.Series(np.arange(110,dtype=float),index=self.dates[:110])
        y = pd.Series(np.arange(110,dtype=float),index=self.dates[:110])
        t = self.dates[100]
        fit = fit_predict_prior(signal,y,t,horizon=7,minimum=20)
        self.assertEqual(fit["train_last_utc"], self.dates[91].strftime("%Y-%m-%d"))
        altered = y.copy()
        altered.loc[y.index >= self.dates[92]] = 100_000
        fit2 = fit_predict_prior(signal,altered,t,horizon=7,minimum=20)
        self.assertEqual(fit["prediction"], fit2["prediction"])

    def test_changes_to_future_prices_do_not_change_past_forecast(self):
        before,_ = validate(self.volume,self.prices, "2026-08-18",
                            list(self.volume), horizon=7)
        self.assertFalse(before.empty)
        cutoff = "2026-06-15"
        original = before.loc[(before.token=="HYPE") & (before.decision_utc==cutoff)]
        self.assertFalse(original.empty)
        modified = self.prices.copy()
        modified.loc[modified.index > pd.Timestamp(cutoff), "HYPE"] *= 100
        after,_ = validate(self.volume,modified,"2026-08-18",
                           list(self.volume),horizon=7)
        updated = after.loc[(after.token=="HYPE") & (after.decision_utc==cutoff)]
        self.assertAlmostEqual(original.prediction.iloc[0],updated.prediction.iloc[0])

    def test_missing_venue_deletes_spurious_share_signals(self):
        volume = self.volume.copy()
        volume.loc[self.dates[140],"lighter"] = np.nan
        preds,_ = validate(volume,self.prices,"2026-08-18",list(volume),horizon=7)
        # 30d share rolling + 14d share shift => missing windows propagate
        span = preds.loc[(preds.venue=="hyperliquid") &
                         (preds.decision_utc>=self.dates[140].strftime("%Y-%m-%d")) &
                         (preds.decision_utc<=self.dates[183].strftime("%Y-%m-%d"))]
        self.assertTrue(span.empty)

    def test_output_reports_no_edge_and_known_label_cutoff(self):
        pred,summary = validate(self.volume,self.prices,"2026-08-18",
                                list(self.volume),horizon=7)
        self.assertTrue((summary.verdict == "NO_EDGE_ESTABLISHED").all())
        self.assertTrue((pred.train_n >= 45).all())
        # As-of day and beyond must never appear as decision dates
        self.assertTrue((pred.decision_utc < "2026-08-18").all())
        self.assertIn("nonoverlap_evaluations",summary.columns)
        self.assertTrue((summary.nonoverlap_evaluations > 0).all())

    def test_cli_smoke_local(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); v = root/"v.csv"; p = root/"p.csv"
            self.volume.to_csv(v); self.prices.to_csv(p)
            paths = run(v,p,root/"out","2026-08-18")
            self.assertTrue(all(f.exists() for f in paths))
            metadata = (root/"out"/"forward_methodology.json").read_text()
            self.assertIn("RESEARCH_ONLY_NO_EDGE_ESTABLISHED",metadata)


if __name__ == "__main__":
    unittest.main()
