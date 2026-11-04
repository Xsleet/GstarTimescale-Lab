import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tools import optimize_diffusion as opt
from tools.run_config import initialize_case


class DiffusionOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()  # Normalize Windows short-name TEMP paths.
        self.case = self.root / 'train'
        initialize_case(self.case, opt.ROOT / 'config')
        path = self.case / 'config/Timescale.cfg'
        text = path.read_text(encoding='utf-8')
        import re
        text = re.sub(r'(?m)^([ \t]*Start time&session length[ \t]*=).*$',
                      r'\1 2026 01 01 00 00 00 864000 [GPST]', text)
        path.write_text(text, encoding='utf-8')

    def test_diffusion_is_squared_sigma_and_only_process_terms_change(self):
        text = (self.case/'config/session.obj').read_text(encoding='utf-8')
        initial = opt.read_coefficients(text)
        values = {c: qs.copy() for c, qs in initial.items()}
        clock = next(iter(values))
        values[clock]['q2'] *= 4
        changed = opt.patch_coefficients(text, values)
        import re
        before = dict((c, line) for _, c, line in opt.clock_rows(text))
        after = dict((c, line) for _, c, line in opt.clock_rows(changed))
        for c in initial:
            for field in ('Phase','Frequency'):
                a = re.search(field+r':\[([^,]+),([^]]+)\]',before[c])
                b = re.search(field+r':\[([^,]+),([^]]+)\]',after[c])
                self.assertEqual(a[1],b[1])  # no change to initial uncertainty
                factor = 2 if c == clock and field == 'Frequency' else 1
                self.assertAlmostEqual(float(b[2])/float(a[2]),factor)
        with self.assertRaises(ValueError):
            opt.patch_coefficients(text, {})

    def test_clone_rebases_inputs_without_changing_source(self):
        source_bytes = (self.case/'config/Timescale.cfg').read_bytes()
        before = opt.inspect_case(self.case)
        target = self.root/'nested/new_case'
        after = opt.clone_case(self.case,target)
        self.assertEqual(before['inputs'],after['inputs'])
        self.assertEqual(before['start'],after['start'])
        self.assertEqual(Path(after['result_dir']),target/'results')
        self.assertEqual(source_bytes,(self.case/'config/Timescale.cfg').read_bytes())
        with self.assertRaisesRegex(ValueError,'already exists'):
            opt.clone_case(self.case,target)

    def test_objective_uses_actual_phase_at_exact_taus(self):
        t = np.arange(5000)*10.
        taus = [100,300,1000]
        score, rows = opt.score_phase(1e-18*t*t,10,taus)
        self.assertAlmostEqual(score,float(np.mean(np.log10(np.sqrt(2)*1e-18*np.array(taus)))),places=9)
        self.assertEqual([r['tau_s'] for r in rows],taus)
        self.assertTrue(all(r['terms'] >= 2 for r in rows))

    def test_search_calls_engine_per_trial_and_applies_to_future_window(self):
        config_path=self.root/'search.json'
        opt.initialize(self.case,config_path)
        config=json.loads(config_path.read_text(encoding='utf-8'))
        engine=self.root/'test_runtime.exe'
        engine.write_bytes(b'fixture - never executed')
        config.update(engine='test_runtime.exe',trials=4,startup_trials=2,shared_q2_scale=False)
        # The default search must keep the initial q1 values during every trial.
        config_path.write_text(json.dumps(config), encoding='utf-8')
        calls=[]
        def fake_evaluate(case,engine,timeout,taus):
            coefficients=opt.read_coefficients((case/'config/session.obj').read_text(encoding='utf-8'))
            calls.append(coefficients)
            return {'loss':sum(math.log10(v['q2'])**2 for v in coefficients.values()),'seconds':.01}
        output=self.root/'search'
        with patch.object(opt,'input_fingerprints',return_value={'fixture':'hash'}), patch.object(opt,'evaluate',side_effect=fake_evaluate):
            opt.run_search(config_path,output)
        self.assertEqual(len(calls),4)
        snapshot=json.loads((output/'search.json').read_text(encoding='utf-8'))
        self.assertEqual((output/snapshot['training_case']).resolve(),output/'template')
        self.assertEqual((output/snapshot['engine']).resolve(),engine)
        self.assertGreater(len({json.dumps(c,sort_keys=True) for c in calls}),1)
        for c in calls:
            for clock in c:
                self.assertEqual(c[clock]['q1'],calls[0][clock]['q1'])
        self.assertIn(',TPE,',(output/'trials.csv').read_text(encoding='utf-8'))
        summary=json.loads((output/'summary.json').read_text(encoding='utf-8'))
        self.assertFalse(summary['held_out_data_used_for_selection'])
        # No date overlap can accidentally become the independent validation.
        with self.assertRaisesRegex(ValueError,'training end'):
            opt.apply_best(output,self.case,self.root/'overlap')
        future=self.root/'future'
        opt.clone_case(self.case,future)
        cfg=future/'config/Timescale.cfg'
        cfg.write_text(cfg.read_text(encoding='utf-8').replace('2026 01 01 00 00 00','2026 01 11 00 00 00'), encoding='utf-8')
        destination=self.root/'validation'
        opt.apply_best(output,future,destination)
        selected=json.loads((output/'best_parameters.json').read_text(encoding='utf-8'))
        actual=opt.read_coefficients((destination/'config/session.obj').read_text(encoding='utf-8'))
        for c in selected:
            for q in opt.FIELDS:
                self.assertAlmostEqual(actual[c][q]/selected[c][q],1)
        self.assertEqual(opt.inspect_case(destination)['start'],'2026-01-11T00:00:00')

    def test_invalid_bounds_and_no_tpe_budget_are_rejected(self):
        path=self.root/'search.json'
        opt.initialize(self.case,path)
        config=json.loads(path.read_text(encoding='utf-8'))
        info=opt.inspect_case(self.case)
        initial=opt.read_coefficients((self.case/'config/session.obj').read_text(encoding='utf-8'))
        config['trials']=config['startup_trials']
        with self.assertRaisesRegex(ValueError,'startup_trials'):
            opt.validate_search(config,initial,info)
        config['trials']=12
        spec=config['parameters'][next(iter(initial))]['q2']
        spec['min']=spec['max']
        with self.assertRaisesRegex(ValueError,'bounds'):
            opt.validate_search(config,initial,info)

    def test_phase_diffusion_can_be_enabled_without_changing_fixed_frequencies(self):
        path=self.root/'search.json'
        opt.initialize(self.case,path)
        config=json.loads(path.read_text(encoding='utf-8'))
        config.update(engine='test_runtime.exe',trials=4,startup_trials=2)
        (self.root/'test_runtime.exe').write_bytes(b'fixture - never executed')
        clock=next(iter(config['parameters']))
        for specs in config['parameters'].values():
            specs['q2']['enabled']=False
        config['parameters'][clock]['q1']['enabled']=True
        path.write_text(json.dumps(config),encoding='utf-8')
        calls=[]
        def fake_evaluate(case,engine,timeout,taus):
            values=opt.read_coefficients((case/'config/session.obj').read_text(encoding='utf-8'))
            calls.append(values)
            return {'loss':math.log10(values[clock]['q1']),'seconds':.01}
        with patch.object(opt,'input_fingerprints',return_value={}), patch.object(opt,'evaluate',side_effect=fake_evaluate):
            opt.run_search(path,self.root/'phase_search')
        self.assertGreater(len({values[clock]['q1'] for values in calls}),1)
        for values in calls:
            for other in values:
                self.assertEqual(values[other]['q2'],calls[0][other]['q2'])
                if other != clock:
                    self.assertEqual(values[other]['q1'],calls[0][other]['q1'])

    def test_shared_frequency_search_preserves_ratios_and_respects_disabled_clocks(self):
        path=self.root/'search.json'
        opt.initialize(self.case,path)
        config=json.loads(path.read_text(encoding='utf-8'))
        config.update(engine='test_runtime.exe',trials=4,startup_trials=2,shared_q2_scale=True)
        (self.root/'test_runtime.exe').write_bytes(b'fixture - never executed')
        fixed=next(iter(config['parameters']))
        config['parameters'][fixed]['q2']['enabled']=False
        path.write_text(json.dumps(config),encoding='utf-8')
        initial=opt.read_coefficients((self.case/'config/session.obj').read_text(encoding='utf-8'))
        calls=[]
        def fake_evaluate(case,engine,timeout,taus):
            values=opt.read_coefficients((case/'config/session.obj').read_text(encoding='utf-8'))
            calls.append(values)
            return {'loss':sum(math.log10(v['q2']) for v in values.values()),'seconds':.01}
        with patch.object(opt,'input_fingerprints',return_value={}), patch.object(opt,'evaluate',side_effect=fake_evaluate):
            opt.run_search(path,self.root/'shared_search')
        self.assertIn('q2_scale',(self.root/'shared_search/report.html').read_text(encoding='utf-8'))
        active=[c for c in initial if c != fixed]
        self.assertGreater(len({values[active[0]]['q2'] for values in calls}),1)
        for values in calls:
            ratios=[values[c]['q2']/initial[c]['q2'] for c in active]
            for ratio in ratios:
                self.assertAlmostEqual(ratio,ratios[0])
                self.assertGreaterEqual(ratio,.25)
                self.assertLessEqual(ratio,16)
            self.assertAlmostEqual(values[fixed]['q2']/initial[fixed]['q2'],1)
            for c in initial:
                self.assertAlmostEqual(values[c]['q1']/initial[c]['q1'],1)

    def test_shared_bounds_use_intersection_and_reject_disjoint_intervals(self):
        path=self.root/'search.json'
        opt.initialize(self.case,path)
        config=json.loads(path.read_text(encoding='utf-8'))
        config['shared_q2_scale']=True
        initial=opt.read_coefficients((self.case/'config/session.obj').read_text(encoding='utf-8'))
        first,second=list(initial)[:2]
        config['parameters'][first]['q2']['max']=initial[first]['q2']*4
        self.assertEqual(opt.search_space(config,initial),{'q2_scale':(.25,4)})
        config['parameters'][first]['q2']['max']=initial[first]['q2']
        config['parameters'][second]['q2']['min']=initial[second]['q2']
        with self.assertRaisesRegex(ValueError,'overlapping'):
            opt.validate_search(config,initial,opt.inspect_case(self.case))

    def test_failed_initial_run_is_not_a_successful_optimization(self):
        path=self.root/'search.json'
        opt.initialize(self.case,path)
        config=json.loads(path.read_text(encoding='utf-8'));config['engine']='test_runtime.exe'
        (self.root/'test_runtime.exe').write_bytes(b'fixture')
        path.write_text(json.dumps(config), encoding='utf-8')
        with patch.object(opt,'input_fingerprints',return_value={}), patch.object(opt,'evaluate',side_effect=ValueError('bad S')):
            with self.assertRaisesRegex(ValueError,'Initial configuration failed'):
                opt.run_search(path,self.root/'failed')
        self.assertFalse((self.root/'failed/best_parameters.json').exists())
        self.assertIn('FAIL',(self.root/'failed/trials.csv').read_text(encoding='utf-8'))

    def test_failed_candidates_are_kept_and_never_selected(self):
        path=self.root/'search.json'
        opt.initialize(self.case,path)
        config=json.loads(path.read_text(encoding='utf-8'));config.update(engine='test_runtime.exe',trials=4,startup_trials=2)
        (self.root/'test_runtime.exe').write_bytes(b'fixture')
        path.write_text(json.dumps(config), encoding='utf-8')
        scores=[{'loss':-12.,'seconds':.01}, ValueError('failed candidate'),
                {'loss':-11.,'seconds':.01}, {'loss':-10.,'seconds':.01}]
        with patch.object(opt,'input_fingerprints',return_value={}), patch.object(opt,'evaluate',side_effect=scores):
            opt.run_search(path,self.root/'search')
        summary=json.loads((self.root/'search/summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['best_trial'],0)
        self.assertEqual(summary['successful_trials'],3)
        import csv
        with (self.root/'search/trials.csv').open(encoding='utf-8') as stream:
            history=list(csv.DictReader(stream))
        self.assertEqual(history[1]['status'],'FAIL')
        self.assertEqual(history[2]['stage'],'random')
        self.assertEqual(history[3]['stage'],'TPE')


if __name__ == '__main__':
    unittest.main()
