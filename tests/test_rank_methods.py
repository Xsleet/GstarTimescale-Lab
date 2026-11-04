from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import lab
from tools import run_demo
from tools.run_config import RANK_REMEDIES, inspect_config, set_rank_remedy


class RankMethodTests(unittest.TestCase):
    def test_all_methods_reach_native_config_and_generation_record(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            for method in RANK_REMEDIES:
                root = Path(temporary) / method
                result = lab.main(["prepare", "--method", method.lower(), "--days", str(150 / 86400), "--output", str(root)])
                self.assertEqual(result, 0)
                self.assertEqual(inspect_config(Path("config/file_table"), root)["rank_remedy"], method)
                self.assertEqual(json.loads((root / "config/manifest.json").read_text())["rank_remedy"], method)

    def test_method_selection_rejects_invalid_or_duplicate_fields_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "Timescale.cfg"
            for original, method in [(" Rank deficiency remedy = GREENHALL\n", "BAD"),
                                     (" Rank deficiency remedy = GREENHALL\n" * 2, "BROWN")]:
                config.write_text(original)
                with self.assertRaises(ValueError):
                    set_rank_remedy(config, method)
                self.assertEqual(config.read_text(), original)

    def test_report_records_method_and_rejects_relabel_without_rerun(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            phases = run_demo.prepare_case(root, "centralized", duration_s=150, rank_remedy="BROWN")
            results = root / "results"
            (results / "IEM.txt").write_text("".join(
                f"2026 01 01 {i * 10} 204 1e-6 IEM {sum(p[i] for p in phases.values()) / 4:.17e}\n" for i in range(3, 15)))
            for index, phase in enumerate(phases.values(), 1):
                (results / f"SIM{index}.txt").write_text("".join(
                    f"2026 01 01 {i * 10} {phase[i]:.17e} 0 0 0 0\n" for i in range(3, 15)))
            (results / "gstar.log").write_text("[info] Finished\n")
            (root / "logs/console.log").write_text("[info] Finished\n")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run_demo.main(["--report-only", "--method", "BROWN", "--output", str(root)]), 0)
            self.assertEqual(json.loads((root / "summary.json").read_text())["rank_remedy"], "BROWN")
            before = (root / "report.html").read_bytes()
            with redirect_stderr(io.StringIO()):
                self.assertEqual(run_demo.main(["--report-only", "--method", "KPW", "--output", str(root)]), 1)
            self.assertEqual((root / "report.html").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
