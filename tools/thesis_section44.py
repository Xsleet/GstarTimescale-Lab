#!/usr/bin/env python3
"""Recompute Section 4.4 archive plots; prepare editable native GSTAR cases."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import thesis_section43 as archive
from tools.run_config import RANK_REMEDIES, set_rank_remedy

EXAMPLE = ROOT / 'examples/thesis-section44'
PLOTTED = (1, 2, 4, 5)
SEARCH_PLOTTED = (1, 2, 4, 3)  # Original Figure 4.15 has a different fourth group.
CONFIGS = ('csac_only', 'mro_only', 'mixed_2plus2')
VARIANTS = ('baseline', 'adjusted')
LABELS = {'baseline': 'Original parameters', 'adjusted': 'Adjusted parameters (FREQFIX)'}
EXACT_TAUS = (10, 100, 300, 1000, 3000, 10000, 100000)


def release() -> dict:
    return json.loads((EXAMPLE / 'data-release.json').read_text(encoding='utf-8'))


def load_phase(path: Path, evaluation: bool):
    import numpy as np
    import pandas as pd
    frame = pd.read_csv(path, float_precision='round_trip')
    expected = ['time_s', *[f'clock{i}_s' for i in range(1, 5)],
                *(VARIANTS if evaluation else ('GREENHALL',))]
    if list(frame.columns) != expected or len(frame) != 86397:
        raise ValueError(f'Unexpected phase schema/sample count: {path}')
    if not np.isfinite(frame.to_numpy()).all() or not np.array_equal(frame.time_s, np.arange(30, 864000, 10)):
        raise ValueError(f'Invalid epochs, gaps or nonfinite phase: {path}')
    return frame


def improvement(reference, ensemble):
    """Positive means improvement; preserve negative values without clipping."""
    import numpy as np
    reference, ensemble = np.asarray(reference), np.asarray(ensemble)
    if np.any(reference <= 0) or not np.isfinite(reference).all() or not np.isfinite(ensemble).all():
        raise ValueError('Invalid ADEV values')
    return 100.0 * (1.0 - ensemble / reference)


def theory_adev(tau, q1: float, q2: float, drift_squared: float):
    import numpy as np
    tau = np.asarray(tau, dtype=float)
    return np.sqrt(q1 / tau + q2 * tau / 3.0 + drift_squared * tau**2 / 2.0)


def runtime_session(content: str, initialization: str) -> str:
    """Keep process coefficients; stabilize only priors and redundant-link R."""
    if initialization not in ('portable', 'archived'):
        raise ValueError('Unknown initialization profile')
    content = re.sub(r'TotalPhase:\[[^\]]+\],\s*', '', content)
    if initialization == 'portable':
        for field, prior in (('Phase', '1e-7'), ('Frequency', '1e-9')):
            content = re.sub(r'\b' + field + r':\[[^,]+,', field + ':[' + prior + ',', content)
        content = re.sub(r'Link_Noise:\{Default:[^}]+\}', 'Link_Noise:{Default:1e-12}', content)
        content = '* Portable initialization: Phase prior 1e-7; Frequency prior 1e-9; Link_Noise 1e-12.\n' + content
    return '* Phase:[initial_sigma,process_sigma]; Frequency:[initial_sigma,process_sigma]\n' + content


def prepare_case(inputs: Path, output: Path, group: str, variant: str, method: str,
                 initialization: str = 'portable') -> None:
    archive.verify(inputs, 'inputs', catalog=release())
    if group not in [f'mixed_2plus2_group{i:02d}' for i in range(1, 6)] or variant not in VARIANTS or method not in RANK_REMEDIES:
        raise ValueError('Unknown group, parameter variant or rank remedy')
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    recipes = json.loads((inputs / 'recipes' / f'{group}.json').read_text(encoding='utf-8'))[variant]
    clk = os.path.relpath(inputs / 'groups' / group / 'clk/SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK', output).replace('\\', '/')
    pfd = os.path.relpath(inputs / 'groups' / group / 'pfd', output).replace('\\', '/')
    if any(c.isspace() for c in clk + pfd):
        raise ValueError('Input paths must not contain spaces; put inputs and output under the same parent')
    config = output / 'config'
    config.mkdir(parents=True)
    for name in ('file_table', 'svinf.dat', 'leap.sec', 'pan_info'):
        shutil.copyfile(inputs / 'tables' / name, config / name)
    for name, content in recipes.items():
        if name == 'session.obj':
            # In this two-state case TotalPhase duplicates Phase. Retain a single
            # editable Phase field to avoid the runtime's substring alias lookup.
            content = runtime_session(content, initialization)
        (config / name).write_text(content.replace('@CLK@', clk).replace('@PFD@', pfd), encoding='utf-8', newline='\n')
    set_rank_remedy(config / 'Timescale.cfg', method)
    with (config / 'Timescale.cfg').open('a', encoding='utf-8') as out:
        out.write('\n* Rank deficiency remedy: NONE | SUMZERO | BROWN | GREENHALL | KPW\n')
    (output / 'case.json').write_text(json.dumps({'group': group, 'variant': variant, 'rank_remedy': method,
        'initialization': initialization,
        'data_window': '2026-01-11 through 2026-01-20 GPST',
        'note': 'adjusted uses the paper plotting archive FREQFIX, not the best search trial'}, indent=2) + '\n', encoding='utf-8')
    print(f'Created editable native configuration: {config}')
    print('Edit file_table, Timescale.cfg and session.obj; run the engine from the case directory.')
    if method != 'GREENHALL':
        print('This is a new method comparison; the Section 4.4 archive uses GREENHALL.')


def analyze(data: Path, output: Path) -> None:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    checked = archive.verify(data, 'analysis', catalog=release())
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    output.mkdir(parents=True)
    figures, tables = output / 'figures', output / 'tables'
    figures.mkdir()
    tables.mkdir()
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'svg.fonttype': 'none'})
    curves, rows, exact = {}, [], []
    for window in ('train', 'evaluation'):
        for path in sorted((data / window).glob('*.csv')):
            frame = load_phase(path, window == 'evaluation')
            for name in frame.columns[1:]:
                tau, sigma, error, count = archive.adev(frame[name].to_numpy())
                curves[window, path.stem, name] = (tau, sigma)
                rows.extend((window, path.stem, name, *values) for values in zip(tau, sigma, error, count))
                t, s, e, n = archive.adev(frame[name].to_numpy(), EXACT_TAUS)
                exact.extend((window, path.stem, name, *values) for values in zip(t, s, e, n))
        print(f'Calculated {window} phase ADEV', flush=True)
    columns = ['window', 'group', 'series', 'tau_s', 'adev', 'adev_error', 'terms']
    pd.DataFrame(rows, columns=columns).to_csv(tables / 'adev_octave.csv', index=False, float_format='%.17e')
    exact_frame = pd.DataFrame(exact, columns=columns)
    exact_frame.to_csv(tables / 'adev_exact.csv', index=False, float_format='%.17e')

    def mean_curve(keys):
        values = [curves[key] for key in keys]
        if any(not np.array_equal(values[0][0], v[0]) for v in values):
            raise ValueError('ADEV grids must match; do not interpolate')
        return values[0][0], np.mean([v[1] for v in values], axis=0)

    def finish(fig, name):
        fig.tight_layout()
        for suffix in ('svg', 'png', 'pdf'):
            fig.savefig(figures / f'{name}.{suffix}', dpi=170)
        plt.close(fig)

    def axes_style(ax, ylabel='ADEV'):
        ax.set_xlabel('Averaging time τ (s)')
        ax.set_ylabel(ylabel)
        ax.grid(True, which='both', alpha=.22)

    # Figure 4.12: 16 clocks of each type, matching the notebook's four groups.
    diffusion = pd.read_csv(data / 'diffusion_coefficients.csv')
    theory_rows = []
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    train_references = {}
    for ax, kind, title in zip(axes, CONFIGS[:2], ('CSAC', 'mRO')):
        tau, avg = mean_curve([('train', f'{kind}_group{i:02d}', f'clock{k}_s') for i in PLOTTED for k in range(1, 5)])
        train_references[title] = (tau, avg)
        row = diffusion.loc[diffusion['时钟类型'] == title].iloc[0]
        model = theory_adev(tau, row['q1=mean(WFM^2)'], row['q2=mean(6RWFM^2)'], row['mean(c3^2)'])
        ax.loglog(tau, avg, 'o-', label='Mean of 16 clock ADEV curves', markersize=3)
        ax.loglog(tau, model, '--', label='Model from generating coefficients')
        ax.set_title(f'{title} · days 1–10')
        axes_style(ax)
        ax.legend(fontsize=8)
        theory_rows.extend((title, t, a, m) for t, a, m in zip(tau, avg, model))
    finish(fig, 'fig4_12')
    diffusion.to_csv(tables / 'table4_3_coefficients.csv', index=False)
    pd.DataFrame(theory_rows, columns=['clock_type', 'tau_s', 'mean_adev', 'model_adev']).to_csv(tables / 'fig4_12.csv', index=False)

    # Figure 4.13: ratio of arithmetic mean ADEV, not ADEV of mean phase.
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    gains = []
    for ax, title in zip(axes, ('CSAC', 'mRO')):
        tau, reference = train_references[title]
        for kind, label in zip(CONFIGS, ('S1: 4 CSAC', 'S2: 4 mRO', 'S3: 2 mRO + 2 CSAC')):
            t, avg = mean_curve([('train', f'{kind}_group{i:02d}', 'GREENHALL') for i in PLOTTED])
            if not np.array_equal(t, tau):
                raise ValueError('Reference grid mismatch')
            gain = improvement(reference, avg)
            ax.semilogx(tau, gain, label=label)
            gains.extend(('train', title, kind, t, v) for t, v in zip(tau, gain))
        ax.axhline(50, color='gray', linestyle=':', label='4 identical clocks: 50%')
        ax.axhline(100*(1-1/np.sqrt(2)), color='gray', linestyle='--', label='2 identical clocks: 29.3%')
        ax.set_title(f'Compared with mean {title} · days 1–10')
        axes_style(ax, 'ADEV improvement (%)')
        ax.legend(fontsize=8)
    finish(fig, 'fig4_13')

    # Figure 4.15: export the actual stored objective. Never relabel it NIS.
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    best, rolling = [], []
    for index in range(1, 6):
        group = f'mixed_2plus2_group{index:02d}'
        trials = pd.read_csv(data / 'search' / f'{group}.csv', float_precision='round_trip')
        if trials.empty or trials.trial.duplicated().any() or not np.isfinite(trials.loss).all():
            raise ValueError(f'Invalid search history: {group}')
        selected = trials.loc[trials.loss.idxmin()]
        params = pd.read_csv(data / 'search' / f'{group}_parameters.csv', float_precision='round_trip')
        for row in params.loc[params.trial == selected.trial].itertuples():
            best.append((group, int(selected.trial), selected.loss, row.param_name, row.param_value, row.param_value**2))
        if index not in SEARCH_PLOTTED:
            continue
        ax = axes.flat[SEARCH_PLOTTED.index(index)]
        roll = trials.loss.rolling(50, min_periods=16, center=True)
        median, q25, q75 = roll.median(), roll.quantile(.25), roll.quantile(.75)
        ax.scatter(trials.trial, trials.loss, s=7, alpha=.25, label='Recorded trials')
        ax.fill_between(trials.trial, q25, q75, alpha=.2, label='Rolling IQR (50 trials)')
        ax.plot(trials.trial, median, label='Rolling median')
        ax.plot(trials.trial, trials.loss.cummin(), color='#c94831', label='Best so far')
        ax.scatter([selected.trial], [selected.loss], marker='*', s=110, color='black')
        ax.set_title(f'Panel {SEARCH_PLOTTED.index(index)+1} · group{index:02d} · best trial {int(selected.trial)}')
        ax.set_xlabel('Archived trial number (zero based)')
        ax.set_ylabel('Stored loss: mean(log10 ADEV)')
        ax.grid(alpha=.2)
        ax.legend(fontsize=7)
        rolling.extend((group, *r) for r in zip(trials.trial, median, q25, q75))
    finish(fig, 'fig4_15')
    pd.DataFrame(best, columns=['group', 'best_trial', 'loss', 'parameter', 'sigma', 'sigma_squared']).to_csv(tables / 'search_best_parameters.csv', index=False, float_format='%.17e')
    pd.DataFrame(rolling, columns=['group', 'trial', 'median', 'q25', 'q75']).to_csv(tables / 'search_rolling.csv', index=False)

    # Figure 4.16: four raw clocks plus the two archived configurations.
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for panel, (ax, index) in enumerate(zip(axes.flat, PLOTTED), 1):
        group = f'mixed_2plus2_group{index:02d}'
        for k in range(1, 5):
            tau, sigma = curves['evaluation', group, f'clock{k}_s']
            ax.loglog(tau, sigma, '--', color=('#677987' if k < 3 else '#9b8468'), alpha=.7,
                      label=f'{"mRO" if k < 3 else "CSAC"} / SIM{k}')
        for variant, color in zip(VARIANTS, ('#7556a4', '#dc792e')):
            tau, sigma = curves['evaluation', group, variant]
            ax.loglog(tau, sigma, color=color, linewidth=2, label=LABELS[variant])
        ax.set_title(f'LEO {panel:02d} · group{index:02d} · days 11–20')
        axes_style(ax)
        ax.legend(fontsize=7)
    finish(fig, 'fig4_16')

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, title, clocks in zip(axes, ('CSAC', 'mRO'), ((3, 4), (1, 2))):
        tau, reference = mean_curve([('evaluation', f'mixed_2plus2_group{i:02d}', f'clock{k}_s') for i in PLOTTED for k in clocks])
        for variant in VARIANTS:
            t, avg = mean_curve([('evaluation', f'mixed_2plus2_group{i:02d}', variant) for i in PLOTTED])
            if not np.array_equal(t, tau):
                raise ValueError('Reference grid mismatch')
            gain = improvement(reference, avg)
            ax.semilogx(tau, gain, label=LABELS[variant])
            gains.extend(('evaluation', title, variant, t, v) for t, v in zip(tau, gain))
        ax.axhline(100*(1-1/np.sqrt(2)), color='gray', linestyle='--', label='2 identical clocks: 29.3%')
        ax.set_title(f'Compared with mean {title} · days 11–20')
        axes_style(ax, 'ADEV improvement (%)')
        ax.legend(fontsize=8)
    finish(fig, 'fig4_17')
    pd.DataFrame(gains, columns=['window', 'reference_type', 'series', 'tau_s', 'improvement_percent']).to_csv(tables / 'improvement.csv', index=False, float_format='%.17e')
    selected = exact_frame[(exact_frame.window == 'evaluation') & exact_frame.series.isin(VARIANTS)
                           & exact_frame.group.isin([f'mixed_2plus2_group{i:02d}' for i in PLOTTED])]
    mean = selected.groupby(['tau_s', 'series']).adev.mean().unstack()
    mean['reduction_percent'] = improvement(mean.baseline, mean.adjusted)
    mean.to_csv(tables / 'parameter_comparison.csv', float_format='%.17e')
    reference = json.loads((EXAMPLE / 'expected-results.json').read_text(encoding='utf-8'))
    for row in reference['evaluation_adev_mean']:
        for variant in VARIANTS:
            if not np.isclose(mean.loc[row['tau_s'], variant], row[variant], rtol=1e-10, atol=0):
                raise ValueError(f'Archive ADEV regression at tau={row["tau_s"]}, {variant}')
    observed_best = {row[0]: row[1] for row in best}
    if observed_best != reference['best_trials']:
        raise ValueError('Archived best-trial selection differs from the verified reference')
    summary = {'verified_archive': checked, 'sample_interval_s': 10, 'phase_samples_per_series': 86397,
               'plotted_groups': list(PLOTTED), 'search_plotted_groups': list(SEARCH_PLOTTED),
               'evaluation_adev_mean': mean.reset_index().to_dict('records'),
               'scope': 'Archive reanalysis and FREQFIX parameter comparison, not an end-to-end reproduction of NIS/GP-EI optimization'}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    captions = {'fig4_12': '图 4.12：16 只 CSAC、16 只 mRO 的平均 ADEV 与模型曲线。',
                'fig4_13': '图 4.13：三种钟组配置相对同类型原始钟的改善率。',
                'fig4_15': '图 4.15：归档搜索损失和最佳记录。第四面板是 group03；记录目标不是 NIS。',
                'fig4_16': '图 4.16：每个面板有四只原始钟和两种参数配置，共六条 ADEV。',
                'fig4_17': '图 4.17：先取 ADEV 算术平均，再算改善率。负值表示组合不如该类原始钟。'}
    sections = ''.join(f'<h2>{caption}</h2><img src="figures/{name}.svg" alt="{caption}">' for name, caption in captions.items())
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>论文 4.4 实验报告</title>'
    page += '<style>body{font:16px/1.7 system-ui;max-width:1120px;margin:40px auto;padding:0 20px;color:#223}img{width:100%}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccc}</style>'
    page += '<h1>第 4.4 节：理解噪声参数怎样影响时间尺度</h1><p>前 10 天用于训练/分析，后 10 天用于对比；采样间隔 10 秒。相同 τ 下 ADEV 越小越稳定。</p>'
    page += '<p><b>来源说明：</b>原图的参数调整曲线来自 GREENHALL_FREQFIX；搜索历史独立展示，不能把两者视为 NIS/GP-EI 搜索到验证的完整复现。核心算法未修改。</p>'
    page += '<h2>后 10 天：四组组合时间尺度平均 ADEV</h2>' + mean.to_html(float_format=lambda x: f'{x:.6g}')
    page += '<p>baseline 为原参数，adjusted 为调整参数；reduction_percent 为 ADEV 降低百分比。详细值和误差估计见 tables/adev_exact.csv。</p>' + sections
    page += '<p>图 4.14 为方法流程示意，见仓库教程；不是一张数据曲线。全部输出：figures/ 的 SVG、PNG、PDF；tables/ 的 CSV。</p></html>'
    (output / 'report.html').write_text(page, encoding='utf-8')
    print(f'PASS: report written to {output / "report.html"}')


def compare_runs(baseline: Path, adjusted: Path, output: Path) -> None:
    """Plot two native runs on an identical epoch and input-clock basis."""
    import numpy as np
    import matplotlib.pyplot as plt
    from tools import plot_results as plot
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    cfg = plot.dp.SchemaConfig(trend_state=2, num_harmonics=0, rate_hz=.1, dev_mode='adev')
    loaded = []
    for result in (baseline, adjusted):
        log = result / 'gstar.log'
        if not log.is_file():
            raise ValueError(f'Missing solver log: {log}')
        if re.search(r'\[(?:error|critical)\]|(?:\*{3}|#{3})\s*error', log.read_text(encoding='utf-8', errors='replace'), re.I):
            raise ValueError(f'The solver logged an error: {log}')
        loaded.append(plot.load_results(result, [f'SIM{i}' for i in range(1, 5)], cfg))
    (t1, first), (t2, second) = loaded
    if not np.array_equal(t1, t2):
        raise ValueError('The two runs must cover identical epochs')
    for k in range(1, 5):
        if not np.array_equal(first[f'SIM{k}'], second[f'SIM{k}']):
            raise ValueError('The two runs must use identical original clocks')
    output.mkdir(parents=True)
    series = {f'SIM{k}': first[f'SIM{k}'] for k in range(1, 5)}
    series.update(baseline=first['Ensemble'], adjusted=second['Ensemble'])
    plot.write_adev_table(output / 'adev_octave.tsv', series, .1, 'octave')
    plot.write_adev_table(output / 'adev_exact.tsv', series, .1, EXACT_TAUS)
    fig, ax = plt.subplots(figsize=(9, 6))
    for name, phase in series.items():
        tau, sigma, _, _ = archive.adev(phase)
        ax.loglog(tau, sigma, '--' if name.startswith('SIM') else '-', label=LABELS.get(name, name))
    ax.set(xlabel='Averaging time τ (s)', ylabel='ADEV', title='Four original clocks and two parameter configurations')
    ax.grid(True, which='both', alpha=.2)
    ax.legend()
    fig.tight_layout()
    for suffix in ('svg', 'png', 'pdf'):
        fig.savefig(output / f'comparison.{suffix}', dpi=170)
    plt.close(fig)
    (output / 'coverage.json').write_text(json.dumps({'start': str(t1[0]), 'end': str(t1[-1]),
        'samples': len(t1), 'sample_interval_s': 10, 'identical_original_clocks': True}, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: six-curve comparison written to {output}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fetch = sub.add_parser('fetch', help='Download and verify data only')
    fetch.add_argument('--kind', choices=('analysis', 'inputs'), default='analysis')
    fetch.add_argument('--output', type=Path, required=True)
    fetch.add_argument('--archive', type=Path)
    plot = sub.add_parser('analyze', help='Recompute archive ADEV and plots')
    plot.add_argument('--data', type=Path, required=True)
    plot.add_argument('--output', type=Path, required=True)
    prepare = sub.add_parser('prepare-case', help='Prepare editable native configuration')
    prepare.add_argument('--inputs', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    prepare.add_argument('--group', choices=[f'mixed_2plus2_group{i:02d}' for i in range(1, 6)], default='mixed_2plus2_group01')
    prepare.add_argument('--variant', choices=VARIANTS, default='adjusted')
    prepare.add_argument('--method', choices=RANK_REMEDIES, default='GREENHALL')
    prepare.add_argument('--initialization', choices=('portable', 'archived'), default='portable',
                         help='portable stabilizes priors/link sigma; archived preserves the old values')
    compare = sub.add_parser('compare-runs', help='Plot four clocks plus two native results')
    compare.add_argument('--baseline', type=Path, required=True, help='First results directory')
    compare.add_argument('--adjusted', type=Path, required=True, help='Second results directory')
    compare.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'fetch':
            archive.fetch(args.kind, args.output.resolve(), args.archive, catalog=release())
        elif args.command == 'analyze':
            analyze(args.data.resolve(), args.output.resolve())
        elif args.command == 'prepare-case':
            prepare_case(args.inputs.resolve(), args.output.resolve(), args.group, args.variant, args.method, args.initialization)
        else:
            compare_runs(args.baseline.resolve(), args.adjusted.resolve(), args.output.resolve())
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
