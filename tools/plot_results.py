"""Read GSTAR text results and draw phase/ADEV figures, independently of lab.py.

Edit the settings below, then run: python tools/plot_results.py
The read/compute/plot functions come from the existing DataProcess notebook.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys

import allantools
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT))
from tools.dataprocess_snapshot import helpers as dp


# ================== 可以直接修改的绘图设置 ==================
RESULTS_DIR = REPO_ROOT / "Runs/manual_case/results"  # IEM.txt、SIM*.txt 所在目录
OUTPUT_DIR = None  # None：在结果目录旁创建 figures/ 和 analysis/；也可填 Path(...)
CLOCK_IDS = ["SIM1", "SIM2", "SIM3", "SIM4"]  # 读取同名 .txt，默认四只原始钟
SAMPLE_INTERVAL_S = 10.0  # 与结果实际采样间隔一致；采样率 = 1 / 间隔
TREND_STATE = 2  # 对应 Timescale.cfg 的 Clock Trend state num
NUM_HARMONICS = 0  # 对应 Clock Harmonics state num
TARGET_TAUS_S = [10, 30, 100, 300, 1000, 3000, 10000, 30000, 86400]
PHASE_ZERO_FIRST = True  # 相位图减去各自首值便于比较；CSV 始终保存原值
FIGURE_FORMATS = ("png", "pdf", "svg")
# ===========================================================


def read_epochs(path: Path) -> np.ndarray:
    """Read dates as well as seconds-of-day, so midnight and shifted dates are safe."""
    epochs = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            parts = line.split()
            if not parts or parts[0].startswith(("#", "%")):
                continue
            try:
                epoch = datetime(*map(int, parts[:3])) + timedelta(seconds=float(parts[3]))
                if path.name == "IEM.txt" and parts[-2] != "IEM":
                    raise ValueError("Missing IEM marker")
            except (ValueError, OverflowError, IndexError, TypeError) as error:
                raise ValueError(f"Invalid result row: {path}:{number}") from error
            epochs.append(epoch)
    return np.asarray(epochs, dtype="datetime64[us]")


def load_results(results: Path, clock_ids: list[str], cfg: dp.SchemaConfig) -> tuple[np.ndarray, dict]:
    """Use original clock phases, not the clock-minus-ensemble columns in IEM.txt."""
    if not clock_ids or len(set(clock_ids)) != len(clock_ids) or "Ensemble" in clock_ids:
        raise ValueError("List each clock once; Ensemble is added automatically")
    if any(Path(name).name != name or "/" in name or "\\" in name for name in clock_ids):
        raise ValueError("Clock IDs must be file stems such as SIM1")
    iem = results / "IEM.txt"
    times = read_epochs(iem)
    if len(times) < 12:
        raise ValueError("At least 12 result epochs are needed")
    differences = np.diff(times) / np.timedelta64(1, "s")
    if not np.allclose(differences, 1 / cfg.rate_hz, rtol=0, atol=1e-6):
        raise ValueError("IEM epochs have gaps/duplicates or do not match --interval")
    files = [results / f"{name}.txt" for name in clock_ids]
    for path in files:
        if not np.array_equal(read_epochs(path), times):
            raise ValueError(f"Epochs differ between IEM.txt and {path.name}; check dates and missing rows")

    # 与 DataProcess 频稳单元相同的读取函数。
    raw = dp.load_all_data([str(path) for path in files], cfg)
    series = dp.extract_origin_phase(raw)
    iem_series, _ = dp.load_iem_to_standard_dict(str(iem))
    if set(series) != set(clock_ids) or "Ensemble" not in iem_series:
        raise ValueError("A requested clock or ensemble phase is missing")
    series["Ensemble"] = iem_series["Ensemble"]
    for name, values in series.items():
        if len(values) != len(times) or not np.isfinite(values).all():
            raise ValueError(f"Invalid or missing phase values: {name}")
    return times, series


def write_adev_table(path: Path, series: dict, rate: float, taus: object) -> None:
    """Export directly calculated values, uncertainty estimates and term counts."""
    rows = []
    for name, phase in series.items():
        if not isinstance(taus, str) and len(taus) == 0:
            break
        tau, sigma, error, count = allantools.adev(phase, rate=rate, data_type="phase", taus=taus)
        rows.extend((name, t, a, e, int(n)) for t, a, e, n in zip(tau, sigma, error, count))
    pd.DataFrame(rows, columns=["series", "tau_s", "adev", "adev_error", "sample_count"]).to_csv(
        path, sep="\t", index=False, float_format="%.17e")


def plot_results(results: Path, output: Path, clock_ids: list[str], interval: float,
                 trend_state: int = TREND_STATE, harmonics: int = NUM_HARMONICS) -> dict:
    if not np.isfinite(interval) or interval <= 0:
        raise ValueError("The sample interval must be positive and finite")
    log = results / "gstar.log"
    if log.is_file() and re.search(r"\[(?:error|critical)\]|(?:\*{3}|#{3})\s*error",
                                  log.read_text(encoding="utf-8", errors="replace"), re.I):
        raise ValueError(f"The solver logged an error; inspect {log}")
    cfg = dp.SchemaConfig(trend_state=trend_state, num_harmonics=harmonics,
                          rate_hz=1 / interval, dev_mode="adev")
    times, series = load_results(results, clock_ids, cfg)
    elapsed = (times - times[0]) / np.timedelta64(1, "s")
    figures, analysis = output / "figures", output / "analysis"
    figures.mkdir(parents=True, exist_ok=True)
    analysis.mkdir(parents=True, exist_ok=True)

    # 1. 保存相位原值。时间从本次输出的首个有效历元计起，同时保留实际 GPST 日期。
    pd.DataFrame({"epoch_gpst": times, "elapsed_s": elapsed, **series}).to_csv(
        analysis / "phase.csv", index=False, float_format="%.17e")
    plt.rcParams.update({"text.usetex": False, "font.family": "DejaVu Sans", "font.size": 10,
                         "svg.fonttype": "none", "mathtext.fontset": "dejavusans"})

    # 2. 画相位图。秒转纳秒只用于显示，不改变参与 ADEV 计算的数据。
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for name, phase in series.items():
        displayed = phase - phase[0] if PHASE_ZERO_FIRST else phase
        ax.plot(elapsed / 86400, displayed * 1e9, label=name, lw=1)
    ax.set(xlabel="Days since first output", ylabel="Phase change (ns)" if PHASE_ZERO_FIRST else "Phase (ns)")
    ax.grid(True, alpha=.3)
    ax.legend()
    fig.tight_layout()
    for extension in FIGURE_FORMATS:
        fig.savefig(figures / f"phase.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)

    # 3. 沿用 DataProcess cell 43 的 compute_dev → plot_dev 流程。
    # 全部原始钟 + Ensemble；不画残差，也不把 IEM 的中间列当成原始钟。
    origin_dev = dp.compute_dev({name: series[name] for name in clock_ids}, cfg=cfg)
    ensemble_dev = dp.compute_dev({"Ensemble": series["Ensemble"]}, cfg=cfg)
    dp.plot_dev(origin_dev=origin_dev, estimate_dev=ensemble_dev, cfg=cfg, legend_cols=None)
    fig = plt.gcf()
    fig.axes[0].set_title("Original clocks and ensemble (ADEV)")
    for extension in FIGURE_FORMATS:
        fig.savefig(figures / f"adev.{extension}", dpi=180, bbox_inches="tight")
    plt.close(fig)

    # 4. 导出曲线与指定平均时间的数值；短实验只使用数据长度支持的 τ。
    write_adev_table(analysis / "adev.tsv", series, cfg.rate_hz, "octave")
    target_taus = [tau for tau in TARGET_TAUS_S if tau >= interval
                   and np.isclose(tau / interval, round(tau / interval), rtol=0, atol=1e-9)
                   and (len(times) - 1) // round(tau / interval) - 1 >= 2]
    write_adev_table(analysis / "stability_summary.tsv", series, cfg.rate_hz, target_taus)
    summary = {"results_directory": str(results.resolve()), "series": list(series), "phase_samples": len(times),
               "first_epoch_gpst": str(times[0]), "last_epoch_gpst": str(times[-1]), "interval_s": interval,
               "method": "allantools.adev", "target_taus_s": target_taus,
               "phase_plot_subtracts_first_value": PHASE_ZERO_FIRST,
               "source": "tools/dataprocess_snapshot/helpers.py; DataProcess cells 35 and 43"}
    (analysis / "plot_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Read {len(times)} epochs; plotted {len(series)} curves: {', '.join(series)}")
    print(f"Pictures: {figures.resolve()}")
    print(f"Numbers: {analysis.resolve()}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=RESULTS_DIR, help="Directory containing IEM.txt and clock files")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="Parent directory for figures/ and analysis/")
    parser.add_argument("--clocks", nargs="+", default=CLOCK_IDS, help="Clock file stems, for example SIM1 SIM2 SIM3 SIM4")
    parser.add_argument("--interval", type=float, default=SAMPLE_INTERVAL_S, help="Actual sample interval in seconds")
    parser.add_argument("--trend-state", type=int, default=TREND_STATE)
    parser.add_argument("--harmonics", type=int, default=NUM_HARMONICS)
    args = parser.parse_args()
    try:
        plot_results(args.results.resolve(), (args.output or args.results.parent).resolve(), args.clocks,
                     args.interval, args.trend_state, args.harmonics)
    except (OSError, ValueError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
