"""Editable diffusion coefficients -> actual GSTAR runs -> TPE search -> held-out case."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.run_config import inspect_config
from tools.thesis_section43 import sha256

FIELDS = {'q1': 'Phase', 'q2': 'Frequency'}
TABLES = {'TimescaleCfg': 'Timescale.cfg', 'object': 'session.obj',
          'satinf': 'svinf.dat', 'leapsc': 'leap.sec', 'paninf': 'pan_info'}
ERRORS = re.compile(r'\[(?:error|critical|fatal)\]|(?:\*{3}|#{3})\s*error|\b(?:fatal|exception|nan|inf)\b', re.I)


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def positive(value) -> float:
    if isinstance(value, bool):
        raise ValueError('Use a number, not true/false, for a coefficient')
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Coefficients and bounds must be positive finite numbers')
    return value


def clock_rows(content: str):
    inside = False
    for index, line in enumerate(content.splitlines(keepends=True)):
        if line.startswith('+LEO used'):
            inside = True
        elif line.startswith('-LEO used'):
            inside = False
        elif inside and line.startswith(' ') and line.strip() and not line.lstrip().startswith('*'):
            tokens = line.split()
            if len(tokens) < 9 or tokens[6] != 'P':
                raise ValueError('This tutorial optimizer expects satellite clocks with OBS P')
            yield index, tokens[1], line


def read_coefficients(content: str) -> dict:
    clocks = {}
    for _, clock, line in clock_rows(content):
        if clock in clocks:
            raise ValueError(f'Duplicate clock: {clock}')
        values = {}
        for q, field in FIELDS.items():
            match = re.search(r'\b' + field + r':\[([^,]+),([^\]]+)\]', line)
            if not match:
                raise ValueError(f'Missing {field} for clock {clock}')
            sigma = positive(match[2])
            values[q] = positive(sigma * sigma)
        clocks[clock] = values
    if not clocks:
        raise ValueError('No active PFD clocks found in session.obj')
    return clocks


def patch_coefficients(content: str, coefficients: dict) -> str:
    """q is the diffusion variance coefficient; native config takes sqrt(q)."""
    if set(coefficients) != set(read_coefficients(content)):
        raise ValueError('Parameter clock IDs must match the session exactly')
    lines = content.splitlines(keepends=True)
    for index, clock, line in clock_rows(content):
        if set(coefficients[clock]) != set(FIELDS):
            raise ValueError('Each clock must have q1 and q2')
        for q, field in FIELDS.items():
            sigma = math.sqrt(positive(coefficients[clock][q]))
            line, count = re.subn(r'(\b' + field + r':\[[^,]+,)[^\]]+(\])',
                                 lambda m: m[1] + f'{sigma:.17e}' + m[2], line)
            if count != 1:
                raise ValueError(f'Expected exactly one {field} for {clock}')
        # If a user kept the legacy alias, update its process term consistently.
        line = re.sub(r'(\bTotalPhase:\[[^,]+,)[^\]]+(\])',
                      lambda m: m[1] + f'{math.sqrt(coefficients[clock]["q1"]):.17e}' + m[2], line)
        lines[index] = line
    return ''.join(lines)


def inspect_case(case: Path) -> dict:
    info = inspect_config(Path('config/file_table'), case)
    if (info['scope'], info['architecture'], info['trend_states'], info['harmonic_states'], info['time_frame']) != (
            'satellite', 'centralized', '2', '0', 'GPST'):
        raise ValueError('This optimizer supports centralized satellite/PFD, two states, no harmonics, GPST')
    if set(info['tables']) != set(TABLES):
        raise ValueError('Use the five native file_table entries from the tutorial')
    return info


def relative(path: Path, base: Path, *, native: bool = True) -> str:
    try:
        result = os.path.relpath(path, base).replace('\\', '/')
    except ValueError:  # Windows source and destination can be on different drives.
        result = path.as_posix()
    if native and any(c.isspace() for c in result):
        raise ValueError('Native relative paths must not contain spaces')
    return result


def clone_case(source: Path, target: Path, coefficients: dict | None = None) -> dict:
    info = inspect_case(source)
    if target.exists():
        raise ValueError(f'Output already exists: {target}')
    content = Path(info['tables']['TimescaleCfg']).read_text(encoding='utf-8-sig')
    replacements = {key: relative(Path(value), target) for key, value in info['inputs'].items()}
    replacements['Project directory'] = 'results'
    for key, value in replacements.items():
        content, count = re.subn(r'(?m)^([ \t]*' + re.escape(key) + r'[ \t]*=).*$',
                                lambda m: m[1] + ' ' + value, content)
        if count != 1:
            raise ValueError(f'Expected one configuration field: {key}')
    session = Path(info['tables']['object']).read_text(encoding='utf-8-sig')
    if coefficients is not None:
        session = patch_coefficients(session, coefficients)
    (target / 'config').mkdir(parents=True)
    for key, name in TABLES.items():
        destination = target / 'config' / name
        if key == 'TimescaleCfg':
            destination.write_text(content, encoding='utf-8')
        elif key == 'object':
            destination.write_text(session, encoding='utf-8')
        else:
            shutil.copyfile(info['tables'][key], destination)
    (target / 'config/file_table').write_text('+FileTable\n' + ''.join(
        f' {key} config/{name}\n' for key, name in TABLES.items()) + '-FileTable\n', encoding='utf-8')
    return inspect_case(target)


def initialize(case: Path, output: Path) -> None:
    info = inspect_case(case)
    clocks = read_coefficients(Path(info['tables']['object']).read_text(encoding='utf-8'))
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    parameters = {clock: {q: {'enabled': True, 'min': value*(.25 if q == 'q1' else .1),
                              'max': value*(4 if q == 'q1' else 100)} for q, value in values.items()}
                  for clock, values in clocks.items()}
    output.parent.mkdir(parents=True, exist_ok=True)
    save_json(output, {'training_case': relative(case, output.parent, native=False),
        'engine': relative(ROOT / 'engine/GstarTimescale.exe', output.parent, native=False),
        'trials': 12, 'startup_trials': 4, 'seed': 42, 'timeout_seconds': 1800,
        'objective_taus_s': [300, 1000, 3000], 'parameters': parameters})
    print(f'Created {output}. Edit q bounds, enabled flags, taus and trial count, then run the search.')


def validate_search(config: dict, initial: dict, info: dict) -> None:
    for key in ('trials', 'startup_trials', 'seed'):
        if type(config[key]) is not int:
            raise ValueError(f'{key} must be an integer')
    if not 2 <= config['startup_trials'] < config['trials']:
        raise ValueError('Need 2 <= startup_trials < trials so actual TPE trials are included')
    positive(config['timeout_seconds'])
    taus = config['objective_taus_s']
    if not taus or len(set(taus)) != len(taus):
        raise ValueError('Specify distinct objective taus')
    for tau in taus:
        if isinstance(tau, bool) or not isinstance(tau, (int, float)):
            raise ValueError('Objective taus must be numbers in seconds')
        tau = positive(tau)
        if not math.isclose(tau / info['interval_s'], round(tau / info['interval_s'])) or tau*3 >= info['duration_s']:
            raise ValueError('Each objective tau must be a sample-interval multiple and fit at least three times in the training window')
    if set(config['parameters']) != set(initial):
        raise ValueError('Search parameter IDs differ from the training clocks')
    active = 0
    for clock, qs in config['parameters'].items():
        if set(qs) != set(FIELDS):
            raise ValueError('Each clock must define q1 and q2')
        for q, spec in qs.items():
            if type(spec['enabled']) is not bool:
                raise ValueError('enabled must be true or false')
            if not spec['enabled']:
                continue
            low, high = positive(spec['min']), positive(spec['max'])
            if not low < high or not low <= initial[clock][q] <= high:
                raise ValueError(f'{clock}.{q}: bounds must contain the initial coefficient')
            active += 1
    if not active:
        raise ValueError('Enable at least one diffusion coefficient')


def input_fingerprints(info: dict) -> dict:
    """Only the configured training dates are enumerated; holdout results are never read."""
    files = set()
    day = datetime.fromisoformat(info['start']).replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.fromisoformat(info['end'])
    while day < end:
        stamp = day.strftime('%Y%j')
        clk = Path(info['inputs']['LEO Clk full name'].replace('-YEARDOY-', stamp))
        links = list(Path(info['inputs']['PFD data directory']).glob(f'*_{stamp}.txt'))
        if not clk.is_file() or not links:
            raise ValueError(f'Missing CLK/PFD training data for {stamp}')
        files.add(clk)
        files.update(links)
        day += timedelta(days=1)
    return {str(path): sha256(path) for path in sorted(files)}


def score_phase(phase, interval: float, taus: list) -> tuple[float, list]:
    import allantools
    import numpy as np
    t, sigma, error, count = allantools.adev(phase, data_type='phase', rate=1/interval, taus=taus)
    if not np.array_equal(t, sorted(taus)) or not np.isfinite(sigma).all() or np.any(sigma <= 0) or np.any(count < 2):
        raise ValueError('Invalid/incomplete objective ADEV')
    # Actual simulation output, evaluated at exact user-selected taus; no fitted replacement curve.
    value = float(np.mean(np.log10(sigma)))
    return value, [dict(tau_s=float(a), adev=float(b), error=float(c), terms=int(d)) for a,b,c,d in zip(t,sigma,error,count)]


def evaluate(case: Path, engine: Path, timeout: float, taus: list) -> dict:
    import numpy as np
    import pandas as pd
    from tools import plot_results as plot
    info = inspect_case(case)
    (case / 'logs').mkdir()
    env = os.environ.copy()
    strict = case / 'logs/innovation.tsv'
    env['GSTAR_STRICT_INNOVATION_TSV'] = str(strict)
    started = time.monotonic()
    with (case / 'logs/console.log').open('wb') as log:
        completed = subprocess.run([str(engine), 'config/file_table'], cwd=case, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    if completed.returncode:
        raise ValueError(f'Engine returned {completed.returncode}; inspect {case / "logs"}')
    for path in (case / 'logs/console.log', case / 'results/gstar.log'):
        if not path.is_file() or ERRORS.search(path.read_text(encoding='utf-8', errors='replace')):
            raise ValueError(f'Engine log missing or contains errors: {path}')
    innovation = pd.read_csv(strict, sep='\t', usecols=['epoch','status','nis'])
    if len(innovation) != info['duration_s'] / info['interval_s'] or set(innovation.status) != {'ok'} or not np.isfinite(innovation.nis).all():
        raise ValueError('Strict innovation validation failed')
    n_clocks = len(read_coefficients((case/'config/session.obj').read_text(encoding='utf-8')))
    ids = [f'SIM{i}' for i in range(1, n_clocks+1)]
    epochs, phases = plot.load_results(case/'results', ids,
        plot.dp.SchemaConfig(trend_state=2, num_harmonics=0, rate_hz=1/info['interval_s'], dev_mode='adev'))
    expected = np.arange(np.datetime64(info['start']) + np.timedelta64(round(info['interval_s']*3e6), 'us'),
                         np.datetime64(info['end']), np.timedelta64(round(info['interval_s']*1e6), 'us'))
    if not np.array_equal(epochs, expected):
        raise ValueError('Native result does not cover the full configured training window')
    loss, values = score_phase(phases['Ensemble'], info['interval_s'], taus)
    record = {'loss': loss, 'objective': 'mean(log10 ADEV) at exact selected taus', 'adev': values,
              'strict_epochs': len(innovation), 'result_epochs': len(epochs), 'seconds': time.monotonic()-started}
    save_json(case / 'score.json', record)
    return record


def export_history(study, output: Path) -> None:
    with (output / 'trials.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['trial','stage','status','loss','best_so_far','seconds','parameters','error'])
        writer.writeheader()
        best = None
        for trial in study.trials:
            valid = trial.state.name == 'COMPLETE'
            if valid:
                best = trial.value if best is None else min(best, trial.value)
            writer.writerow({'trial': trial.number, 'stage': trial.user_attrs.get('stage'), 'status': trial.state.name,
                'loss': trial.value if valid else '', 'best_so_far': best, 'seconds': trial.user_attrs.get('seconds'),
                'parameters': json.dumps(trial.params), 'error': trial.user_attrs.get('error','')})


def plot_search(search: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    import pandas as pd
    frame = pd.read_csv(search / 'trials.csv')
    valid = frame[frame.status == 'COMPLETE']
    if valid.empty:
        raise ValueError('No completed trial to plot')
    figures = search / 'figures'
    figures.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(9,5))
    for stage in ('initial', 'random', 'TPE'):
        subset = valid[valid.stage == stage]
        if not subset.empty:
            ax.scatter(subset.trial, subset.loss, label=stage)
    ax.plot(valid.trial, valid.best_so_far, color='black', label='Best observed training loss')
    ax.set(xlabel='Trial number (zero based)', ylabel='Mean log10 ADEV (lower is better)', title='Actual GSTAR parameter search')
    ax.legend()
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(alpha=.2)
    fig.tight_layout()
    for suffix in ('png','svg','pdf'):
        fig.savefig(figures / f'convergence.{suffix}', dpi=160)
    plt.close(fig)
    (search / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>扩散系数优化</title>'
        '<h1>实际运行的扩散系数搜索</h1><p>每个点对应一次真实 GSTAR 解算。目标越小越好；失败试验在 trials.csv 中保留。训练最优不保证验证期最优。</p>'
        '<img src="figures/convergence.svg" style="max-width:100%">' + frame[['trial','stage','status','loss','best_so_far']].to_html(index=False), encoding='utf-8')


def run_search(config_path: Path, output: Path) -> None:
    import optuna
    config = json.loads(config_path.read_text(encoding='utf-8'))
    case = (config_path.parent / config['training_case']).resolve()
    engine = (config_path.parent / config['engine']).resolve()
    info = inspect_case(case)
    initial = read_coefficients(Path(info['tables']['object']).read_text(encoding='utf-8'))
    validate_search(config, initial, info)
    if not engine.is_file():
        raise ValueError(f'Install the private runtime first: {engine}')
    if output.exists():
        raise ValueError(f'Output already exists: {output}; use a new search directory')
    fingerprints = input_fingerprints(info)
    output.mkdir(parents=True)
    # The complete training template is frozen before the first trial.
    clone_case(case, output / 'template')
    snapshot = dict(config, training_case='template', engine=relative(engine, output, native=False))
    save_json(output / 'search.json', snapshot)
    save_json(output / 'provenance.json', {'training': info, 'input_sha256': fingerprints,
                                          'engine_sha256': sha256(engine)})
    save_json(output / 'initial_parameters.json', initial)
    distributions = {f'{clock}.{q}': optuna.distributions.FloatDistribution(positive(spec['min']),positive(spec['max']),log=True)
        for clock, qs in config['parameters'].items() for q,spec in qs.items() if spec['enabled']}
    sampler = optuna.samplers.TPESampler(seed=config['seed'], n_startup_trials=config['startup_trials'])
    study = optuna.create_study(direction='minimize', sampler=sampler)
    study.enqueue_trial({key:initial[key.split('.')[0]][key.split('.')[1]] for key in distributions})
    for number in range(config['trials']):
        completed_count = sum(t.state.name == 'COMPLETE' for t in study.trials)
        stage = 'initial' if number == 0 else ('random' if completed_count < config['startup_trials'] else 'TPE')
        trial = study.ask(distributions)
        trial.set_user_attr('stage', stage)
        coefficients = {clock:values.copy() for clock,values in initial.items()}
        for key, value in trial.params.items():
            clock, q = key.split('.')
            coefficients[clock][q] = value
        destination = output / 'trials' / f'trial_{number:03d}'
        clone_case(output / 'template', destination, coefficients)
        save_json(destination / 'parameters.json', coefficients)
        print(f'Trial {number+1}/{config["trials"]} ({stage}): {destination}', flush=True)
        try:
            score = evaluate(destination, engine, positive(config['timeout_seconds']), config['objective_taus_s'])
            trial.set_user_attr('seconds', score['seconds'])
            study.tell(trial, score['loss'])
            print(f'  loss={score["loss"]:.8f}; best={study.best_value:.8f}', flush=True)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            trial.set_user_attr('error', str(exc))
            study.tell(trial, state=optuna.trial.TrialState.FAIL)
            save_json(destination / 'failure.json', {'error': str(exc)})
            export_history(study, output)
            if number == 0:
                raise ValueError('Initial configuration failed; fix it before optimizing') from exc
            print(f'  FAILED: {exc}', flush=True)
        export_history(study, output)
    if input_fingerprints(info) != fingerprints:
        raise ValueError('Training input files changed during optimization')
    selected = output / 'trials' / f'trial_{study.best_trial.number:03d}'
    coefficients = json.loads((selected / 'parameters.json').read_text(encoding='utf-8'))
    save_json(output / 'best_parameters.json', coefficients)
    clone_case(output / 'template', output / 'best_case', coefficients)
    save_json(output / 'summary.json', {'best_trial': study.best_trial.number, 'best_loss': study.best_value,
        'initial_loss': study.trials[0].value, 'successful_trials': len([t for t in study.trials if t.state.name == 'COMPLETE']),
        'trial_count': len(study.trials), 'objective_taus_s': config['objective_taus_s'],
        'training_start': info['start'], 'training_end': info['end'], 'held_out_data_used_for_selection': False})
    plot_search(output)
    print(f'Finished: best trial {study.best_trial.number}; inspect {output / "best_parameters.json"}', flush=True)


def apply_best(search: Path, case: Path, output: Path) -> None:
    summary = json.loads((search / 'summary.json').read_text(encoding='utf-8'))
    info = inspect_case(case)
    if datetime.fromisoformat(info['start']) < datetime.fromisoformat(summary['training_end']):
        raise ValueError('Validation must start at or after the training end; do not reuse training dates')
    training = json.loads((search / 'provenance.json').read_text(encoding='utf-8'))['training']
    for key in ('interval_s','rank_remedy','scope','architecture','trend_states','harmonic_states'):
        if info[key] != training[key]:
            raise ValueError(f'Validation {key} must match training for a parameter-only comparison')
    for key in ('LEO Clk full name','PFD data directory'):
        if info['inputs'][key] != training['inputs'][key]:
            raise ValueError('Use the same clock group for training and validation')
    coefficients = json.loads((search / 'best_parameters.json').read_text(encoding='utf-8'))
    clone_case(case, output, coefficients)
    save_json(output / 'selection.json', {'best_trial': summary['best_trial'], 'training_end': summary['training_end'],
                                         'validation_start': info['start']})
    print(f'Created {output / "config/session.obj"}. Inspect it, then run the engine and plot independently.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--case', type=Path, required=True)
    init.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('run')
    run.add_argument('--config', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    apply = sub.add_parser('apply')
    apply.add_argument('--search', type=Path, required=True)
    apply.add_argument('--case', type=Path, required=True)
    apply.add_argument('--output', type=Path, required=True)
    plot = sub.add_parser('plot')
    plot.add_argument('--search', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init': initialize(args.case.resolve(), args.output.resolve())
        elif args.command == 'run': run_search(args.config.resolve(), args.output.resolve())
        elif args.command == 'apply': apply_best(args.search.resolve(), args.case.resolve(), args.output.resolve())
        else: plot_search(args.search.resolve())
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
