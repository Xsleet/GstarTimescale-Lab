from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tools import thesis_section52 as thesis
from tools.run_config import inspect_config


class Thesis52Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / 'inputs'
        (self.inputs / 'tables').mkdir(parents=True)
        (self.inputs / 'recipes').mkdir()
        for name in ('file_table', 'svinf.dat', 'leap.sec', 'pan_info'):
            shutil.copyfile(thesis.ROOT / 'config' / name, self.inputs / 'tables' / name)
        session = ' 000 0101 0101 {Phase:[1e-4,3e-11], Frequency:[1e-6,2e-13]}\n'
        (self.inputs / 'recipes/group01.json').write_text(json.dumps(
            {s: {'session.obj': session} for s in thesis.SCENARIOS}), encoding='utf-8')
        shutil.copyfile(self.inputs / 'recipes/group01.json', self.inputs / 'recipes/group02.json')
        for variant in ('base', 'csac_join', 'mro_join'):
            (self.inputs / 'groups/group01/pfd' / variant).mkdir(parents=True)

    def prepare(self, name='case', **kwargs):
        destination = self.root / name
        with patch.object(thesis.archive, 'verify', return_value={}), patch.object(thesis, 'sync_observations'):
            thesis.prepare_case(self.inputs, destination, **kwargs)
        return destination

    def test_native_configuration_preserves_priors_and_exposes_modes(self):
        robust = self.prepare('robust', scenario='mro_join')
        cfg = thesis.fields(robust / 'config/Timescale.cfg')
        self.assertEqual(cfg['Centralized admission covariance initialization'], 'calibrated_bounded_influence')
        self.assertEqual(cfg['Centralized admission observation window'], '120')
        self.assertEqual(cfg['Centralized admission covariance inflation'], 'off')
        self.assertIn('Phase:[1e-4,3e-11]', (robust / 'config/session.obj').read_text())
        schedule = thesis.read_schedule(robust / 'config/membership_schedule.tsv', thesis.START, thesis.END)
        self.assertEqual(schedule[1][2] - schedule[0][2], {'0106'})
        fixed = self.prepare('fixed', scenario='csac_join', admission='fixed', gamma=10)
        cfg = thesis.fields(fixed / 'config/Timescale.cfg')
        self.assertEqual(cfg['Centralized admission covariance initialization'], 'legacy')
        self.assertEqual(cfg['Centralized admission covariance inflation scale'], '10')
        self.assertEqual(cfg['Centralized admission covariance inflation'], 'on')
        self.assertEqual(inspect_config(fixed / 'config/file_table', fixed)['rank_remedy'], 'GREENHALL')
        self.assertNotIn(str(self.root), (fixed / 'config/Timescale.cfg').read_text())

    def test_exit_removes_the_selected_clock_type(self):
        for kind, prn in [('csac', '0104'), ('mro', '0102')]:
            case = self.prepare(kind, scenario=f'{kind}_exit', event_day=4)
            rows = thesis.read_schedule(case / 'config/membership_schedule.tsv', thesis.START, thesis.END)
            self.assertEqual(rows[0][2] - rows[1][2], {prn})
            self.assertEqual(rows[1][0], datetime(2026, 1, 5))

    def test_additional_groups_scale_all_priors_without_changing_process_coefficients(self):
        session = (' 000 0101 0101 {Phase:[1e-4,3e-11], Frequency:[1e-6,2e-13]}\n'
                   ' 000 0106 0106 {Phase:[1e-4,4e-11], Frequency:[1e-6,3e-13]}\n')
        (self.inputs / 'recipes/group02.json').write_text(json.dumps(
            {s: {'session.obj': session} for s in thesis.SCENARIOS}), encoding='utf-8')
        scaled = self.prepare('scaled', group='group02', scenario='mro_join')
        text = (scaled / 'config/session.obj').read_text()
        self.assertIn('Phase:[1e-7,3e-11], Frequency:[1e-9,2e-13]', text)
        self.assertIn('Phase:[1e-7,4e-11], Frequency:[1e-9,3e-13]', text)
        original = self.prepare('original', group='group02', scenario='mro_join', prior_profile='original')
        self.assertIn(session, (original / 'config/session.obj').read_text())

    def test_invalid_parameters_create_no_partial_directory(self):
        for i, kwargs in enumerate([{'gamma': float('nan')}, {'window': -10}, {'window': 15},
                                    {'event_day': 10}, {'event_day': 5.00001}]):
            destination = self.root / f'invalid{i}'
            with self.assertRaises(ValueError):
                thesis.prepare_case(self.inputs, destination, **kwargs)
            self.assertFalse(destination.exists())

    def test_schedule_rejects_gaps_duplicates_and_missing_coverage(self):
        path = self.root / 'schedule.tsv'
        header = 'start_gpst\tend_gpst\tactive_prns\n'
        for contents in [
            '2026-01-02T00:00:00\t2026-01-11T00:00:00\t0101,0102\n',
            '2026-01-01T00:00:00\t2026-01-11T00:00:00\t0101,0101\n',
            '2026-01-01T00:00:00\t2026-01-10T00:00:00\t0101,0102\n',
        ]:
            path.write_text(header + contents, encoding='utf-8')
            with self.assertRaises(ValueError):
                thesis.read_schedule(path, thesis.START, thesis.END)

    def test_observation_sync_filters_both_directions_at_exact_event_and_keeps_prior_copy(self):
        case = self.prepare(scenario='csac_join', event_day=5 + 20/86400)
        pool = self.inputs / 'groups/group01/pfd/csac_join'
        name = '0101_0105_2026006.txt'
        day = datetime(2026, 1, 6)
        mjd = (day - datetime(1858, 11, 17)).days
        lines = [f' {mjd} {second:.5f} {a} {b} {value:.16e}\n'
                 for second in (0, 10, 20, 30) for a, b, value in [('0101', '0105', 3e-6), ('0105', '0101', -3e-6)]]
        (pool / name).write_text(''.join(lines), encoding='utf-8')
        selected = thesis.sync_observations(case)
        self.assertEqual((selected / name).read_text(), ''.join(lines[4:]))
        original_hash = thesis.archive.sha256(selected / name)
        schedule = case / 'config/membership_schedule.tsv'
        schedule.write_text(schedule.read_text().replace('00:00:20', '00:00:30'), encoding='utf-8')
        second = thesis.sync_observations(case)
        self.assertEqual((second / name).read_text(), ''.join(lines[6:]))
        self.assertEqual(thesis.archive.sha256(selected / name), original_hash)
        self.assertEqual(thesis.fields(case / 'config/Timescale.cfg')['PFD data directory'], second.name)

    def test_transients_follow_equation_5_21_at_actual_joint_epoch(self):
        times = np.datetime64('2026-01-01') + np.arange(8) * np.timedelta64(10, 's')
        baseline = np.arange(8) * 1e-8
        residual = np.array([0., 0., 0., 0., 2., 5., 8., 11.]) * 1e-9
        result = thesis.transient_metrics(times, baseline, baseline + residual, str(times[4]))
        self.assertAlmostEqual(result['phase_jump_s']/1e-9, 2)
        self.assertAlmostEqual(result['frequency_jump']/1e-10, 2)
        with self.assertRaises(ValueError):
            thesis.transient_metrics(times, baseline, baseline + residual, str(times[0]))

    def test_failed_native_run_is_not_accepted_as_a_plot(self):
        case = self.prepare()
        (case / 'results').mkdir()
        (case / 'results/gstar.log').write_text('[error] LDLT failed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'did not complete'):
            thesis.load_case(case)

    def test_four_group_summary_uses_magnitudes_and_common_methods(self):
        paths = []
        for index, group in enumerate(thesis.GROUPS):
            folder = self.root / group
            folder.mkdir()
            transients = [{'case': 'csac_robust', 'phase_jump_s': (-1)**index*(index+1)*1e-9,
                           'frequency_jump': (-1)**index*(index+1)*1e-12}]
            if index == 0:
                transients.append({'case': 'csac_fixed10', 'phase_jump_s': 1., 'frequency_jump': 1.})
            (folder / 'validation.json').write_text(json.dumps({'group': group, 'event_gpst': '2026-01-06',
                'interval_s': 10., 'transients': transients}), encoding='utf-8')
            paths.append(folder)
        output = self.root / 'summary'
        thesis.summarize_events(paths, output)
        record = json.loads((output / 'summary.json').read_text())
        self.assertEqual(record['methods_present_in_all_groups'], ['csac_robust'])
        self.assertEqual(record['rows'][0]['groups'], 4)
        self.assertAlmostEqual(record['rows'][0]['mean_abs_phase_jump_ns'], 2.5)
        self.assertAlmostEqual(record['rows'][0]['mean_abs_frequency_jump']/1e-12, 2.5)
        with self.assertRaises(ValueError):
            thesis.summarize_events(paths[:-1]+[paths[0]], self.root / 'bad_summary')


if __name__ == '__main__':
    unittest.main()
