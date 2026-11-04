#!/usr/bin/env python3
"""Editable membership experiments and plots for thesis Section 5.2."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import thesis_section43 as archive
from tools.run_config import configured_path, inspect_config

EXAMPLE = ROOT / 'examples/thesis-section52'
GROUPS = ('group01', 'group02', 'group04', 'group05')
SCENARIOS = ('baseline', 'csac_exit', 'mro_exit', 'csac_join', 'mro_join')
EXACT_TAUS = (10, 100, 300, 1000, 3000, 10000, 10240, 30000, 86400)
START = datetime(2026, 1, 1)
END = datetime(2026, 1, 11)
DT = 10.0


def release() -> dict:
    return json.loads((EXAMPLE / 'data-release.json').read_text(encoding='utf-8'))


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepare_case(inputs: Path, output: Path, group: str = 'group01', scenario: str = 'baseline',
                 admission: str = 'robust', gamma: float = 10000, window: float = 120,
                 event_day: float = 5, prior_profile: str = 'auto') -> None:
    if group not in GROUPS or scenario not in SCENARIOS or admission not in ('robust', 'fixed'):
        raise ValueError('Unknown group, scenario or initialization method')
    if prior_profile not in ('auto', 'original', 'scaled'):
        raise ValueError('Unknown initial-prior profile')
    if prior_profile == 'auto':
        prior_profile = 'original' if group == 'group01' else 'scaled'
    if not all(math.isfinite(v) and v > 0 for v in (gamma, window, event_day)) or event_day >= 10:
        raise ValueError('gamma/window must be positive; event-day must be between 0 and 10')
    if (event_day * 86400) % DT or window % DT:
        raise ValueError('Event time and observation window must lie on the 10-second grid')
    if output.exists():
        raise ValueError(f'Output already exists: {output}; choose a new experiment directory')
    archive.verify(inputs, 'inputs', catalog=release())
    recipe = json.loads((inputs / 'recipes' / f'{group}.json').read_text(encoding='utf-8'))[scenario]
    variant = scenario if scenario.endswith('_join') else 'base'
    base = inputs / 'groups' / group
    clk = os.path.relpath(base / f'clk/{variant}/SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK', output).replace('\\', '/')
    pfd = 'pfd'
    if any(c.isspace() for c in clk + pfd):
        raise ValueError('Use space-free relative input paths; keep inputs and experiments under the same parent')
    config = output / 'config'
    config.mkdir(parents=True)
    for name in ('file_table', 'svinf.dat', 'leap.sec', 'pan_info'):
        shutil.copyfile(inputs / 'tables' / name, config / name)
    session = recipe['session.obj']
    if prior_profile == 'scaled':
        # Scale BOTH incumbents and candidates; retain their relative prior weights.
        # Process coefficients and PFD/CLK measurements are unchanged.
        session = re.sub(r'Phase:\[[^,]+,', 'Phase:[1e-7,', session)
        session = re.sub(r'Frequency:\[[^,]+,', 'Frequency:[1e-9,', session)
    (config / 'session.obj').write_text(
        '* Phase/Frequency:[initial standard deviation,process noise coefficient]\n'
        f'* Initial-prior profile: {prior_profile}; process coefficients follow the input recipe.\n'
        + session, encoding='utf-8', newline='\n')
    event = START + timedelta(days=event_day)
    before = '0101,0102,0103,0104'
    after = {'baseline': before, 'csac_exit': '0101,0102,0103', 'mro_exit': '0101,0103,0104',
             'csac_join': before + ',0105', 'mro_join': before + ',0106'}[scenario]
    rows = [(START, END, before)] if scenario == 'baseline' else [(START, event, before), (event, END, after)]
    (config / 'membership_schedule.tsv').write_text('start_gpst\tend_gpst\tactive_prns\n' + ''.join(
        f'{a.isoformat()}\t{b.isoformat()}\t{members}\n' for a, b, members in rows), encoding='utf-8', newline='\n')
    join = scenario.endswith('_join')
    mode = 'calibrated_bounded_influence' if join and admission == 'robust' else 'legacy'
    (config / 'Timescale.cfg').write_text(f'''* Section 5.2: 10 days, 10-second samples; edit this native file directly.
 Start time&session length   = 2026 01 01 00 00 00 864000 [GPST]
 Processing interval        = 10

+File Directory
 Project directory          = results
 GNSS Sp3 full name          = not_used/orbit.SP3
 GNSS Clk full name          = {clk}
 LEO Sp3 full name           = not_used/orbit.SP3
 LEO Clk full name           = {clk}
 ISL data directory          = not_used/isl
 PFD data directory          = {pfd}
-File Directory

+Timescale Section
 Timescale scope             = satellite
 Clock Trend state num       = 2
 Clock Harmonics state num   = 0
 Rank deficiency remedy      = GREENHALL
 Estimation architecture     = centralized
 Centralized dynamic membership = {'off' if scenario == 'baseline' else 'on'}
 Centralized membership schedule = config/membership_schedule.tsv
 Centralized admission covariance initialization = {mode}
 Centralized admission observation window = {window:g}
 Centralized admission covariance inflation = {'on' if join and admission == 'fixed' else 'off'}
 Centralized admission covariance inflation scale = {gamma:g}
 SUMZERO constraint sigma    = 1e-14
-Timescale Section

+Orbit and Clock Section
 GNSS Apriori orbit          = spp
 GNSS Apriori clock          = prec
 LEO Apriori orbit           = spp
 LEO Apriori clock           = prec
-Orbit and Clock Section

+Output Section
 Clock state output flag     = 1
 Output Kalman covariance    = 0
 Log level                  = info
-Output Section
* Dynamic membership requires centralized satellite/PFD, two states and GREENHALL.
* Other experiments retain NONE / SUMZERO / BROWN / GREENHALL / KPW options.
''', encoding='utf-8', newline='\n')
    save_json(output / 'case.json', {'group': group, 'scenario': scenario,
        'inputs': os.path.relpath(inputs, output).replace('\\', '/'),
        'note': 'Edit native config files; analysis reads the actual configuration and membership events.'})
    sync_observations(output)
    print(f'Prepared {output} (initial priors: {prior_profile}). Edit config files; run the engine from this directory.')


def fields(path: Path) -> dict[str, str]:
    return {line.split('=', 1)[0].strip(): line.split('=', 1)[1].split('!', 1)[0].strip()
            for line in path.read_text(encoding='utf-8-sig').splitlines()
            if line.startswith(' ') and '=' in line}


def read_schedule(path: Path, start: datetime, end: datetime) -> list[tuple]:
    import csv
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != ['start_gpst', 'end_gpst', 'active_prns']:
            raise ValueError('Schedule needs three TAB-separated columns: start_gpst, end_gpst, active_prns')
        rows = []
        cursor = start
        for row in reader:
            first, last = datetime.fromisoformat(row['start_gpst']), datetime.fromisoformat(row['end_gpst'])
            members = row['active_prns'].split(',')
            if (first != cursor or last <= first or last > end or
                    (first-start).total_seconds() % DT or (last-start).total_seconds() % DT or
                    len(members) < 2 or len(set(members)) != len(members) or
                    any(not re.fullmatch(r'\d{4}', p) for p in members)):
                raise ValueError('Schedule must be continuous, ordered, on the 10-second grid, with distinct four-digit PRNs')
            rows.append((first, last, set(members)))
            cursor = last
    if cursor != end or not rows:
        raise ValueError('Schedule must cover the entire configured run')
    return rows


def sync_observations(case: Path) -> Path:
    """Select existing PFD rows by the edited membership schedule; never change a measurement."""
    metadata = json.loads((case / 'case.json').read_text(encoding='utf-8'))
    info = inspect_config(case / 'config/file_table', case)
    config_path = Path(info['tables']['TimescaleCfg'])
    cfg = fields(config_path)
    start, end = datetime.fromisoformat(info['start']), datetime.fromisoformat(info['end'])
    if start < START or end > END or info['interval_s'] != DT:
        raise ValueError('The provided observations cover 2026-01-01 through 2026-01-10, at 10 seconds')
    schedule = read_schedule(configured_path(cfg['Centralized membership schedule'], case), start, end)
    scenario = metadata['scenario']
    variant = scenario if scenario.endswith('_join') else 'base'
    inputs = (case / metadata['inputs']).resolve()
    pool = inputs / 'groups' / metadata['group'] / 'pfd' / variant
    allowed = {'0101', '0102', '0103', '0104'} | ({'0105'} if variant == 'csac_join' else {'0106'} if variant == 'mro_join' else set())
    if any(not members <= allowed for _, _, members in schedule):
        raise ValueError('The selected CLK/PFD variant does not contain a scheduled member')
    selected = []
    for path in sorted(pool.glob('*.txt')):
        match = re.fullmatch(r'(\d{4})_(\d{4})_(\d{4})(\d{3})\.txt', path.name)
        if not match:
            raise ValueError('Unexpected PFD filename')
        left, right, year, doy = match.groups()
        day = datetime(int(year), 1, 1) + timedelta(days=int(doy)-1)
        intervals = [(max(a, day), min(b, day+timedelta(days=1))) for a, b, members in schedule
                     if left in members and right in members and a < day+timedelta(days=1) and b > day]
        if intervals:
            selected.append((path, day, intervals))
    if not selected:
        raise ValueError('No matching observations for this schedule')
    # Keep prior observations for comparison when the user edits the schedule again.
    destination = case / 'pfd'
    revision = 2
    while destination.exists():
        destination = case / f'pfd_revision{revision}'
        revision += 1
    destination.mkdir()
    for path, day, intervals in selected:
        if any(a == day and b == day+timedelta(days=1) for a, b in intervals):
            shutil.copyfile(path, destination / path.name)
        else:
            with path.open(encoding='utf-8') as src, (destination / path.name).open('w', encoding='utf-8', newline='\n') as dst:
                for line in src:
                    parts = line.split()
                    epoch = datetime(1858, 11, 17) + timedelta(days=int(parts[0]), seconds=float(parts[1]))
                    if any(a <= epoch < b for a, b in intervals):
                        dst.write(line)
    text = config_path.read_text(encoding='utf-8')
    text, count = re.subn(r'(?m)^([ \t]+PFD data directory[ \t]*=)[^\r\n]*',
                         lambda match: match[1]+' '+destination.relative_to(case).as_posix(), text)
    if count != 1:
        raise ValueError('Expected one PFD data directory field')
    config_path.write_text(text, encoding='utf-8', newline='\n')
    print(f'Selected {len(selected)} PFD files from the schedule: {destination}')
    return destination


def load_case(case: Path) -> dict:
    import numpy as np
    import pandas as pd
    from tools.plot_results import read_epochs
    from tools.dataprocess_snapshot.helpers import load_iem_to_standard_dict

    metadata = json.loads((case / 'case.json').read_text(encoding='utf-8'))
    info = inspect_config(case / 'config/file_table', case)
    cfg = fields(Path(info['tables']['TimescaleCfg']))
    results = Path(info['result_dir'])
    log = (results / 'gstar.log').read_text(encoding='utf-8', errors='replace')
    if re.search(r'\[(?:error|critical)\]|(?:\*{3}|#{3})\s*error|terminate called', log, re.I) or 'runs successfully' not in log:
        raise ValueError(f'Run did not complete successfully: {case}')
    times = read_epochs(results / 'IEM.txt')
    phase = load_iem_to_standard_dict(str(results / 'IEM.txt'))[0]['Ensemble']
    expected = np.arange(np.datetime64(info['start']) + np.timedelta64(30, 's'),
                         np.datetime64(info['end']), np.timedelta64(10, 's'))
    if info['interval_s'] != DT or not np.array_equal(times, expected) or not np.isfinite(phase).all():
        raise ValueError(f'Incomplete, nonfinite or non-10-second output: {case}')
    scenario = metadata['scenario']
    label = scenario
    event = joint = active = None
    if scenario != 'baseline':
        schedule = pd.read_csv(configured_path(cfg['Centralized membership schedule'], case), sep='\t')
        if len(schedule) != 2:
            raise ValueError('This comparison expects one membership event per experiment')
        event = str(schedule.iloc[1].start_gpst)
        events = pd.read_csv(results / 'centralized_membership_events.tsv', sep='\t', dtype=str).fillna('')
        if len(events) != 1:
            raise ValueError(f'Expected one actual membership change: {case}')
        joint = events.iloc[0].event_gpst
        if scenario.endswith('_join'):
            if events.iloc[0].state_dim_before != '8' or events.iloc[0].state_dim_after != '10':
                raise ValueError('Joining case did not enter the five-clock filter')
            mode = cfg.get('Centralized admission covariance initialization', 'legacy')
            if mode == 'calibrated_bounded_influence':
                label = scenario.replace('_join', '_robust')
                diag = pd.read_csv(results / 'centralized_calibrated_bounded_influence.tsv', sep='\t')
                ready = diag.loc[diag.lifecycle == 'ACTIVE']
                if ready.empty or ready.iloc[0].eta != 1:
                    raise ValueError(f'Candidate never reached ACTIVE: {case}')
                active = str(ready.iloc[0].event_gpst)
            elif mode == 'legacy' and cfg.get('Centralized admission covariance inflation') == 'on':
                gamma = float(cfg['Centralized admission covariance inflation scale'])
                label = scenario.replace('_join', f'_fixed{gamma:g}')
                active = joint
            else:
                raise ValueError('Use fixed covariance or calibrated_bounded_influence for this comparison')
        elif events.iloc[0].state_dim_before != '8' or events.iloc[0].state_dim_after != '6':
            raise ValueError('Exit case did not enter the three-clock filter')
    return {'label': label, 'times': times, 'phase': phase, 'group': metadata['group'], 'event': event,
            'joint': joint, 'active': active, 'inputs': (case / metadata['inputs']).resolve(),
            'clock_pattern': info['inputs']['LEO Clk full name'],
            'iem_sha256': archive.sha256(results / 'IEM.txt')}


def read_member_clocks(inputs: Path, group: str, times, patterns: dict | None = None):
    """Read actual RINEX CLK values, including the not-yet-admitted candidate clocks."""
    import numpy as np
    import pandas as pd

    result = {}
    for variant, selected in [('base', (101, 102, 103, 104)), ('csac_join', (105,)), ('mro_join', (106,))]:
        frames = []
        pattern = Path(patterns[variant]) if patterns and variant in patterns else (
            inputs / 'groups' / group / 'clk' / variant / 'SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK')
        paths = sorted(pattern.parent.glob(pattern.name.replace('-YEARDOY-', '*')))
        if not paths:
            raise ValueError(f'No CLK files match {pattern}')
        for path in paths:
            with path.open(encoding='utf-8') as stream:
                for skip, line in enumerate(stream, 1):
                    if 'END OF HEADER' in line:
                        break
                else:
                    raise ValueError(f'Missing CLK header: {path}')
            frame = pd.read_csv(path, sep=r'\s+', skiprows=skip, header=None,
                                usecols=[1, 2, 3, 4, 5, 6, 7, 9],
                                names=['prn', 'year', 'month', 'day', 'hour', 'minute', 'second', 'phase'])
            frame['time'] = pd.to_datetime(frame[['year', 'month', 'day', 'hour', 'minute', 'second']])
            frames.append(frame)
        full = pd.concat(frames, ignore_index=True)
        for prn in selected:
            part = full.loc[full.prn == prn].set_index('time')['phase']
            if part.index.has_duplicates:
                raise ValueError('Duplicate raw clock epoch')
            values = part.reindex(pd.DatetimeIndex(times)).to_numpy()
            if not np.isfinite(values).all():
                raise ValueError('Raw CLK does not cover the comparison interval')
            result[f'clock_{prn:04d}_s'] = values
    return result


def transient_metrics(times, baseline, dynamic, joint: str) -> dict:
    import numpy as np
    index = int(np.searchsorted(times, np.datetime64(joint)))
    if index < 2 or index >= len(times) or times[index] != np.datetime64(joint):
        raise ValueError('Joint-entry epoch needs two preceding samples')
    residual = dynamic - baseline
    return {'phase_jump_s': float(residual[index] - residual[index-1]),
            # Thesis Eq. (5.21): y[k] - y[k-1], y[k] = (e[k]-e[k-1])/DT.
            'frequency_jump': float(((residual[index] - residual[index-1]) -
                                     (residual[index-1] - residual[index-2])) / DT)}


def analyze_cases(cases: Path, output: Path, group: str = 'group01') -> None:
    import numpy as np
    loaded = [load_case(p.parent) for p in sorted(cases.glob('*/case.json'))
              if json.loads(p.read_text(encoding='utf-8'))['group'] == group]
    by_name = {record['label']: record for record in loaded}
    if len(by_name) != len(loaded) or 'baseline' not in by_name or len(loaded) < 2:
        raise ValueError('Need one baseline and distinct completed comparison cases for this group')
    baseline = by_name['baseline']
    event_times = {r['event'] for r in loaded if r['event'] is not None}
    if len(event_times) != 1:
        raise ValueError('All compared scenarios must have the same scheduled event time')
    for record in loaded:
        if not np.array_equal(record['times'], baseline['times']) or record['inputs'] != baseline['inputs']:
            raise ValueError('Comparison cases must use the same input package and actual epochs')
    patterns = {'base': baseline['clock_pattern']}
    for kind in ('csac', 'mro'):
        matching = [r['clock_pattern'] for r in loaded if r['label'].startswith(kind+'_') and not r['label'].endswith('_exit')]
        if matching:
            if len(set(matching)) != 1:
                raise ValueError('Initialization comparisons must use the same candidate CLK input')
            patterns[kind+'_join'] = matching[0]
    raw = read_member_clocks(baseline['inputs'], group, baseline['times'], patterns)
    # The same group label alone does not prove that the four input clocks match.
    for pattern in set(r['clock_pattern'] for r in loaded) - {baseline['clock_pattern']}:
        check = read_member_clocks(baseline['inputs'], group, baseline['times'], {**patterns, 'base': pattern})
        if any(not np.array_equal(raw[f'clock_{prn:04d}_s'], check[f'clock_{prn:04d}_s']) for prn in (101, 102, 103, 104)):
            raise ValueError('The four incumbent input clocks differ; this is not a valid membership comparison')
    provenance = [{k: v for k, v in record.items() if k in ('label', 'joint', 'active', 'iem_sha256')}
                  for record in loaded]
    make_report(baseline['times'], {r['label']: r['phase'] for r in loaded}, raw,
                provenance, next(iter(event_times)), output, group, 'new native runs')


def analyze_archive(data: Path, output: Path) -> None:
    import numpy as np
    import pandas as pd
    archive.verify(data, 'analysis', catalog=release())
    frame = pd.read_csv(data / 'ensemble_phases.csv', float_precision='round_trip')
    raw = pd.read_csv(data / 'member_clocks.csv', float_precision='round_trip')
    if not np.array_equal(frame.time_s, np.arange(30, 864000, 10)) or not np.array_equal(raw.time_s, np.arange(0, 864000, 10)):
        raise ValueError('Invalid archived time grid')
    records = json.loads((data / 'source_provenance.json').read_text(encoding='utf-8'))
    provenance = [{'label': r['case'], 'joint': r.get('joint_start_gpst', '2026-01-06T00:00:00'),
                   'active': r.get('active_gpst', '2026-01-06T00:00:00'), 'iem_sha256': r['iem_sha256']} for r in records]
    times = np.datetime64(START) + frame.time_s.to_numpy(dtype='timedelta64[s]')
    make_report(times, {c: frame[c].to_numpy() for c in frame if c != 'time_s'},
                {c: raw[c].to_numpy()[3:] for c in raw if c != 'time_s'}, provenance,
                '2026-01-06T00:00:00', output, 'group01', 'archived phase data')


def summarize_events(reports: list[Path], output: Path) -> None:
    """Average absolute event disturbances over the same four clock groups."""
    import numpy as np
    import pandas as pd
    records = [json.loads((path / 'validation.json').read_text(encoding='utf-8')) for path in reports]
    if len(records) != len(GROUPS) or {r['group'] for r in records} != set(GROUPS):
        raise ValueError('Provide each of group01/group02/group04/group05 exactly once')
    if len({r['event_gpst'] for r in records}) != 1 or len({r['interval_s'] for r in records}) != 1:
        raise ValueError('Groups must use the same scheduled event and sampling interval')
    per_group = {r['group']: {row['case']: row for row in r['transients']
                            if not row['case'].endswith('_exit')} for r in records}
    common = set.intersection(*(set(v) for v in per_group.values()))
    if not common:
        raise ValueError('No common completed joining methods across all four groups')
    details = []
    for group, methods in per_group.items():
        for name in sorted(common):
            row = methods[name]
            values = [row['phase_jump_s'], row['frequency_jump']]
            if not np.isfinite(values).all():
                raise ValueError('Event disturbances must be finite')
            details.append({'group': group, 'case': name, 'abs_phase_jump_ns': abs(values[0])*1e9,
                            'abs_frequency_jump': abs(values[1])})
    frame = pd.DataFrame(details)
    mean = frame.groupby('case', sort=True).agg(groups=('group', 'nunique'),
        mean_abs_phase_jump_ns=('abs_phase_jump_ns', 'mean'),
        mean_abs_frequency_jump=('abs_frequency_jump', 'mean')).reset_index()
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    output.mkdir(parents=True)
    frame.to_csv(output / 'events_by_group.tsv', sep='\t', index=False, float_format='%.17e')
    mean.to_csv(output / 'table5_1_event_summary.tsv', sep='\t', index=False, float_format='%.17e')
    save_json(output / 'summary.json', {'groups': list(GROUPS), 'statistic': 'mean of absolute per-group jumps',
                                      'methods_present_in_all_groups': sorted(common), 'rows': mean.to_dict('records')})
    (output / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>四组接入扰动</title>'
        '<h1>四组接入扰动</h1><p>先取各组跳变的绝对值，再求四组平均。只比较四组都已完成的方法。'
        '频率跳变按论文公式 (5.21) 计算。</p>' + mean.to_html(index=False), encoding='utf-8')
    print(f'Created {output / "table5_1_event_summary.tsv"}')


def make_report(times, phases: dict, raw: dict, provenance: list[dict], event: str,
                output: Path, group: str, source: str) -> None:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    if any(len(v) != len(times) or not np.isfinite(v).all() for v in [*phases.values(), *raw.values()]):
        raise ValueError('Invalid phases in comparison')
    figures, tables = output / 'figures', output / 'tables'
    figures.mkdir(parents=True)
    tables.mkdir()
    records = {r['label']: r for r in provenance}
    baseline = phases['baseline']
    event_epoch = np.datetime64(event)
    hours = (times - event_epoch) / np.timedelta64(1, 's') / 3600
    days = (times - np.datetime64(START)) / np.timedelta64(1, 's') / 86400
    post_exit = times >= event_epoch
    ready = [np.datetime64(r['active']) for r in provenance if r['label'].endswith('_robust')]
    post_start = max([event_epoch, *ready]) + np.timedelta64(10, 's')
    post_join = times >= post_start
    masks = {'full': np.ones(len(times), dtype=bool), 'post_event': post_exit, 'post_active': post_join}
    curves, exact_rows, metrics = {}, [], []
    all_series = {**raw, **phases}
    for segment, mask in masks.items():
        if mask.sum() < 12:
            raise ValueError(f'Insufficient samples for {segment}')
        for name, values in all_series.items():
            tau, sigma, _, _ = archive.adev(values[mask])
            curves[segment, name] = tau, sigma
            t, a, e, n = archive.adev(values[mask], EXACT_TAUS)
            exact_rows.extend((segment, name, float(tt), float(aa), float(ee), int(nn), int(mask.sum()))
                              for tt, aa, ee, nn in zip(t, a, e, n))
    for name, values in phases.items():
        if name == 'baseline':
            continue
        record = records[name]
        before = times < event_epoch
        metrics.append({'case': name, 'event_gpst': event, 'joint_gpst': record['joint'],
                        'active_gpst': record['active'],
                        'pre_event_max_difference_s': float(np.max(np.abs(values[before]-baseline[before]))),
                        **transient_metrics(times, baseline, values, record['joint'])})
    exact = pd.DataFrame(exact_rows, columns=['segment', 'series', 'tau_s', 'adev', 'adev_error', 'terms', 'phase_samples'])
    exact.to_csv(tables / 'adev_exact.tsv', sep='\t', index=False, float_format='%.17e')
    pd.DataFrame(metrics).to_csv(tables / 'event_metrics.tsv', sep='\t', index=False, float_format='%.17e')
    comparisons = []
    for row in exact.loc[exact.series.isin(phases) & (exact.series != 'baseline')].itertuples():
        base = exact.loc[(exact.segment == row.segment) & (exact.series == 'baseline') & (exact.tau_s == row.tau_s)]
        value = float(base.iloc[0].adev)
        comparisons.append({'segment': row.segment, 'case': row.series, 'tau_s': row.tau_s,
                            'baseline_adev': value, 'case_adev': row.adev, 'reduction_percent': 100*(1-row.adev/value)})
    pd.DataFrame(comparisons).to_csv(tables / 'improvement.tsv', sep='\t', index=False, float_format='%.17e')
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'svg.fonttype': 'none'})
    colors = {'baseline': '#202d3b', 'robust': '#007e87', 'exit': '#b54838'}
    fixed_colors = ['#ce5777', '#e08b39', '#9174b5', '#658cc0', '#b22222']
    fixed_names = sorted({n.split('_fixed')[1] for n in phases if '_fixed' in n}, key=float)

    def style(name):
        if name == 'baseline': return {'color': colors['baseline'], 'linestyle': '--', 'linewidth': 1.8}
        if name.endswith('robust'): return {'color': colors['robust'], 'linewidth': 1.8}
        if name.endswith('exit'): return {'color': colors['exit'], 'linewidth': 1.5}
        return {'color': fixed_colors[fixed_names.index(name.split('_fixed')[1]) % len(fixed_colors)], 'linewidth': 1.1}

    def label(name):
        if name == 'baseline': return 'Static 4 clocks'
        if name.endswith('robust'): return 'Short-window initialization'
        if name.endswith('exit'): return 'After clock exit'
        return 'Fixed gamma=' + name.split('_fixed')[1]

    generated = []

    def finish(fig, name):
        fig.tight_layout()
        for ext in ('png', 'svg', 'pdf'):
            fig.savefig(figures / f'{name}.{ext}', dpi=160)
        plt.close(fig)
        generated.append(name)

    def adev_axes(ax, title):
        ax.set(title=title, xlabel='Averaging time (s)', ylabel='ADEV')
        ax.grid(True, which='both', alpha=.22)

    fig, ax = plt.subplots(figsize=(9, 5))
    for name in raw:
        prn = name.split('_')[1]
        kind = 'mRO' if prn in ('0101', '0102', '0106') else 'CSAC'
        ax.loglog(*curves['full', name], '--', alpha=.75, label=f'{prn} {kind}')
    ax.loglog(*curves['full', 'baseline'], label=label('baseline'), **style('baseline'))
    adev_axes(ax, f'{group}: member clocks and static timescale')
    ax.legend(fontsize=8, ncol=2)
    finish(fig, 'member_clocks_adev')

    exits = [k for k in ('csac', 'mro') if f'{k}_exit' in phases]
    if exits:
        fig, axes = plt.subplots(2, len(exits), figsize=(5.4*len(exits), 6.5), squeeze=False)
        mask = (hours >= -6) & (hours <= 24)
        for col, kind in enumerate(exits):
            for name in ('baseline', f'{kind}_exit'):
                frequency = np.r_[np.nan, np.diff(phases[name])/DT]
                axes[0, col].plot(hours[mask], phases[name][mask]*1e6, label=label(name), **style(name))
                axes[1, col].plot(hours[mask], frequency[mask]*1e10, **style(name))
            axes[0, col].set(title=f'{kind.upper()} exits: 4 to 3 clocks', ylabel='Phase (us)')
            axes[0, col].legend(fontsize=8)
            axes[1, col].set(xlabel='Hours from scheduled exit', ylabel='Fractional frequency / 1e-10')
            for ax in axes[:, col]:
                ax.axvline(0, color='gray', linestyle=':'); ax.grid(alpha=.22)
        finish(fig, 'fig5_2_exit_response')
        fig, axes = plt.subplots(1, len(exits), figsize=(5.4*len(exits), 4.5), squeeze=False)
        for ax, kind in zip(axes.flat, exits):
            for name in ('baseline', f'{kind}_exit'):
                ax.loglog(*curves['post_event', name], label=label(name), **style(name))
            adev_axes(ax, f'{kind.upper()} exits: post-event ADEV')
            ax.legend(fontsize=8)
        finish(fig, 'fig5_3_exit_adev')

    joins = [k for k in ('csac', 'mro') if any(n.startswith(k+'_') and not n.endswith('exit') for n in phases)]
    for kind, figure_number in [('csac', 4), ('mro', 5)]:
        if kind not in joins: continue
        names = ['baseline'] + [n for n in phases if n.startswith(kind+'_') and not n.endswith('exit')]
        fig, axes = plt.subplots(2, 2, figsize=(11, 6.5))
        near = (hours >= -.1) & (hours <= 1)
        for name in names:
            values = phases[name]
            frequency = np.r_[np.nan, np.diff(values)/DT]
            residual = values-baseline
            axes[0, 0].plot(days, values*1e6, label=label(name), **style(name))
            axes[1, 0].plot(days, frequency*1e10, **style(name))
            if name == 'baseline' or name.endswith('_robust') or ('_fixed' in name and float(name.split('_fixed')[1]) >= 1000):
                axes[0, 1].plot(hours[near]*60, residual[near]*1e9, label=label(name), **style(name))
                axes[1, 1].plot(hours[near]*60, np.r_[np.nan, np.diff(residual)/DT][near], **style(name))
        axes[0, 0].set(title=f'New {kind.upper()}: full 10 days', ylabel='Phase (us)')
        axes[1, 0].set(xlabel='Days from start', ylabel='Fractional frequency / 1e-10')
        axes[0, 1].set(title='Smaller transients: difference from baseline', ylabel='Phase difference (ns)')
        axes[1, 1].set(xlabel='Minutes from scheduled join', ylabel='Frequency difference')
        axes[0, 0].legend(fontsize=7, ncol=2)
        axes[0, 1].legend(fontsize=7)
        for col in range(2):
            for ax in axes[:, col]:
                ax.axvline(float((event_epoch-np.datetime64(START))/np.timedelta64(1,'s')/86400) if col==0 else 0,
                           color='gray', linestyle=':')
                ax.grid(alpha=.22)
        finish(fig, f'fig5_{figure_number}_{kind}_join_response')
    if joins:
        fig, axes = plt.subplots(2, len(joins), figsize=(5.4*len(joins), 8), squeeze=False)
        for col, kind in enumerate(joins):
            names = ['baseline'] + [n for n in phases if n.startswith(kind+'_') and not n.endswith('exit')]
            for row, segment in enumerate(('full', 'post_event')):
                ax = axes[row, col]
                for name in names:
                    ax.loglog(*curves[segment, name], label=label(name), **style(name))
                adev_axes(ax, f'{kind.upper()}: {"full 10 days" if row==0 else "common post-event interval"}')
                ax.legend(fontsize=7)
        finish(fig, 'fig5_6_join_adev')

    summary = {'group': group, 'source': source, 'samples': len(times), 'interval_s': DT,
               'event_gpst': event, 'post_event_start': str(event_epoch),
               'post_active_start': str(post_start), 'cases': provenance,
               'transients': metrics, 'adev_comparisons': comparisons}
    save_json(output / 'validation.json', summary)
    intro = ('先看退出/接入时刻的相位与频率，再看 ADEV。全时段包含接入扰动；事件后采用所有方法共有的时间段。'
             'ADEV 越低越稳定；改善率为正表示相对静态四钟更好。频率由相位的一阶差分计算。')
    (output / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>第5.2节成员变化实验</title>'
        '<style>body{font:16px/1.65 system-ui;max-width:1100px;margin:36px auto;padding:0 20px;color:#233342}'
        'img{max-width:100%}table{border-collapse:collapse;font-size:13px}td,th{padding:6px;border:1px solid #cbd5df}</style>'
        f'<h1>第5.2节：成员钟退出与加入</h1><p>{intro}</p>'
        f'<p>组别：{html.escape(group)}；数据：{html.escape(source)}；图中的事件后区间从 {html.escape(str(event_epoch))} 开始。'
        f'数值表另外保留从 {html.escape(str(post_start))} 开始的完全接入后区间（post_active）。</p>'
        '<p>数值文件：<a href="tables/adev_exact.tsv">ADEV</a> · <a href="tables/improvement.tsv">改善率</a> · '
        '<a href="tables/event_metrics.tsv">事件扰动</a>。相位跳变在实际进入联合滤波的时刻计算。</p>'
        + ''.join(f'<h2>{html.escape(n)}</h2><img src="figures/{n}.svg">' for n in generated)
        + '<h2>事件记录</h2>' + pd.DataFrame(metrics).to_html(index=False), encoding='utf-8')
    print(f'Created {output / "report.html"}; exact ADEV and event metrics are in tables/.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch')
    fetch.add_argument('--kind', choices=['inputs', 'analysis'], default='inputs')
    fetch.add_argument('--output', type=Path, required=True)
    fetch.add_argument('--archive', type=Path)
    prepare = commands.add_parser('prepare-case')
    prepare.add_argument('--inputs', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--group', choices=GROUPS, default='group01')
    prepare.add_argument('--scenario', choices=SCENARIOS, default='baseline')
    prepare.add_argument('--admission', choices=['robust', 'fixed'], default='robust')
    prepare.add_argument('--gamma', type=float, default=10000)
    prepare.add_argument('--window', type=float, default=120)
    prepare.add_argument('--event-day', type=float, default=5)
    prepare.add_argument('--prior-profile', choices=['auto', 'original', 'scaled'], default='auto',
                         help='auto: original for group01, scaled initial uncertainties for the other groups')
    analyze = commands.add_parser('analyze')
    analyze.add_argument('--cases', type=Path, required=True)
    analyze.add_argument('--output', type=Path, required=True)
    analyze.add_argument('--group', choices=GROUPS, default='group01')
    sync = commands.add_parser('sync-pfd')
    sync.add_argument('--case', type=Path, required=True)
    summary = commands.add_parser('summarize-events')
    summary.add_argument('--reports', type=Path, nargs='+', required=True)
    summary.add_argument('--output', type=Path, required=True)
    old = commands.add_parser('analyze-archive')
    old.add_argument('--data', type=Path, required=True)
    old.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'fetch':
            archive.fetch(args.kind, args.output.resolve(), args.archive, catalog=release())
        elif args.command == 'prepare-case':
            prepare_case(args.inputs.resolve(), args.output.resolve(), args.group, args.scenario,
                         args.admission, args.gamma, args.window, args.event_day, args.prior_profile)
        elif args.command == 'analyze':
            analyze_cases(args.cases.resolve(), args.output.resolve(), args.group)
        elif args.command == 'sync-pfd':
            sync_observations(args.case.resolve())
        elif args.command == 'summarize-events':
            summarize_events([p.resolve() for p in args.reports], args.output.resolve())
        else:
            analyze_archive(args.data.resolve(), args.output.resolve())
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
