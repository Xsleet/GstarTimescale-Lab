import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.run_config import execute_config, inspect_config


class ExistingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "working directory with spaces"
        (self.root / "config").mkdir(parents=True)
        self.table = self.root / "config/file_table"
        self.table.write_text("+FileTable\n TimescaleCfg config/Timescale.cfg\n object config/session.obj\n-FileTable\n", encoding="utf-8")
        (self.root / "config/session.obj").write_text("test-only session fixture\n", encoding="utf-8")
        self.cfg = self.root / "config/Timescale.cfg"
        self.cfg.write_text(
            " Start time&session length = 2026 02 28 23 50 00 1800 [GPST]\n"
            " Processing interval = 10\n Project directory = output/custom\n"
            " Timescale scope = satellite\n Estimation architecture = distributed_if\n"
            " Clock Trend state num = 2\n Clock Harmonics state num = 0\n"
            " Rank deficiency remedy = GREENHALL\n"
            " LEO Clk full name = input/clk/example_-YEARDOY-.CLK\n PFD data directory = input/pfd\n",
            encoding="utf-8")
        self.executable = self.root / "fixture.exe"
        self.executable.write_bytes(b"test fixture; subprocess is mocked")

    def test_custom_window_paths_and_architecture_are_read_without_rewriting(self):
        original = {path: path.read_bytes() for path in (self.table, self.cfg)}
        info = inspect_config(Path("config/file_table"), self.root)
        self.assertEqual(info["start"], "2026-02-28T23:50:00")
        self.assertEqual(info["end"], "2026-03-01T00:20:00")
        self.assertEqual(info["architecture"], "distributed_if")
        self.assertEqual(info["result_dir"], str((self.root / "output/custom").resolve()))
        self.assertEqual(info["inputs"]["PFD data directory"], str((self.root / "input/pfd").resolve()))
        self.assertTrue(info["inputs"]["LEO Clk full name"].endswith("example_-YEARDOY-.CLK"))
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)

    def test_post_2026_start_and_nonfinite_interval_are_rejected(self):
        original = self.cfg.read_text()
        for changed, message in ((original.replace("2026", "2027"), "after 2026"),
                                 (original.replace("interval = 10", "interval = nan"), "finite")):
            self.cfg.write_text(changed)
            with self.assertRaisesRegex(ValueError, message):
                inspect_config(self.table, self.root)

    def test_paths_with_embedded_spaces_and_duplicate_keys_are_rejected(self):
        original = self.cfg.read_text()
        for changed in (original.replace("output/custom", "output/my results"),
                        original + " Project directory = another\n"):
            self.cfg.write_text(changed)
            with self.assertRaises(ValueError):
                inspect_config(self.table, self.root)

    def test_missing_object_file_fails_before_execution(self):
        self.table.write_text(self.table.read_text().replace("config/session.obj", "config/absent.obj"))
        with self.assertRaisesRegex(ValueError, "Missing object"):
            inspect_config(self.table, self.root)

    def test_existing_results_are_preserved(self):
        output = self.root / "output/custom"
        output.mkdir(parents=True)
        saved = output / "important.txt"
        saved.write_text("keep")
        with patch("tools.run_config.subprocess.run") as runner:
            with self.assertRaisesRegex(ValueError, "not empty"):
                execute_config(self.table, self.root, self.executable)
            runner.assert_not_called()
        self.assertEqual(saved.read_text(), "keep")

    def run_mock(self, *, returncode=0, error_log=False):
        def simulate(command, **kwargs):
            self.assertEqual(kwargs["cwd"], str(self.root.resolve()))
            self.assertEqual(command[1], str(self.table.resolve()))
            kwargs["stdout"].write(b"runtime stdout\n")
            output = self.root / "output/custom"
            output.mkdir(parents=True)
            (output / "gstar.log").write_text("[error] numerical failure\n" if error_log else "[info] completed\n")
            return subprocess.CompletedProcess(command, returncode)
        return patch("tools.run_config.subprocess.run", side_effect=simulate)

    def test_success_records_config_hashes_and_does_not_claim_report_validation(self):
        expected = hashlib.sha256(self.cfg.read_bytes()).hexdigest()
        with self.run_mock():
            record = execute_config(self.table, self.root, self.executable)
        self.assertEqual(record["sha256"]["TimescaleCfg"], expected)
        self.assertEqual(record["status"], "execution_completed")
        self.assertIn("case-specific", record["validation_scope"])
        self.assertFalse((self.root / "report.html").exists())
        self.assertEqual(hashlib.sha256(self.cfg.read_bytes()).hexdigest(), expected)

    def test_nonzero_exit_is_recorded_as_failure(self):
        with self.run_mock(returncode=7):
            with self.assertRaisesRegex(ValueError, "code 7"):
                execute_config(self.table, self.root, self.executable)
        record = json.loads(next((self.root / "logs").rglob("execution.json")).read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["returncode"], 7)

    def test_error_in_log_is_failure_even_with_zero_exit(self):
        with self.run_mock(error_log=True):
            with self.assertRaisesRegex(ValueError, "contains an error"):
                execute_config(self.table, self.root, self.executable)

    def test_timeout_keeps_a_failure_record(self):
        with patch("tools.run_config.subprocess.run", side_effect=subprocess.TimeoutExpired("fixture", 1)):
            with self.assertRaisesRegex(ValueError, "timed out"):
                execute_config(self.table, self.root, self.executable, timeout=1)
        record = json.loads(next((self.root / "logs").rglob("execution.json")).read_text())
        self.assertEqual(record["status"], "failed")


if __name__ == "__main__":
    unittest.main()
