import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import prepare_csac, run_demo
from tools.run_config import RANK_REMEDIES


class ArchivedCsacTests(unittest.TestCase):
    def test_installs_native_inputs_unchanged_and_protects_existing_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {"config/file_table": b"+FileTable\n TimescaleCfg config/Timescale.cfg\n-FileTable\n",
                     "config/Timescale.cfg": b" Processing interval = 10\n Rank deficiency remedy = GREENHALL\n",
                     "config/session.obj": b" Phase:[1e-7,1.618e-10]\n", "clk/example.CLK": b"archived data\n"}
            manifest = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in files.items()}
            files["manifest.json"] = json.dumps({"files": manifest}).encode()
            archive = root / "data.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                for name, data in files.items():
                    stream.writestr(name, data)
            info = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size,
                    "manifest_sha256": hashlib.sha256(files["manifest.json"]).hexdigest(),
                    "file_count": len(files), "expanded_bytes": sum(map(len, files.values()))}
            output = root / "case"
            with patch.object(prepare_csac, "descriptor", return_value=info):
                prepare_csac.prepare(output, archive)
                self.assertEqual({p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}, files)
                for method in RANK_REMEDIES:
                    selected = root / method.lower()
                    prepare_csac.prepare(selected, archive, method.lower())
                    self.assertEqual((selected / "config/Timescale.cfg").read_text(),
                                     files["config/Timescale.cfg"].decode().replace("= GREENHALL", f"= {method}"))
                    for name, data in files.items():
                        if name != "config/Timescale.cfg":
                            self.assertEqual((selected / name).read_bytes(), data)
                edited = output / "config/Timescale.cfg"
                edited.write_text("user changes")
                with self.assertRaisesRegex(ValueError, "already exists"):
                    prepare_csac.prepare(output, archive)
                self.assertEqual(edited.read_text(), "user changes")
                archive.write_bytes(b"corrupted archive")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    prepare_csac.prepare(root / "invalid", archive)
                self.assertFalse((root / "invalid").exists())

    def test_retired_basic_generator_cannot_recreate_white_phase_case(self):
        with self.assertRaisesRegex(ValueError, "Unsupported clock profile"):
            run_demo.clock_series(duration_s=150, clock_profile="basic")

    def test_release_selects_four_existing_csacs(self):
        info = prepare_csac.descriptor()
        self.assertEqual(info["clocks"], ["CSAC_01", "CSAC_02", "CSAC_03", "CSAC_04"])
        self.assertEqual((info["duration_s"], info["interval_s"]), (864000, 10))


if __name__ == "__main__":
    unittest.main()
