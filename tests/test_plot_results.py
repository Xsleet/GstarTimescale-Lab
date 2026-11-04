from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from tools import plot_results as plot


class StandalonePlotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.results = self.root / "custom_results"
        self.results.mkdir()
        self.coefficients = {"CLOCK_A": 2e-17, "CLOCK_B": 3e-17, "Ensemble": 1e-17}
        start = datetime(2025, 12, 31, 23, 57)
        for name, coefficient in self.coefficients.items():
            rows = []
            for index in range(65):
                epoch = start + timedelta(seconds=15 * index)
                sod = epoch.hour * 3600 + epoch.minute * 60 + epoch.second
                prefix = f"{epoch.year} {epoch.month} {epoch.day} {sod}"
                phase = coefficient * (15 * index) ** 2
                suffix = f" 204 0 205 0 IEM {phase:.17e}" if name == "Ensemble" else f" {phase:.17e} 0 0 0 0"
                rows.append(prefix + suffix)
            filename = "IEM" if name == "Ensemble" else name
            (self.results / f"{filename}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.cfg = plot.dp.SchemaConfig(trend_state=2, num_harmonics=0, rate_hz=1 / 15, dev_mode="adev")

    def test_custom_clocks_dates_and_interval_without_demo_manifest(self):
        with patch.object(plot, "FIGURE_FORMATS", ("png",)):
            summary = plot.plot_results(self.results, self.root / "plot", ["CLOCK_A", "CLOCK_B"], 15)
        self.assertEqual(summary["phase_samples"], 65)
        self.assertEqual(summary["series"], ["CLOCK_A", "CLOCK_B", "Ensemble"])
        self.assertTrue(summary["first_epoch_gpst"].startswith("2025-12-31"))
        self.assertTrue(summary["last_epoch_gpst"].startswith("2026-01-01"))
        self.assertTrue((self.root / "plot/figures/adev.png").is_file())
        self.assertTrue((self.root / "plot/figures/phase.png").is_file())
        table = pd.read_csv(self.root / "plot/analysis/stability_summary.tsv", sep="\t")
        self.assertEqual(set(table.series), set(self.coefficients))
        for row in table.itertuples():
            expected = np.sqrt(2) * self.coefficients[row.series] * row.tau_s
            self.assertAlmostEqual(row.adev / expected, 1, places=12)
        phase = pd.read_csv(self.root / "plot/analysis/phase.csv")
        self.assertEqual(phase.elapsed_s.iloc[-1], 960)
        self.assertAlmostEqual(phase.Ensemble.iloc[-1] / (1e-17 * 960 ** 2), 1, places=12)

    def test_shifted_date_is_not_mistaken_for_aligned_seconds_of_day(self):
        path = self.results / "CLOCK_B.txt"
        path.write_text(path.read_text().replace("2025 12 31", "2025 12 30"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Epochs differ"):
            plot.load_results(self.results, ["CLOCK_A", "CLOCK_B"], self.cfg)

    def test_missing_epochs_or_wrong_interval_cannot_change_adev_silently(self):
        wrong = plot.dp.SchemaConfig(trend_state=2, rate_hz=1 / 30, dev_mode="adev")
        with self.assertRaisesRegex(ValueError, "interval"):
            plot.load_results(self.results, ["CLOCK_A", "CLOCK_B"], wrong)
        for path in self.results.glob("*.txt"):
            rows = path.read_text().splitlines()
            del rows[10]
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "gaps"):
            plot.load_results(self.results, ["CLOCK_A", "CLOCK_B"], self.cfg)


if __name__ == "__main__":
    unittest.main()
