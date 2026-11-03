import hashlib
import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

import lab
from tools.check_public_tree import audit_file


class RuntimeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files = {"GstarTimescale.exe": b"test fixture, not executable", "licenses/notice.txt": b"notice"}
        self.archive = self.root / "teacher.zip"
        self.make_archive()

    def make_archive(self, extra=None, symlink=False, duplicate=False):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w") as package:
                for name, data in self.files.items():
                    info = zipfile.ZipInfo(name)
                    if symlink and name == "GstarTimescale.exe":
                        info.create_system = 3
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    package.writestr(info, data)
                if extra:
                    package.writestr(*extra)
                if duplicate:
                    package.writestr("GstarTimescale.exe", b"duplicate")
        self.manifest = {
            "version": "test", "platform": "windows-x64", "distribution": "instructor-only",
            "archive_sha256": lab.sha256(self.archive),
            "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                      for name, data in self.files.items()}}
        self.save_manifest()

    def save_manifest(self):
        (self.root / "engine-release.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_exact_archive_install_and_integrity(self):
        engine = lab.install_engine(self.archive, self.root)
        self.assertEqual(lab.check_engine(self.root), engine / "GstarTimescale.exe")
        self.assertEqual((engine / "licenses/notice.txt").read_bytes(), b"notice")
        self.assertEqual(list(self.root.glob(".engine-install-*")), [])

    def test_archive_hash_mismatch_leaves_no_install(self):
        self.archive.write_bytes(self.archive.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "Archive SHA256"):
            lab.install_engine(self.archive, self.root)
        self.assertFalse((self.root / "engine").exists())

    def test_internal_hash_failure_cleans_staging(self):
        self.manifest["files"]["GstarTimescale.exe"]["sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "file SHA256"):
            lab.install_engine(self.archive, self.root)
        self.assertFalse((self.root / "engine").exists())
        self.assertEqual(list(self.root.glob(".engine-install-*")), [])

    def test_existing_installation_is_preserved(self):
        engine = lab.install_engine(self.archive, self.root)
        with self.assertRaisesRegex(ValueError, "already exists"):
            lab.install_engine(self.archive, self.root)
        self.assertEqual((engine / "GstarTimescale.exe").read_bytes(), self.files["GstarTimescale.exe"])

    def test_unexpected_or_traversal_entry_rejected(self):
        for name in ("extra.dll", "../escape.txt", "/absolute.txt", "C:/outside.txt", "a\\b.txt"):
            with self.subTest(name=name):
                self.make_archive(extra=(name, b"bad"))
                with self.assertRaises(ValueError):
                    lab.install_engine(self.archive, self.root)
                self.assertFalse((self.root / "engine").exists())

    def test_unsafe_manifest_paths_rejected(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/outside.txt", "a\\b.txt", "a//b.txt", "a/./b.txt"):
            self.assertFalse(lab.safe_name(name))

    def test_symlinks_and_duplicate_entries_rejected(self):
        for options in ({"symlink": True}, {"duplicate": True}):
            self.make_archive(**options)
            with self.assertRaises(ValueError):
                lab.install_engine(self.archive, self.root)
            self.assertFalse((self.root / "engine").exists())

    def test_size_mismatch_rejected(self):
        self.manifest["files"]["GstarTimescale.exe"]["size"] += 1
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Unsafe archive"):
            lab.install_engine(self.archive, self.root)

    def test_runtime_tamper_detected_before_execution(self):
        engine = lab.install_engine(self.archive, self.root)
        (engine / "GstarTimescale.exe").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            lab.check_engine(self.root)

    def test_extra_runtime_dll_rejected(self):
        engine = lab.install_engine(self.archive, self.root)
        (engine / "unknown.dll").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "file list differs"):
            lab.check_engine(self.root)


class PublicationAuditTests(unittest.TestCase):
    def test_teaching_text_allowed(self):
        self.assertEqual(audit_file("docs/guide.md", b"Use the instructor runtime."), [])
        self.assertEqual(audit_file("tools/generate.py", b"print('hello')"), [])

    def test_core_source_archives_and_runtime_denied(self):
        for name in ("GstarTimescale/src/main.cpp", "include/solver.h", "engine/GstarTimescale.exe",
                     "docs/engine.zip", "tools/solver.cpp", "Runs/results.json", "private/secret.md"):
            with self.subTest(name=name):
                self.assertTrue(audit_file(name, b"contents"))

    def test_binary_renaming_and_symlinks_denied(self):
        self.assertTrue(audit_file("docs/hidden.md", b"MZbinary"))
        self.assertTrue(audit_file("docs/hidden.md", b"PK\x03\x04zip"))
        self.assertTrue(audit_file("docs/linked.md", b"../outside", "120000"))

    def test_private_path_and_token_denied(self):
        local_path = "Z:" + "/Users/" + "example/secret"
        token = "ghp_" + "a" * 30
        self.assertTrue(audit_file("docs/bad.md", local_path.encode()))
        self.assertTrue(audit_file("docs/bad.md", token.encode()))


if __name__ == "__main__":
    unittest.main()
