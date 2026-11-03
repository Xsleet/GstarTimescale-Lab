#!/usr/bin/env python3
"""Download, verify and analyze the archived thesis Section 4.3 experiment."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples' / 'thesis-section43'
CONFIGS = ('csac_only', 'mro_only', 'mixed_2plus2')
METHODS = ('SUMZERO', 'BROWN', 'GREENHALL', 'KPW')
PLOTTED = (1, 2, 4, 5)
COVARIANCE_GROUP = 2  # Word-embedded Figures 4.7/4.8 match the group02 candidate images.
LABELS = {'SUMZERO': 'Centroid', 'BROWN': 'Brown', 'GREENHALL': 'Greenhall', 'KPW': 'KPW'}
COLORS = {'SUMZERO': '#1f77b4', 'BROWN': '#c62728', 'GREENHALL': '#f0b16e', 'KPW': '#7161a8'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_name(name: str) -> bool:
    return bool(name) and '\\' not in name and ':' not in name and not PurePosixPath(name).is_absolute() and all(
        part not in ('', '.', '..') for part in name.split('/'))


def release() -> dict:
    return json.loads((EXAMPLE / 'data-release.json').read_text(encoding='utf-8'))


def verify(data: Path, kind: str) -> dict:
    descriptor = release()['assets'][kind]
    manifest_path = data / 'manifest.json'
    if sha256(manifest_path) != descriptor['manifest_sha256']:
        raise ValueError('Data manifest checksum mismatch')
    entries = json.loads(manifest_path.read_text(encoding='utf-8'))['files']
    if any(not safe_name(n) for n in entries):
        raise ValueError('Unsafe manifest entry')
    paths = list(data.rglob('*'))
    if data.is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError('Symlinks are not permitted in an installed data package')
    actual = {p.relative_to(data).as_posix() for p in paths if p.is_file()}
    if actual != set(entries) | {'manifest.json'}:
        raise ValueError('Missing or extra data files; keep generated results outside the data folder')
    for name, info in entries.items():
        p = data / name
        if p.is_symlink() or p.stat().st_size != info['bytes'] or sha256(p) != info['sha256']:
            raise ValueError(f'Data checksum mismatch: {name}')
    return {'files': len(actual), 'manifest_sha256': descriptor['manifest_sha256']}


def extract_archive(archive: Path, target: Path, info: dict) -> None:
    if archive.stat().st_size != info['bytes'] or sha256(archive) != info['sha256']:
        raise ValueError('Archive checksum mismatch; do not use this download')
    if target.exists():
        raise ValueError(f'Output already exists: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.thesis43-', dir=target.parent) as temporary:
        stage = Path(temporary) / 'data'
        stage.mkdir()
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            if len(names) != len(set(names)) or len(names) != info['file_count']:
                raise ValueError('Duplicate entries or unexpected file count')
            if sum(i.file_size for i in z.infolist()) != info['expanded_bytes']:
                raise ValueError('Unexpected expanded archive size')
            for i in z.infolist():
                mode = i.external_attr >> 16
                if not safe_name(i.filename) or stat.S_ISLNK(mode) or i.is_dir():
                    raise ValueError(f'Unsafe archive entry: {i.filename}')
            manifest = z.read('manifest.json')
            if hashlib.sha256(manifest).hexdigest() != info['manifest_sha256']:
                raise ValueError('Manifest checksum mismatch')
            entries = json.loads(manifest)['files']
            if set(names) != set(entries) | {'manifest.json'}:
                raise ValueError('Archive contents differ from manifest')
            for name in names:
                dst = stage / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, dst.open('wb') as out:
                    shutil.copyfileobj(src, out)
                if name != 'manifest.json':
                    if dst.stat().st_size != entries[name]['bytes'] or sha256(dst) != entries[name]['sha256']:
                        raise ValueError(f'Checksum mismatch: {name}')
        # Both resolved paths remain inside the explicitly selected destination parent.
        if not stage.resolve().is_relative_to(target.parent.resolve()):
            raise ValueError('Invalid staging path')
        stage.rename(target)


def fetch(kind: str, output: Path, archive: Path | None) -> None:
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    info = release()['assets'][kind]
    if archive is not None:
        extract_archive(archive.resolve(), output, info)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.thesis43-download-', dir=output.parent) as temporary:
            downloaded = Path(temporary) / info['filename']
            url = f"https://github.com/Xsleet/GstarTimescale-Lab/releases/download/{release()['release_tag']}/{info['filename']}"
            print(f'Downloading {info["bytes"] / 1e6:.1f} MB: {url}', flush=True)
            request = urllib.request.Request(url, headers={'User-Agent': 'GstarTimescale-Lab'})
            with urllib.request.urlopen(request, timeout=60) as response, downloaded.open('wb') as out:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > info['bytes']:
                        raise ValueError('Download exceeds the pinned release size')
                    out.write(block)
            extract_archive(downloaded, output, info)
    print(f'PASS: verified {kind} data installed in {output}')


def load_phase(path: Path):
    import numpy as np
    import pandas as pd
    frame = pd.read_csv(path, float_precision='round_trip')
    columns = ['time_s', 'clock1_s', 'clock2_s', 'clock3_s', 'clock4_s', *METHODS]
    if list(frame.columns) != columns or len(frame) != 86397:
        raise ValueError(f'Unexpected phase schema or sample count: {path}')
    values = frame.to_numpy()
    if not np.all(np.isfinite(values)) or not np.array_equal(values[:, 0], np.arange(30, 864000, 10)):
        raise ValueError(f'Nonfinite phase, gaps or invalid time range: {path}')
    return frame


def adev(phase, taus='octave'):
    import allantools
    # Same non-overlapping phase ADEV used by Chapter4.ipynb and DataProcess.
    return allantools.adev(phase, rate=0.1, data_type='phase', taus=taus)


def prepare_case(inputs: Path, output: Path, group: str, method: str) -> None:
    verify(inputs, 'inputs')
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    recipes = json.loads((inputs / 'recipes' / f'{group}.json').read_text(encoding='utf-8'))
    clk = os.path.relpath(inputs / 'groups' / group / 'clk' / 'SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK', output).replace('\\', '/')
    pfd = os.path.relpath(inputs / 'groups' / group / 'pfd', output).replace('\\', '/')
    if any(c.isspace() for c in clk + pfd):
        raise ValueError('Relative input paths contain spaces; put inputs and output under the same space-free parent')
    config = output / 'config'
    config.mkdir(parents=True)
    for name in ('file_table', 'svinf.dat', 'leap.sec', 'pan_info'):
        shutil.copyfile(inputs / 'tables' / name, config / name)
    for name, text in recipes[method].items():
        (config / name).write_text(text.replace('@CLK@', clk).replace('@PFD@', pfd), encoding='utf-8', newline='\n')
    print(f'Created editable native configuration: {config}')
    print(f'Run: python lab.py execute --workdir "{output}"')
    if method == 'NONE':
        print('NONE is an intentionally unstable baseline. An early failed run must not be reported as successful.')


def analyze(data: Path, output: Path) -> None:
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    checked = verify(data, 'analysis')
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    output.mkdir(parents=True)
    figures = output / 'figures'
    tables = output / 'tables'
    figures.mkdir()
    tables.mkdir()
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'mathtext.fontset': 'dejavusans',
                         'font.size': 10, 'axes.unicode_minus': False, 'svg.fonttype': 'none'})
    rows = []
    exact = []
    curves = {}
    for config in CONFIGS:
        for index in range(1, 6):
            group = f'{config}_group{index:02d}'
            frame = load_phase(data / 'phase' / f'{group}.csv')
            for column in frame.columns[1:]:
                tau, sigma, error, count = adev(frame[column].to_numpy())
                curves[group, column] = (tau, sigma)
                for t, s, e, n in zip(tau, sigma, error, count):
                    rows.append((group, column, t, s, e, n))
                if config == 'mixed_2plus2' and column in METHODS:
                    t, s, _, n = adev(frame[column].to_numpy(), [10, 100, 1000, 10000, 100000])
                    exact.extend((group, column, a, b, c) for a, b, c in zip(t, s, n))
        print(f'Calculated {config}: 5 groups x 8 phase series', flush=True)
    curve_table = pd.DataFrame(rows, columns=['group', 'series', 'tau_s', 'adev', 'adev_error', 'terms'])
    curve_table.to_csv(tables / 'adev_octave.csv', index=False, float_format='%.17e')
    exact = pd.DataFrame(exact, columns=['group', 'method', 'tau_s', 'adev', 'terms'])
    exact.to_csv(tables / 'adev_exact_by_group.csv', index=False, float_format='%.17e')
    means = exact.groupby(['method', 'tau_s']).adev.mean()
    plotted_means = exact[~exact.group.str.endswith('group03')].groupby(['method', 'tau_s']).adev.mean()
    printed = json.loads((EXAMPLE / 'paper-values.json').read_text(encoding='utf-8'))
    comparisons = []
    for method in METHODS:
        for tau, paper in zip(printed['tau_s'], printed['values'][method]):
            value = float(means.loc[method, tau])
            comparisons.append((tau, method, paper, value, float(plotted_means.loc[method,tau]),
                                (value / paper - 1) * 100, f'{value:.2e}' == f'{paper:.2e}'))
    comparison = pd.DataFrame(comparisons, columns=['tau_s', 'method', 'paper_rounded', 'five_group_exact',
                              'four_plotted_group_exact', 'difference_percent', 'matches_printed_rounding'])
    comparison.to_csv(tables / 'table4_2_audit.csv', index=False, float_format='%.17e')
    notebook = pd.read_csv(data / 'notebook_summary.csv', float_precision='round_trip')
    selected = curve_table[curve_table.group.str.startswith('mixed_2plus2') & curve_table.series.isin(METHODS)]
    averages = selected.groupby(['series', 'tau_s']).adev.mean()
    errors = [abs(float(averages.loc[r.method,r.actual_tau_s]) / r.adev_mean - 1) for r in notebook.itertuples()]
    max_error = max(errors)
    if max_error > 1e-10:
        raise ValueError(f'Archived notebook table mismatch: relative error {max_error}')
    reference = EXAMPLE / 'reference' / 'adev_octave.csv'
    if not reference.is_file():
        raise ValueError('Reference ADEV table missing; download the complete repository')
    expected = pd.read_csv(reference, float_precision='round_trip')
    if not curve_table[['group','series']].equals(expected[['group','series']]) or not np.array_equal(curve_table.tau_s, expected.tau_s):
        raise ValueError('Reference curve keys differ')
    if not np.allclose(curve_table.adev, expected.adev, rtol=1e-10, atol=0):
        raise ValueError('Reference ADEV curves differ')

    image_names = []
    def save(fig, stem):
        fig.savefig(figures / f'{stem}.svg', bbox_inches='tight')
        fig.savefig(figures / f'{stem}.png', dpi=220, bbox_inches='tight')
        plt.close(fig)
        image_names.append(stem)

    for fig_no, config in enumerate(CONFIGS, 9):
        fig, axes = plt.subplots(2, 2, figsize=(8.2, 6.6), sharex=True, sharey=True)
        for panel, (ax, index) in enumerate(zip(axes.flat, PLOTTED), 1):
            group = f'{config}_group{index:02d}'
            for clock in range(1, 5):
                family = 'CSAC' if config == 'csac_only' or (config == 'mixed_2plus2' and clock > 2) else 'MRO'
                ax.loglog(*curves[group,f'clock{clock}_s'], '--', color='0.55' if family == 'MRO' else '0.25',
                          marker='v' if family == 'MRO' else '^', ms=3, lw=0.8,
                          label=family if clock == 1 or (config == 'mixed_2plus2' and clock == 3) else None)
            for method in ('BROWN','GREENHALL','KPW','SUMZERO'):
                ax.loglog(*curves[group,method], '--' if method == 'KPW' else '-', color=COLORS[method],
                          marker='o', ms=3, lw=1.3, label=LABELS[method])
            ax.set(xlim=(10,1e5), ylim=(1e-12,5e-10), title=f'LEO {panel:02d} (group{index:02d})')
            ax.grid(True, which='both', alpha=.25)
            ax.set_xlabel('Averaging time (s)')
            ax.set_ylabel('Allan deviation')
        handles, labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='upper center', ncol=len(labels), fontsize=9)
        fig.tight_layout(rect=(0,0,1,.94))
        save(fig,f'fig4_{fig_no}')

    covariance_points = []
    for fig_no, modes in [(7,['NONE']), (8,['SUMZERO','BROWN','GREENHALL']), ('8_max',['SUMZERO','BROWN','GREENHALL'])]:
        fig, axes = plt.subplots(1,3,figsize=(10.2,3.3),sharey=True)
        for ax, config, scheme in zip(axes,CONFIGS,['S1','S2','S3']):
            for method in modes:
                frame = pd.read_csv(data/'covariance'/f'{config}_group{COVARIANCE_GROUP:02d}'/f'{method}.csv',float_precision='round_trip')
                t = frame.time_s.to_numpy()/3600
                variance = frame.iloc[:,1:].to_numpy()
                std = np.sqrt(np.where(np.isfinite(variance) & (variance > 0),variance,np.nan))
                if fig_no == 7:
                    series = [(f'Clock {i+1}', std[:,i], None) for i in range(4)]
                else:
                    values = std[:,0]
                    if fig_no == '8_max':
                        values = np.full(len(std), np.nan)
                        valid_epoch = np.all(np.isfinite(std), axis=1)
                        values[valid_epoch] = np.max(std[valid_epoch], axis=1)
                    series = [(LABELS[method],values,COLORS[method])]
                for label, values, color in series:
                    valid = np.isfinite(values)
                    x,y = t[valid],values[valid]
                    covariance_points.extend((str(fig_no),config,method,label,float(a),float(b)) for a,b in zip(x,y))
                    if fig_no != 7 and len(x)>2200:
                        ix=np.linspace(0,len(x)-1,2200).astype(int); x,y=x[ix],y[ix]
                    ax.semilogy(x,y,label=label,color=color,lw=.8)
            ax.set(xlim=(0,24),xticks=[0,6,12,18,24],xlabel='Time (h)',title=scheme)
            if fig_no != 7: ax.set_ylim(1e-15,1e-6)
            ax.grid(True,alpha=.25)
        axes[0].set_ylabel('Phase-state standard deviation (s)')
        handles,labels=axes[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='upper center',ncol=len(labels))
        fig.tight_layout(rect=(0,0,1,.91))
        save(fig,f'fig4_{fig_no}')
    pd.DataFrame(covariance_points,columns=['figure','configuration','method','series','time_h','std_s']).to_csv(
        tables/'covariance_points.csv',index=False,float_format='%.17e')
    checked.update({'phase_series':120,'octave_adev_points':len(curve_table),'notebook_summary_points':len(errors),
                    'notebook_max_relative_error':max_error,'paper_table_matching_cells':int(comparison.matches_printed_rounding.sum()),
                    'paper_table_total_cells':20,'solver_rerun':False})
    (output/'validation.json').write_text(json.dumps(checked,indent=2)+'\n',encoding='utf-8')
    summary = comparison.assign(method=comparison.method.map(LABELS)).rename(columns={
        'tau_s':'平滑时间 (s)', 'method':'方法', 'paper_rounded':'论文原值',
        'five_group_exact':'五组直接重算', 'four_plotted_group_exact':'图示四组直接重算',
        'difference_percent':'五组相对差异 (%)', 'matches_printed_rounding':'匹配论文印刷精度'
    }).to_html(index=False,float_format=lambda x:f'{x:.4e}')
    captions = {'fig4_7':'图 4.7：无补偿时的后验标准差', 'fig4_8':'图 4.8：三种补偿方法（原脚本的单钟口径）',
                'fig4_8_max':'图 4.8 补充核对：四钟标准差最大值', 'fig4_9':'图 4.9：CSAC 同构钟组 ADEV',
                'fig4_10':'图 4.10：MRO 同构钟组 ADEV', 'fig4_11':'图 4.11：异构钟组 ADEV'}
    body=''.join(f'<h2>{html.escape(caption)}</h2><img src="figures/{name}.svg" alt="{html.escape(caption)}">'
                 for name, caption in captions.items())
    (output/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>论文 4.3 复现</title>'
        '<style>body{max-width:1100px;margin:40px auto;padding:0 20px;font:16px/1.7 sans-serif;color:#222}img{max-width:100%}table{font-size:13px;border-collapse:collapse}td,th{padding:6px;border:1px solid #ddd}pre{white-space:pre-wrap}</style>'
        '<h1>论文第 4.3 节实验复现</h1><p>归档仿真数据：10 天、10 秒采样，三种钟组配置。此报告从公开相位和协方差数据重算，未运行核心解算程序。</p>'
        '<p>图 4.7/4.8 按 Word 内嵌图像匹配选择 group02。图 4.8 保留脚本的 Clock 1 口径，另附 max 图对应正文“四钟最大值”口径。图 4.9～4.11 展示 group01、02、04、05；原表统计归档含 5 组。详见仓库复现说明。</p>'
        f'<h2>核对结果</h2><p>数据文件校验通过；120 条序列、1800 个 ADEV 点与原计算函数一致。归档汇总表 60 项一致。论文表 4.2 的 {checked["paper_table_matching_cells"]}/20 项匹配印刷精度，其余项尚未复现。</p>'
        '<details><summary>查看校验明细</summary><pre>'+html.escape(json.dumps(checked,indent=2,ensure_ascii=False))+'</pre></details>'+body+
        '<h2>表 4.2 数值核对</h2><p>两种重算值均直接在目标 τ 计算 ADEV，未插值。False 表示未复现论文的印刷精度，不能视为通过。原始字段名与高精度数值见 tables/table4_2_audit.csv。</p>'+summary+'</html>',encoding='utf-8')
    print(json.dumps(checked,indent=2))
    print(f'Report: {output / "report.html"}')


def compare_rerun(data: Path, workdir: Path, group: str, method: str, output: Path) -> bool:
    """Compare a new run without changing its results or concealing failed checks."""
    import re
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    verify(data, 'analysis')
    reference = load_phase(data / 'phase' / f'{group}.csv')
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    source = workdir / 'results' / 'IEM.txt'
    values = np.loadtxt(source, usecols=[0, 1, 2, 3, 13], ndmin=2)
    time = (values[:, 2] - 1) * 86400 + values[:, 3]
    aligned = (np.all(values[:, 0] == 2026) and np.all(values[:, 1] == 1)
               and np.array_equal(time, reference.time_s.to_numpy())
               and np.all(np.isfinite(values)))
    error_pattern = re.compile(r'\[(?:error|critical|fatal)\]|\b(?:fatal|exception|nan|inf)\b', re.I)
    log_paths = [workdir / 'results' / 'gstar.log', *sorted((workdir / 'logs').glob('execute_*/console.log'))]
    log_errors = [p.relative_to(workdir).as_posix() for p in log_paths
                  if p.is_file() and error_pattern.search(p.read_text(encoding='utf-8', errors='replace'))]
    record_paths = sorted((workdir / 'logs').glob('execute_*/execution.json'))
    record = json.loads(record_paths[-1].read_text(encoding='utf-8')) if record_paths else {}
    completed = record.get('status') == 'execution_completed'
    method_matches = record.get('configuration', {}).get('rank_remedy') == method
    logs_present = log_paths[0].is_file() and len(log_paths) > 1
    report = {'group': group, 'method': method, 'expected_rows': len(reference), 'actual_rows': len(values),
              'complete_finite_aligned_epochs': bool(aligned), 'execution_record_completed': completed,
              'record_method_matches': method_matches, 'log_error_files': log_errors,
              'required_logs_present': logs_present,
              'execution_checks_passed': bool(aligned and completed and method_matches and logs_present and not log_errors),
              'historical_identity_claimed': False}
    output.mkdir(parents=True)
    comparison_html = ''
    if aligned:
        expected = reference[method].to_numpy()
        actual = values[:, 4]
        tau, observed, _, terms = adev(actual)
        _, archived, _, _ = adev(expected)
        report.update({'max_phase_difference_s': float(np.max(np.abs(actual - expected))),
                       'max_adev_relative_difference': float(np.max(np.abs(observed / archived - 1)))})
        table = pd.DataFrame({'tau_s': tau, 'archived_adev': archived, 'rerun_adev': observed,
                              'relative_difference': observed / archived - 1, 'terms': terms})
        table.to_csv(output / 'adev_comparison.csv', index=False, float_format='%.17e')
        fig, ax = plt.subplots(figsize=(8, 5))
        for clock in range(1, 5):
            t, a, _, _ = adev(reference[f'clock{clock}_s'].to_numpy())
            ax.loglog(t, a, '--', lw=.8, label=f'Clock {clock}')
        ax.loglog(tau, archived, 'o-', label=f'{LABELS[method]} archived')
        ax.loglog(tau, observed, 'x--', label=f'{LABELS[method]} rerun')
        ax.set(xlabel='Averaging time (s)', ylabel='Allan deviation')
        ax.grid(True, which='both', alpha=.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(output / 'adev_comparison.png', dpi=180)
        plt.close(fig)
        comparison_html = '<img style="max-width:100%" src="adev_comparison.png" alt="ADEV comparison">' + table.to_html(index=False)
    else:
        comparison_html = '<p>历元不完整、不连续或存在非有限值，未压缩缺测序列来计算 ADEV。请检查解算日志。</p>'
    (output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (output / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>重新解算核对</title>'
        '<main style="max-width:1000px;margin:40px auto;font:16px/1.6 sans-serif"><h1>当前解算与历史归档核对</h1>'
        '<p>execution_checks_passed 仅表示日志与完整性检查通过，不表示与论文或历史版本完全相同。组名是命令行声明值，输入来源仍需核实。</p><pre>'
        + html.escape(json.dumps(report, indent=2)) + '</pre>' + comparison_html + '</main>', encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'Report: {output / "report.html"}')
    return report['execution_checks_passed']


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('fetch'); p.add_argument('--kind',choices=['analysis','inputs'],default='analysis'); p.add_argument('--output',type=Path,required=True); p.add_argument('--archive',type=Path)
    p=commands.add_parser('verify'); p.add_argument('--kind',choices=['analysis','inputs'],default='analysis'); p.add_argument('--data',type=Path,required=True)
    p=commands.add_parser('analyze'); p.add_argument('--data',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p=commands.add_parser('prepare-case'); p.add_argument('--inputs',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--group',choices=[f'{c}_group{i:02d}' for c in CONFIGS for i in range(1,6)],default='mixed_2plus2_group01'); p.add_argument('--method',choices=['NONE',*METHODS],default='GREENHALL')
    p = commands.add_parser('compare-rerun')
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--workdir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--group', choices=[f'{c}_group{i:02d}' for c in CONFIGS for i in range(1,6)], default='mixed_2plus2_group01')
    p.add_argument('--method', choices=METHODS, default='GREENHALL')
    args=parser.parse_args()
    try:
        if args.command=='fetch': fetch(args.kind,args.output.resolve(),args.archive)
        elif args.command=='verify': print(json.dumps(verify(args.data.resolve(),args.kind),indent=2))
        elif args.command=='analyze': analyze(args.data.resolve(),args.output.resolve())
        elif args.command == 'compare-rerun':
            passed = compare_rerun(args.data.resolve(), args.workdir.resolve(), args.group, args.method, args.output.resolve())
            return 0 if passed else 2
        else: prepare_case(args.inputs.resolve(),args.output.resolve(),args.group,args.method)
        return 0
    except (OSError,ValueError,KeyError,zipfile.BadZipFile) as error:
        print(f'ERROR: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
