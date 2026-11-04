import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from tools import thesis_section44 as thesis
from tools.run_config import RANK_REMEDIES


class Thesis44Tests(unittest.TestCase):
    def test_improvement_keeps_negative_values(self):
        np.testing.assert_allclose(thesis.improvement([2., 2.], [1., 3.]), [50., -50.])
        with self.assertRaises(ValueError):
            thesis.improvement([0.], [1.])

    def test_model_terms_and_adev_definition(self):
        tau = np.array([10., 100., 1000.])
        np.testing.assert_allclose(thesis.theory_adev(tau, 4., 0., 0.), 2/np.sqrt(tau))
        np.testing.assert_allclose(thesis.theory_adev(tau, 0., 3., 0.), np.sqrt(tau))
        t = np.arange(5000) * 10.
        result = thesis.archive.adev(1e-18*t*t, tau)
        np.testing.assert_array_equal(result[0], tau)
        np.testing.assert_allclose(result[1], np.sqrt(2)*1e-18*tau, rtol=1e-8)

    def test_phase_rejects_shift_gaps_and_nonfinite_values(self):
        t = np.arange(30, 864000, 10)
        frame = pd.DataFrame({'time_s': t, **{f'clock{k}_s': t*1e-12 for k in range(1,5)},
                              'baseline': t*1e-12, 'adjusted': t*1e-12})
        with patch.object(pd, 'read_csv', return_value=frame):
            self.assertEqual(len(thesis.load_phase(Path('example.csv'), True)), 86397)
            for column, value in [('time_s', 50), ('baseline', float('nan'))]:
                saved = frame.loc[1, column]
                frame.loc[1, column] = value
                with self.assertRaises(ValueError):
                    thesis.load_phase(Path('example.csv'), True)
                frame.loc[1, column] = saved

    def test_two_parameter_variants_keep_all_rank_remedies_editable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / 'inputs'
            (inputs / 'tables').mkdir(parents=True)
            (inputs / 'recipes').mkdir()
            for name in ('file_table', 'svinf.dat', 'leap.sec', 'pan_info'):
                (inputs / 'tables' / name).write_text('fixture')
            recipes = {v: {'Timescale.cfg': ' Rank deficiency remedy = GREENHALL\n PFD data directory = @PFD@\n',
                           'session.obj': '{TotalPhase:[1e-4,2e-11], Phase:[1e-4,2e-11], Frequency:[1e-6,' + q + ']}\n'}
                       for v, q in [('baseline', '1e-13'), ('adjusted', '2e-13')]}
            (inputs / 'recipes/mixed_2plus2_group01.json').write_text(json.dumps(recipes))
            with patch.object(thesis.archive, 'verify', return_value={}):
                for variant in thesis.VARIANTS:
                    for method in RANK_REMEDIES:
                        dest = root / f'{variant}_{method}'
                        thesis.prepare_case(inputs, dest, 'mixed_2plus2_group01', variant, method)
                        cfg = (dest / 'config/Timescale.cfg').read_text()
                        session = (dest / 'config/session.obj').read_text()
                        self.assertIn(f' Rank deficiency remedy = {method}\n', cfg)
                        self.assertNotIn('TotalPhase:', session)
                        self.assertIn('Phase:[1e-7,2e-11]', session)
                        self.assertIn('1e-13' if variant == 'baseline' else '2e-13', session)
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    thesis.prepare_case(inputs, dest, 'mixed_2plus2_group01', variant, method)

    def test_release_and_group_mapping_are_explicit(self):
        self.assertEqual(thesis.PLOTTED, (1, 2, 4, 5))
        self.assertEqual(thesis.SEARCH_PLOTTED, (1, 2, 4, 3))
        catalog = thesis.release()
        self.assertEqual(catalog['release_tag'], 'thesis-section44-data-v1')
        for item in catalog['assets'].values():
            self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(item['filename'].startswith('thesis-section44-'))

    def test_initialization_profiles_preserve_process_coefficients(self):
        original = '{TotalPhase:[1e-4,3e-11], Phase:[1e-4,3e-11], Frequency:[1e-6,7e-13], Link_Noise:{Default:1e-14}}'
        portable = thesis.runtime_session(original, 'portable')
        self.assertIn('Phase:[1e-7,3e-11]', portable)
        self.assertIn('Frequency:[1e-9,7e-13]', portable)
        self.assertIn('Link_Noise:{Default:1e-12}', portable)
        archived = thesis.runtime_session(original, 'archived')
        self.assertIn('Phase:[1e-4,3e-11]', archived)
        self.assertIn('Frequency:[1e-6,7e-13]', archived)
        self.assertIn('Link_Noise:{Default:1e-14}', archived)

    def test_failed_solver_run_is_not_accepted_for_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'gstar.log').write_text('[error] bad innovation')
            with self.assertRaisesRegex(ValueError, 'solver logged an error'):
                thesis.compare_runs(root, root, root / 'comparison')
            self.assertFalse((root / 'comparison').exists())


if __name__ == '__main__':
    unittest.main()
