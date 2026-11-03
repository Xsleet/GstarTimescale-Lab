import hashlib
import json
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from tools import thesis_section43 as thesis
from tools.check_public_tree import audit_file


class DataArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, name='phase/example.csv', symlink=False, wrong_hash=False):
        content = b'time_s,phase_s\n0,0\n'
        manifest = json.dumps({'files': {name: {
            'bytes': len(content),
            'sha256': '0' * 64 if wrong_hash else hashlib.sha256(content).hexdigest()
        }}}).encode()
        path = self.root / 'data.zip'
        with zipfile.ZipFile(path, 'w') as z:
            entry = zipfile.ZipInfo(name)
            if symlink:
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(entry, content)
            z.writestr('manifest.json', manifest)
        descriptor = {'bytes': path.stat().st_size, 'sha256': thesis.sha256(path),
                      'expanded_bytes': len(content) + len(manifest), 'file_count': 2,
                      'manifest_sha256': hashlib.sha256(manifest).hexdigest()}
        return path, descriptor

    def test_verified_extraction_and_no_overwrite(self):
        source, info = self.archive()
        target = self.root / 'installed'
        thesis.extract_archive(source, target, info)
        self.assertTrue((target / 'phase/example.csv').is_file())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            thesis.extract_archive(source, target, info)

    def test_traversal_and_symlinks_are_rejected(self):
        for name, link in [('../escape.csv', False), ('phase/example.csv', True)]:
            source, info = self.archive(name, link)
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                thesis.extract_archive(source, self.root / 'installed', info)
            self.assertFalse((self.root / 'installed').exists())
            self.assertFalse((self.root / 'escape.csv').exists())

    def test_download_corruption_is_rejected(self):
        source, info = self.archive()
        source.write_bytes(source.read_bytes() + b'corruption')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            thesis.extract_archive(source, self.root / 'installed', info)

    def test_member_corruption_cleans_staging(self):
        source, info = self.archive(wrong_hash=True)
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            thesis.extract_archive(source, self.root / 'installed', info)
        self.assertFalse((self.root / 'installed').exists())
        self.assertEqual(list(self.root.glob('.thesis43-*')), [])

    def test_release_is_data_only(self):
        release = thesis.release()
        self.assertEqual(set(release['assets']), {'analysis', 'inputs'})
        for descriptor in release['assets'].values():
            self.assertRegex(descriptor['sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(descriptor['filename'].startswith('thesis-section43-'))
        self.assertEqual(audit_file('examples/thesis-section43/reference/adev_octave.csv', b'a,b\n1,2\n'), [])
        self.assertTrue(audit_file('examples/thesis-section43/data.zip', b'PK\x03\x04'))
        self.assertTrue(audit_file('examples/thesis-section43/engine.exe', b'MZ'))


class ScientificAnalysisTests(unittest.TestCase):
    def test_exact_tau_and_quadratic_phase(self):
        # x(t)=a*t^2 gives non-overlapping ADEV sqrt(2)*a*tau.
        t = np.arange(2000) * 10.0
        a = 1e-18
        tau, sigma, _, terms = thesis.adev(a * t * t, [10, 100, 1000])
        np.testing.assert_array_equal(tau, [10, 100, 1000])
        np.testing.assert_allclose(sigma, np.sqrt(2) * a * tau, rtol=1e-8, atol=0)
        self.assertTrue(np.all(terms > 0))

    def test_plot_mapping_does_not_silently_drop_extra_table_group(self):
        self.assertEqual(thesis.PLOTTED, (1, 2, 4, 5))
        self.assertEqual(thesis.COVARIANCE_GROUP, 2)
        paper = json.loads((thesis.EXAMPLE / 'paper-values.json').read_text(encoding='utf-8'))
        self.assertEqual(paper['tau_s'], [10, 100, 1000, 10000, 100000])
        self.assertEqual(set(paper['values']), set(thesis.METHODS))

    def make_rerun(self, root, *, error=False, missing_epoch=False):
        (root / 'results').mkdir()
        (root / 'logs/execute_test').mkdir(parents=True)
        t = np.arange(30, 20030, 10)
        phase = 1e-18 * t * t
        frame = pd.DataFrame({'time_s': t, **{f'clock{i}_s': phase * i for i in range(1,5)},
                              **{m: phase for m in thesis.METHODS}})
        values = np.zeros((len(t), 14))
        values[:, 0] = 2026
        values[:, 1:3] = 1
        values[:, 3] = t
        values[:, 13] = phase
        if missing_epoch:
            values = np.delete(values, 100, axis=0)
        np.savetxt(root / 'results/IEM.txt', values)
        message = '[error] LDLT failed' if error else ''
        (root / 'results/gstar.log').write_text(message)
        (root / 'logs/execute_test/console.log').write_text(message)
        (root / 'logs/execute_test/execution.json').write_text(json.dumps({
            'status': 'execution_completed', 'configuration': {'rank_remedy': 'GREENHALL'}}))
        return frame

    def test_error_log_prevents_success_even_with_complete_identical_phase(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame = self.make_rerun(root, error=True)
            with patch.object(thesis, 'verify', return_value={}), patch.object(thesis, 'load_phase', return_value=frame):
                passed = thesis.compare_rerun(root, root, 'mixed_2plus2_group01', 'GREENHALL', root / 'comparison')
            self.assertFalse(passed)
            report = json.loads((root / 'comparison/comparison.json').read_text())
            self.assertTrue(report['complete_finite_aligned_epochs'])
            self.assertEqual(report['max_adev_relative_difference'], 0)

    def test_missing_epoch_is_not_compressed_into_a_false_adev(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame = self.make_rerun(root, missing_epoch=True)
            with patch.object(thesis, 'verify', return_value={}), patch.object(thesis, 'load_phase', return_value=frame):
                passed = thesis.compare_rerun(root, root, 'mixed_2plus2_group01', 'GREENHALL', root / 'comparison')
            self.assertFalse(passed)
            self.assertFalse((root / 'comparison/adev_comparison.csv').exists())


if __name__ == '__main__':
    unittest.main()
