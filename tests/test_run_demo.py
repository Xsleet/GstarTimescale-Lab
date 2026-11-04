"""Checks for demo inputs, shared epochs and the existing DataProcess ADEV pipeline."""
from contextlib import redirect_stderr
import csv
from datetime import date, timedelta
import hashlib
import importlib.util
import io
import itertools
import json
import math
import random
import re
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/run_demo.py"
SPEC = importlib.util.spec_from_file_location("run_demo", MODULE_PATH)
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)
TEST_DURATION = 3600


class RunDemoTests(unittest.TestCase):
    def create_products(self, root, architecture="centralized", clock_profile="csac-mro"):
        series = demo.prepare_case(root, architecture, duration_s=TEST_DURATION, clock_profile=clock_profile)
        directories = [root / f"results/nodes/node{node}" for node in range(4)] if architecture == "distributed_ci" else [root / "results"]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "IEM.txt").write_text("".join(
                f"2026 01 01 {i * 10} 204 99e-6 IEM {sum(series[sat][i] for sat in demo.SATELLITES) / 4:.17e}\n"
                for i in range(3, 360)))
            for index, satellite in enumerate(demo.SATELLITES, 1):
                (directory / f"SIM{index}.txt").write_text("".join(
                    f"2026 01 01 {i * 10} {series[satellite][i]:.17e} 0 0 99e-6 0\n"
                    for i in range(3, 360)))
        (root / "logs/console.log").write_text("[info] Finished\n")
        (root / "results/gstar.log").write_text("[info] Finished\n")
        return series, directories[0] / "IEM.txt"

    def test_deterministic_clocks_are_nonzero_and_finite(self):
        self.assertEqual(demo.DURATION, 10 * 86400)
        series = demo.clock_series(duration_s=TEST_DURATION)
        self.assertEqual(series, demo.clock_series(duration_s=TEST_DURATION))
        self.assertNotEqual(series, demo.clock_series(19, duration_s=TEST_DURATION))
        self.assertEqual(set(series), set(demo.SATELLITES))
        for values in series.values():
            self.assertEqual(len(values), 360)
            self.assertTrue(all(math.isfinite(v) and v != 0 for v in values))

    def test_days_require_a_finite_supported_sampling_duration(self):
        for days, seconds in ((150 / 86400, 150), (1 / 24, 3600),
                              (10, 864000), (365, 365 * 86400)):
            with self.subTest(days=days):
                self.assertEqual(demo.duration_from_days(days), seconds)
        for days in (float("nan"), float("inf"), float("-inf"), 0, -1,
                     140 / 86400, 151 / 86400, 86410 / 86400,
                     345610 / 86400, 365 + 10 / 86400):
            with self.subTest(days=days):
                with self.assertRaises(ValueError):
                    demo.duration_from_days(days)

    def test_heterogeneous_generation_matches_saved_filter_parameters(self):
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            demo.clock_series(seed=-3, duration_s=150, clock_profile="csac-mro")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            series = demo.prepare_case(root, "centralized", duration_s=TEST_DURATION, clock_profile="csac-mro")
            manifest = json.loads((root / "config/manifest.json").read_text())
            specs = manifest["clock_specs"]
            self.assertEqual([spec["clock_type"] for spec in specs], ["CSAC", "CSAC", "mRO", "mRO"])
            self.assertEqual(len({spec["seed"] for spec in specs}), 4)
            self.assertEqual(series, demo.clock_series(duration_s=TEST_DURATION, clock_profile="csac-mro"))
            self.assertNotEqual(series, demo.clock_series(seed=2027, duration_s=TEST_DURATION, clock_profile="csac-mro"))
            short = demo.clock_series(duration_s=150, clock_profile="csac-mro")
            session = (root / "config/session.obj").read_text()
            for spec in specs:
                prn = spec["session_prn"]
                self.assertEqual(series[prn][:15], short[prn])
                self.assertEqual(series[prn][0], spec["phase_offset_s"])
                self.assertEqual(len(series[prn]), 360)
                self.assertTrue(all(math.isfinite(value) for value in series[prn]))
                line = next(line for line in session.splitlines() if line.startswith(f" 000 {prn}"))
                phase_std = float(re.search(r"[{,]\s*Phase:\[[^,]+,([^\]]+)\]", line).group(1))
                frequency_std = float(re.search(r" Frequency:\[[^,]+,([^\]]+)\]", line).group(1))
                self.assertEqual(phase_std, spec["wfm_coefficient"])
                self.assertEqual(frequency_std, math.sqrt(6) * spec["rwfm_coefficient"])
                self.assertEqual(phase_std, spec["phase_process_std"])
                self.assertEqual(frequency_std, spec["frequency_process_std"])
            self.assertGreater(specs[0]["phase_process_std"], specs[2]["phase_process_std"])
            self.assertLess(specs[0]["frequency_process_std"], specs[2]["frequency_process_std"])
            definition = (root / "config/clock_profile.json").read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(definition).hexdigest(), manifest["clock_profile_sha256"])
            for path in (root / "pfd").glob("*.txt"):
                lines = path.read_text().splitlines()
                self.assertEqual(len(lines), 720)
                for index in (0, 100, 359):
                    first, second = (lines[2 * index + offset].split() for offset in (0, 1))
                    expected = series[first[2]][index] - series[first[3]][index]
                    self.assertAlmostEqual(float(first[4]), expected, places=18)
                    self.assertAlmostEqual(float(second[4]), -expected, places=18)

    def test_diffusion_transition_has_correct_joint_covariance(self):
        # Statistical check of the model, independent of the generator's factorization.
        # An endpoint-only integral fails both the variance and cross-covariance checks.
        import numpy as np
        rng = random.Random(347)
        dt, a, b = 10.0, 2.0, 0.7
        samples = np.array([demo.diffusion_step(0.0, 0.0, dt, a, b, rng) for _ in range(30000)])
        expected = np.array([[a*a*dt + b*b*dt**3/3, b*b*dt**2/2],
                             [b*b*dt**2/2, b*b*dt]])
        np.testing.assert_allclose(np.cov(samples, rowvar=False), expected, rtol=0.04, atol=0)
        self.assertTrue(np.all(np.abs(samples.mean(axis=0)) < 0.04 * np.sqrt(expected.diagonal())))

    def test_heterogeneous_report_preserves_types_and_rejects_profile_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_products(root, clock_profile="csac-mro")
            self.assertEqual(demo.main(["--report-only", "--output", str(root)]), 0)
            summary = json.loads((root / "summary.json").read_text())
            self.assertEqual(summary["clock_profile"], "csac-mro")
            self.assertEqual(set(summary["adev"]["curve_labels"]), {
                "SIM1 (CSAC) - origin", "SIM2 (CSAC) - origin",
                "SIM3 (mRO) - origin", "SIM4 (mRO) - origin", "Ensemble - estimate"})
            page = (root / "report.html").read_text(encoding="utf-8")
            self.assertIn("2 CSAC + 2 mRO", page)
            self.assertIn("config/clock_profile.json", page)
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            with redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit) as stopped:
                demo.main(["--report-only", "--clock-profile", "basic", "--output", str(root)])
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("invalid choice", errors.getvalue())
            self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()})

    def test_phase_display_preserves_endpoints_and_isolated_extrema(self):
        values = [0.01 * math.sin(index / 13) for index in range(10000)]
        spikes = {1234: 6.0, 5678: -7.0, 9998: 8.0}
        for index, value in spikes.items():
            values[index] = value
        selected = demo.phase_display_indices(values)
        self.assertLessEqual(len(selected), 2000)
        self.assertEqual(selected, sorted(set(selected)))
        self.assertEqual((selected[0], selected[-1]), (0, len(values) - 1))
        self.assertTrue(set(spikes).issubset(selected))
        self.assertEqual(demo.phase_display_indices(values[:100]), list(range(100)))

    def test_inputs_have_reader_columns_and_bidirectional_pairs(self):
        with tempfile.TemporaryDirectory(prefix="gstar demo ") as directory:
            root = Path(directory)
            series = demo.prepare_case(root, "centralized", duration_s=TEST_DURATION)
            records = (root / "clk/SIM0MGNFIN_20260010000_01D_10S_CLK.CLK").read_text().splitlines()
            records = [line for line in records if line.startswith("AS ")]
            self.assertEqual(len(records), 360 * 4)
            self.assertEqual(records[0][3:7].strip(), "101")
            self.assertAlmostEqual(float(records[0][40:60]), series["0101"][0], places=16)
            files = sorted((root / "pfd").glob("*.txt"))
            self.assertEqual(len(files), 6)
            for path in files:
                lines = path.read_text().splitlines()
                self.assertEqual(len(lines), 720)
                for row in range(0, len(lines), 2):
                    first, second = lines[row].split(), lines[row + 1].split()
                    self.assertEqual(first[:2], second[:2])
                    self.assertEqual(first[2:4], second[3:1:-1])
                    self.assertAlmostEqual(float(first[4]), -float(second[4]), places=18)
                left, right = lines[0].split()[2:4]
                self.assertAlmostEqual(float(lines[0].split()[4]), series[left][0] - series[right][0], places=18)
            mapping = (root / "config/svinf.dat").read_text().splitlines()[1:]
            self.assertEqual([line[98:104].strip() for line in mapping], ["SIM1", "SIM2", "SIM3", "SIM4"])
            self.assertTrue(all(line[52:56] == "2020" for line in mapping))
            table = (root / "config/file_table").read_text().splitlines()[1:-1]
            self.assertTrue(all((root / line.split()[1]).is_file() for line in table))
            manifest = json.loads((root / "config/manifest.json").read_text())
            self.assertEqual(manifest["samples_per_clock"], 360)

    def test_inputs_split_at_midnight_with_continuous_clock_differences(self):
        duration_s = 86420
        with tempfile.TemporaryDirectory(prefix="gstar across midnight ") as directory:
            root = Path(directory)
            series = demo.prepare_case(root, "centralized", duration_s=duration_s)
            self.assertEqual({len(values) for values in series.values()}, {8642})
            self.assertEqual(
                {path.name for path in (root / "clk").glob("*.CLK")},
                {"SIM0MGNFIN_20260010000_01D_10S_CLK.CLK",
                 "SIM0MGNFIN_20260020000_01D_10S_CLK.CLK"},
            )
            pairs = list(itertools.combinations(demo.SATELLITES, 2))
            expected_pfd_names = {f"{left}_{right}_202600{day}.txt"
                                  for left, right in pairs for day in (1, 2)}
            self.assertEqual({path.name for path in (root / "pfd").glob("*.txt")}, expected_pfd_names)
            for day_offset, sample_count in ((0, 8640), (1, 2)):
                day = demo.START + timedelta(days=day_offset)
                year_doy = day.strftime("%Y%j")
                records = [line for line in
                           (root / f"clk/SIM0MGNFIN_{year_doy}0000_01D_10S_CLK.CLK").read_text().splitlines()
                           if line.startswith("AS ")]
                self.assertEqual(len(records), sample_count * 4)
                for row, seconds in ((records[0], 0), (records[-1], (sample_count - 1) * 10)):
                    parts = row.split()
                    epoch = day + timedelta(seconds=seconds)
                    self.assertEqual([int(value) for value in parts[2:7]],
                                     [epoch.year, epoch.month, epoch.day, epoch.hour, epoch.minute])
                    self.assertEqual(float(parts[7]), epoch.second)
                for row_index, row in enumerate(records):
                    self.assertEqual([int(value) for value in row.split()[2:5]],
                                     [day.year, day.month, day.day])
                    satellite = demo.SATELLITES[row_index % 4]
                    self.assertEqual(row[3:7].strip(), str(int(satellite)))
                    global_step = day_offset * 8640 + row_index // 4
                    # CLK stores 12 significant digits; tolerance follows that
                    # format instead of assuming the retired WPM phase scale.
                    expected = series[satellite][global_step]
                    quantum = 10.0 ** (math.floor(math.log10(abs(expected))) - 11)
                    self.assertLessEqual(abs(float(row[40:60]) - expected), 0.5001 * quantum)
                mjd = (day.date() - date(1858, 11, 17)).days
                for left, right in pairs:
                    lines = (root / f"pfd/{left}_{right}_{year_doy}.txt").read_text().splitlines()
                    self.assertEqual(len(lines), sample_count * 2)
                    self.assertEqual(float(lines[0].split()[1]), 0)
                    self.assertEqual(float(lines[-1].split()[1]), (sample_count - 1) * 10)
                    for local_step in range(sample_count):
                        first, second = (lines[2 * local_step + offset].split() for offset in (0, 1))
                        self.assertEqual(int(first[0]), mjd)
                        self.assertEqual(float(first[1]), local_step * 10)
                        self.assertEqual(first[:2], second[:2])
                        self.assertEqual(first[2:4], [left, right])
                        self.assertEqual(second[2:4], [right, left])
                        global_step = day_offset * 8640 + local_step
                        difference = series[left][global_step] - series[right][global_step]
                        self.assertAlmostEqual(float(first[4]), difference, places=18)
                        self.assertAlmostEqual(float(second[4]), -difference, places=18)
            manifest = json.loads((root / "config/manifest.json").read_text())
            self.assertEqual(manifest["duration_s"], duration_s)
            self.assertEqual(manifest["samples_per_clock"], 8642)
            self.assertIn("00 00 00 86420 [GPST]", (root / "config/Timescale.cfg").read_text())

    def test_existing_results_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / "my-results.txt"
            sentinel.write_text("keep")
            with self.assertRaisesRegex(ValueError, "not empty"):
                demo.prepare_case(root, "centralized", duration_s=TEST_DURATION)
            self.assertEqual(sentinel.read_text(), "keep")

    def test_engine_errors_are_rejected_even_with_a_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            (root / "results").mkdir()
            console = root / "logs/console.log"
            log = root / "results/gstar.log"
            console.write_text("###WARNING: no site selected\n")
            log.write_text("[info] Finished\n")
            demo.check_engine_logs(root)
            for message in ("[error] Failed", "[critical] Failed", "***ERROR(reader): failed", "###ERROR: failed", ""):
                log.write_text(message)
                with self.assertRaises(ValueError):
                    demo.check_engine_logs(root)

    def test_iem_parser_rejects_missing_nonfinite_and_disordered_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "IEM.txt"
            lines = [f"2026 01 01 {i * 10} 204 1e-6 IEM 2e-6\n" for i in range(3, 360)]
            path.write_text("".join(lines))
            self.assertEqual(len(demo.read_iem(path, duration_s=TEST_DURATION)), 357)
            shifted_window = [f"2026 01 01 {i * 10} 204 1e-6 IEM 2e-6\n" for i in range(357)]
            for bad_lines in (lines[:2], [*lines[:3], lines[3].replace("2e-6", "nan"), *lines[4:]],
                              [lines[1], lines[0], *lines[2:]], lines[:50] + lines[51:], shifted_window):
                path.write_text("".join(bad_lines))
                with self.assertRaises(ValueError):
                    demo.read_iem(path, duration_s=TEST_DURATION)

    def test_report_records_all_outputs_and_csv_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            series, selected = self.create_products(root, "distributed_ci")
            summary = demo.write_report(root, "distributed_ci")
            self.assertEqual(len(summary["outputs"]), 4)
            self.assertIn("iem_phase_s", (root / "phase.csv").read_text().splitlines()[0])
            self.assertIn("<svg", (root / "report.html").read_text(encoding="utf-8"))
            self.assertTrue((root / "figures/phase.svg").is_file())
            self.assertEqual(summary["adev"]["series"], ["SIM1", "SIM2", "SIM3", "SIM4", "Ensemble"])
            self.assertEqual(summary["adev"]["target_taus_s"], [10, 30, 100, 300, 1000])
            self.assertEqual(summary["adev"]["requested_target_taus_s"], list(demo.TARGET_TAUS))
            self.assertEqual(summary["adev"]["target_sample_counts"], [355, 117, 34, 10, 2])
            self.assertEqual(len(summary["adev"]["curve_labels"]), 5)
            for extension in ("svg", "png", "pdf"):
                self.assertGreater((root / f"figures/adev.{extension}").stat().st_size, 1000)
            with (root / "analysis/stability_summary.tsv").open() as stream:
                table = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(table), 25)
            self.assertTrue(all(int(row["sample_count"]) >= 2 for row in table))
            # Independent non-overlapping second-difference calculation at tau=30 s.
            # This catches using residuals, nanoseconds, OADEV, or a nearest octave tau.
            phases = series["0101"][3:360]
            m = 3
            differences = [phases[i + 2*m] - 2*phases[i + m] + phases[i]
                           for i in range(0, len(phases) - 2*m, m)]
            expected = math.sqrt(sum(value*value for value in differences) / (2 * len(differences))) / 30
            actual = next(row for row in table if row["series"] == "SIM1" and float(row["tau_s"]) == 30)
            self.assertAlmostEqual(float(actual["adev"]) / expected, 1.0, places=12)
            self.assertEqual(int(actual["sample_count"]), len(differences))

    def test_adev_rejects_misaligned_and_nonfinite_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, selected = self.create_products(root)
            rows = demo.read_iem(selected, duration_s=TEST_DURATION)
            path = selected.parent / "SIM1.txt"
            original = path.read_text()
            self.assertEqual(len(demo.read_common_origins(selected, rows)["SIM1"]), 357)
            for invalid in (original.replace("2026 01 01 30 ", "2026 01 01 20 ", 1),
                            "\n".join(original.splitlines()[1:]),
                            original.replace(" 99e-6 ", " nan ", 1)):
                path.write_text(invalid)
                with self.assertRaises(ValueError):
                    demo.read_common_origins(selected, rows)

    def test_report_only_preserves_engine_results_and_input_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_products(root)
            # Report refresh must read saved products, even if generation metadata changes.
            manifest_path = root / "config/manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["seed"] = 999
            manifest_path.write_text(json.dumps(manifest))
            files = [path for name in ("config", "clk", "pfd", "results")
                     for path in (root / name).rglob("*") if path.is_file()]
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
            self.assertEqual(demo.main(["--report-only", "--output", str(root)]), 0)
            self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files})
            self.assertTrue((root / "analysis/adev.tsv").is_file())
            summary = json.loads((root / "summary.json").read_text())
            self.assertIsNone(summary["execution"]["engine_exit_code"])
            self.assertNotIn("engine exit code zero", summary["checks"])
            with (root / "phase.csv").open() as stream:
                first = next(csv.DictReader(stream))
            raw_phase = float((root / "results/SIM1.txt").read_text().splitlines()[0].split()[4])
            self.assertEqual(float(first["0101_phase_s"]), raw_phase)

    def test_report_only_rejects_duration_changes_without_touching_saved_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_products(root)
            (root / "report.html").write_text("keep the existing report")
            before = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in root.rglob("*") if path.is_file()}
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = demo.main(["--report-only", "--days", "10", "--output", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("--days differs from saved duration", errors.getvalue())
            after = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
