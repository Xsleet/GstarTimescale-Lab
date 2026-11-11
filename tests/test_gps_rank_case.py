"""Portable GPS fixture, gap statistics, and native output parsing checks."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import run_gps_rank_case as case


class InitializedGpsCaseTests(unittest.TestCase):
    def test_archived_reference(self):
        if not (case.CASE / 'manifest.json').is_file():
            self.skipTest('Optional public data verification: fetch the GPS release first')
        case.verify_reference()

    def test_gaps_do_not_create_differences(self):
        phase = np.arange(40, dtype=float) ** 3
        mask = np.ones(40, dtype=bool)
        mask[14:25] = False
        shifted = phase.copy()
        shifted[25:] += 1e9
        for metric in ("adev", "hdev", "ohdev"):
            original = case.deviation(phase, mask, metric, [30., 60.])
            changed = case.deviation(shifted, mask, metric, [30., 60.])
            for a, b in zip(original, changed):
                np.testing.assert_allclose(a["deviation"], b["deviation"], rtol=1e-12)
                self.assertEqual(a["difference_terms"], b["difference_terms"])
        self.assertEqual(case.deviation(phase, mask, "ohdev", [60.])[0]["difference_terms"], 17)

    def test_pool_single_terms_from_separate_segments(self):
        phase = np.array([0., 0., 0., 6., np.nan, 0., 0., 0., 12.])
        result = case.deviation(phase, np.isfinite(phase), "ohdev", [30.])[0]
        self.assertEqual(result["difference_terms"], 2)
        self.assertAlmostEqual(result["deviation"], np.sqrt((36 + 144) / (6 * 30**2 * 2)))

    def test_short_input_generation_and_pair_sign(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            data = Path(directory) / "data"
            metadata = case.load(case.EXAMPLE / 'case.json')
            case.dump(data / 'case.json', metadata)
            for name, value in case.load(case.EXAMPLE / 'config-recipes.json').items():
                case.write(data / 'config' / name, value)
            raw = np.arange(case.EPOCHS)[:, None] * 1e-13 + np.arange(31)[None, :] * 1e-4
            valid = np.ones(case.EPOCHS, dtype=bool)
            np.savez_compressed(data / 'data-placeholder.npz', phase=raw[:120])
            (data / 'data').mkdir()
            (data / 'data-placeholder.npz').rename(data / 'data/clocks.npz')
            with patch.object(case, 'CASE', data), patch.object(case, 'verify_assets'), patch.object(
                    case, 'clocks', return_value=(raw, valid, metadata['satellites'])):
                case.prepare(output, 120)
                with self.assertRaises(FileExistsError):
                    case.prepare(output, 120)
            self.assertEqual(len(list((output / "pfd").glob("*.txt"))), 465)
            self.assertEqual(len(list((output / "clk").glob("*.CLK"))), 1)
            lines = (output / "clk/BHU_2026153.CLK").read_text().splitlines()[6:]
            self.assertEqual(len(lines), 120 * 31)
            self.assertAlmostEqual(float(lines[0][39:59]), raw[0, 0], delta=1e-16)
            pairs = (output / "pfd/0101_0102_2026153.txt").read_text().splitlines()
            self.assertEqual(len(pairs), 240)
            forward, reverse = pairs[0].split(), pairs[1].split()
            self.assertEqual(forward[2:4], ["0101", "0102"])
            self.assertEqual(reverse[2:4], ["0102", "0101"])
            self.assertEqual(float(forward[-1]), -float(reverse[-1]))
            self.assertAlmostEqual(float(forward[-1]), raw[0, 0] - raw[0, 1], delta=1e-18)
            for method in case.METHODS + ("NONE",):
                cfg = (output / f"config/{method.lower()}/Timescale.cfg").read_text()
                self.assertIn("3600 [GPST]", cfg)
                self.assertTrue("Initialize relative clock phase = on" in cfg or
                                "SUMZERO initialize relative phase = on" in cfg)

    def test_native_reader_uses_final_iem_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "IEM.txt"
            path.write_text("2026 06 02 90.0 204 123.0 IEM 0.0002\n")
            np.testing.assert_array_equal(case.read_iem(path, 4), [0.0002])
            path.write_text("2026 06 02 120.0 204 123.0 IEM 0.0002\n")
            with self.assertRaises(ValueError):
                case.read_iem(path, 4)


if __name__ == "__main__":
    unittest.main()
