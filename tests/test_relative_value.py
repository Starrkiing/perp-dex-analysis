import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from relative_value import (complete_days, comparable_volume_share,
                            leave_one_out_activity_residual, log_changes,
                            read_daily, rolling_pair_correlations, run)


class RelativeValueTest(unittest.TestCase):
    def setUp(self):
        self.idx = pd.date_range('2026-01-01', periods=125, freq='D')
        rng = np.random.default_rng(8)
        base = np.exp(rng.normal(0, .03, len(self.idx)).cumsum())
        self.vol = pd.DataFrame({
            'hyperliquid': base * 100_000_000,
            'extended': base * 1_000_000 * np.exp(rng.normal(0, .02, len(self.idx))),
            'lighter': base * 9_000_000 * np.exp(rng.normal(0, .02, len(self.idx)))}, index=self.idx)

    def test_missing_day_breaks_changes(self):
        frame = self.vol.drop(self.idx[35])
        changes = log_changes(frame)
        self.assertTrue(np.isnan(changes.loc[self.idx[35], 'extended']))
        self.assertTrue(np.isnan(changes.loc[self.idx[36], 'extended']))

    def test_invalid_volume_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'bad.csv'
            path.write_text(',x\n2026-01-01,-2\n')
            with self.assertRaisesRegex(ValueError, 'Negative'):
                read_daily(path)

    def test_share_constituent_gap_does_not_inflate_other_share(self):
        frame = self.vol.copy()
        frame.loc[self.idx[40], 'lighter'] = np.nan
        shares = comparable_volume_share(frame, list(frame), window=30)
        self.assertTrue(shares.loc[self.idx[40]:self.idx[69]].isna().all().all())
        self.assertAlmostEqual(shares.loc[self.idx[70]].sum(), 1., places=8)

    def test_residual_uses_only_past_and_requires_complete_window(self):
        venues = list(self.vol)
        a = leave_one_out_activity_residual(self.vol, 'extended', venues, 60)
        self.assertTrue(a['activity_residual'].iloc[:61].isna().all())
        self.assertTrue(a['activity_residual'].iloc[62:].notna().any())
        modified = self.vol.copy()
        modified.iloc[-1, modified.columns.get_loc('extended')] *= 10
        b = leave_one_out_activity_residual(modified, 'extended', venues, 60)
        self.assertAlmostEqual(a['prior_beta'].iloc[-1], b['prior_beta'].iloc[-1])
        self.assertNotAlmostEqual(a['activity_residual'].iloc[-1], b['activity_residual'].iloc[-1])

    def test_missing_window_not_silently_filled(self):
        frame = self.vol.copy()
        frame.loc[self.idx[60], 'hyperliquid'] = np.nan
        correlations = rolling_pair_correlations(log_changes(frame), 'hyperliquid', (14,))
        self.assertTrue(np.isnan(correlations.loc[self.idx[60], 'extended__hyperliquid__corr_14d']))
        self.assertTrue(np.isnan(correlations.loc[self.idx[74], 'extended__hyperliquid__corr_14d']))

    def test_partial_latest_volume_excluded(self):
        before = complete_days(self.vol, as_of='2026-05-05')
        self.assertEqual(before.index.max(), pd.Timestamp('2026-05-04'))

    def test_end_to_end_files_generated(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            vol = root/'v.csv'; prices=root/'p.csv'; out=root/'result'
            self.vol.to_csv(vol)
            pd.DataFrame({'BTC':self.vol.hyperliquid,'HYPE':self.vol.extended},index=self.idx).to_csv(prices)
            files = run(vol, prices, out, '2026-05-05')
            self.assertTrue((out/'METHODS.txt').exists())
            self.assertIn('fixed_panel_volume_share_30d.csv', files)
            self.assertEqual(len(files), 4+3+1)


if __name__ == '__main__':
    unittest.main()
