
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable

import numpy as np
import matplotlib.pyplot as plt

# 可选：如果用户环境装有 scienceplots，则开启；否则忽略
try:
    import scienceplots  # noqa: F401
    plt.style.use(["science"])  # type: ignore
except Exception:  # pragma: no cover
    pass

# =============================
# 配置与基础结构
# =============================

@dataclass
class SchemaConfig:
    """文件解析与分析配置。

    参数
    ------
    trend_state: int
        2: 估计项包含 (estimate_phase, estimate_frequency)
        3: 估计项包含 (estimate_phase, estimate_frequency, estimate_aging)
        4: 估计项包含 (estimate_total_phase, estimate_phase, estimate_frequency, estimate_aging)
        注意：列索引仍按完整格式给出，见 parse 逻辑说明。
    num_harmonics: int
        谐波对 (a_k, b_k) 的数量；0 表示无谐波列。
    dev_mode: str
        Allan 类稳定度类型："adev" | "mdev" | "hdev"，默认 "adev"。
        与下方 compute/plot 系列函数联动，未显式指定时将采用该值。
    rate_hz: Optional[float]
        采样率。如果为 None，则根据 seconds 自动估计为 1 / median(diff(seconds))。
    """

    trend_state: int = 4
    num_harmonics: int = 0
    dev_mode: str = "adev"
    rate_hz: Optional[float] = None


# =============================
# 读取与解析
# =============================

def _parse_line(parts: List[str], cfg: SchemaConfig) -> Optional[dict]:
    """按给定配置解析一行。

    假定基础列顺序（与用户提供示例一致）：
    0:year 1:month 2:day 3:seconds 4:origin_phase 5:origin_frequency 6:origin_aging
    7:estimate_total_phase 8:estimate_phase 9:estimate_frequency 10:estimate_aging
    之后是谐波列：11:a1 12:b1 13:a2 14:b2 ...

    当 trend_state < 4 时，不强制要求使用 estimate_total_phase，但仍允许其存在。
    若文件确实缺失某些列，将自动进行可用性检查。
    """
    try:
        year = int(parts[0]); month = int(parts[1]); day = int(parts[2])
        seconds = float(parts[3])
        origin_phase = float(parts[4])
        origin_frequency = float(parts[5])
        origin_aging = float(parts[6])
    except Exception:
        return None

    # 估计量列：尽量按完整索引读取，不存在则置为 None
    def _get_float(idx: int) -> Optional[float]:
        return float(parts[idx]) if len(parts) > idx and parts[idx] not in (None, "",) else None

    if cfg is not None:
        if cfg.trend_state ==4:
            est_total = _get_float(7)
            est_phase = _get_float(8)
            est_freq = _get_float(9)
            est_aging = _get_float(10)
        elif cfg.trend_state ==3:
            est_phase = _get_float(7)
            est_freq = _get_float(8)
            est_aging = _get_float(9)
        elif cfg.trend_state ==2:
            est_phase = _get_float(7)
            est_freq = _get_float(8)

    record = {
        "year": year,
        "month": month,
        "day": day,
        "seconds": seconds,
        "origin_phase": origin_phase,
        "origin_frequency": origin_frequency,
        "origin_aging": origin_aging,
    }

    # 根据 trend_state 决定放入哪些估计量键
    if cfg.trend_state == 2:
        if est_phase is not None:
            record["estimate_phase"] = est_phase
        if est_freq is not None:
            record["estimate_frequency"] = est_freq
    elif cfg.trend_state == 3:
        if est_phase is not None:
            record["estimate_phase"] = est_phase
        if est_freq is not None:
            record["estimate_frequency"] = est_freq
        if est_aging is not None:
            record["estimate_aging"] = est_aging
    elif cfg.trend_state == 4:
        if est_total is not None:
            record["estimate_total_phase"] = est_total
        if est_phase is not None:
            record["estimate_phase"] = est_phase
        if est_freq is not None:
            record["estimate_frequency"] = est_freq
        if est_aging is not None:
            record["estimate_aging"] = est_aging
    else:
        raise ValueError(f"Unsupported trend_state: {cfg.trend_state}")

    # 解析谐波列
    if cfg.num_harmonics > 0:
        a_list, b_list = [], []
        base = 11
        for k in range(cfg.num_harmonics):
            a_idx = base + 2 * k
            b_idx = base + 2 * k + 1
            if len(parts) > b_idx:
                try:
                    a_list.append(float(parts[a_idx]))
                    b_list.append(float(parts[b_idx]))
                except Exception:
                    a_list.append(np.nan)
                    b_list.append(np.nan)
            else:
                a_list.append(np.nan)
                b_list.append(np.nan)
        record["a_coeffs"] = a_list
        record["b_coeffs"] = b_list

        # 幅度：sqrt(a^2 + b^2)
        a_arr = np.asarray(a_list, dtype=float)
        b_arr = np.asarray(b_list, dtype=float)
        amp_arr = np.sqrt(a_arr * a_arr + b_arr * b_arr)
        # 若 a 或 b 为 NaN，则幅度置为 NaN
        amp_arr[~np.isfinite(a_arr) | ~np.isfinite(b_arr)] = np.nan
        record["ab_amp"] = amp_arr.tolist()

    return record

def read_simu_file(filepath):
    header = {}
    data = []

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    with open(filepath, 'r') as f:
        header_done = False
        for line in f:
            line = line.strip()
            if not line:
                continue
            if not header_done:
                if line == "# Header End":
                    header_done = True
                    continue
                if ':' in line:
                    key, value = line.split(":", 1)
                    header[key.strip()] = value.strip()
            else:
                try:
                    data.append(float(line))
                except ValueError:
                    continue  # 跳过不能转换为浮点数的行

    return {"header": header, "data": data}


def read_simu_results_file(filepath: str, cfg: SchemaConfig) -> List[dict]:
    data: List[dict] = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            rec = _parse_line(parts, cfg)
            if rec is not None:
                data.append(rec)
    return data


def load_all_data(filepaths: Iterable[str], cfg: SchemaConfig) -> Dict[str, List[dict]]:
    data_dict: Dict[str, List[dict]] = {}
    for path in filepaths:
        name = os.path.splitext(os.path.basename(path))[0]
        data_dict[name] = read_simu_results_file(path, cfg)
    return data_dict


# =============================
# 序列抽取工具
# =============================

def _extract_series(data_dict: Dict[str, List[dict]], key: str) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {}
    for name, recs in data_dict.items():
        vals = [r[key] for r in recs if key in r]
        if len(vals) > 0:
            out[name] = np.asarray(vals, dtype=float)
    return out


def extract_time_seconds(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "seconds")


def extract_origin_phase(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "origin_phase")


def extract_origin_frequency(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "origin_frequency")


def extract_origin_aging(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "origin_aging")

def extract_estimate_total_phase(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "estimate_total_phase")

def extract_estimate_phase(
    data_dict: Dict[str, List[dict]],
    cfg: Optional[SchemaConfig] = None
) -> Dict[str, np.ndarray]:
    """
    - 若 cfg.trend_state == 4: 优先 'estimate_total_phase'，缺失则回退 'estimate_phase'
    - 若 cfg.trend_state in {2,3}：使用 'estimate_phase'
    - 若 cfg 为 None: 使用 'estimate_phase'
    """
    if cfg is not None:
        if cfg.trend_state == 4:
            out = _extract_series(data_dict, "estimate_total_phase")
            return out if out else _extract_series(data_dict, "estimate_phase")
        else:
            return _extract_series(data_dict, "estimate_phase")
    else:
        return _extract_series(data_dict, "estimate_phase")


def extract_estimate_frequency(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "estimate_frequency")


def extract_estimate_aging(data_dict: Dict[str, List[dict]]) -> Dict[str, np.ndarray]:
    return _extract_series(data_dict, "estimate_aging")


def extract_harmonics(
    data_dict: Dict[str, List[dict]],
    k: int
) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """
    提取第 k 个谐波系数 (a_k, b_k) 及其幅度 amp_k = sqrt(a_k^2 + b_k^2)，k 从 1 开始。

    返回:
        a_out[name] -> np.ndarray([... a_k_t ...])
        b_out[name] -> np.ndarray([... b_k_t ...])
        amp_out[name] -> np.ndarray([... amp_k_t ...])
    """
    a_out: Dict[str, List[float]] = {}
    b_out: Dict[str, List[float]] = {}
    amp_out: Dict[str, List[float]] = {}

    idx = k - 1
    for name, recs in data_dict.items():
        a_vals, b_vals, amp_vals = [], [], []
        for r in recs:
            a_list = r.get("a_coeffs")
            b_list = r.get("b_coeffs")
            # 优先使用已存好的幅度（若有）
            amp_list = r.get("ab_amp")

            if a_list is None or b_list is None:
                continue
            if len(a_list) <= idx or len(b_list) <= idx:
                continue

            a_k = a_list[idx]
            b_k = b_list[idx]
            a_vals.append(float(a_k))
            b_vals.append(float(b_k))

            if amp_list is not None and len(amp_list) > idx:
                amp_k = amp_list[idx]
                amp_vals.append(float(amp_k))
            else:
                # 现场计算，等价于 sqrt(a^2+b^2)，对数值更稳健
                amp_vals.append(float(np.hypot(a_k, b_k)))

        if a_vals:  # 有数据再写入字典
            a_out[name] = np.asarray(a_vals, dtype=float)
            b_out[name] = np.asarray(b_vals, dtype=float)
            # 对 NaN 做一次统一处理：若 a/b 不是有限数，则幅度置 NaN
            amp_arr = np.asarray(amp_vals, dtype=float)
            mask_bad = ~np.isfinite(a_out[name]) | ~np.isfinite(b_out[name])
            if mask_bad.any():
                amp_arr[mask_bad] = np.nan
            amp_out[name] = amp_arr

    return a_out, b_out, amp_out


# =============================
# 时间轴构建（连续）
# =============================
from datetime import datetime, timedelta

def _sort_records_by_time(recs: List[dict]) -> List[dict]:
    """按 (year, month, day, seconds) 升序排序，避免乱序导致的回溯。
    若键缺失将抛出 KeyError。"""
    return sorted(
        recs,
        key=lambda r: (int(r["year"]), int(r["month"]), int(r["day"]), float(r["seconds"]))
    )


def build_continuous_time_seconds_for_one(
    recs: List[dict], *, sort: bool = True
) -> np.ndarray:
    """将单个卫星记录的 (year, month, day, seconds-of-day) 合成为首样本为零点的连续时间轴（单位：秒）。

    参数
    ------
    recs : List[dict]
        单星全部记录（read_simu_file 读取结果中的某个 name 的列表）。
    sort : bool
        是否按时间排序。默认 True，推荐开启以避免乱序导致的时间回绕。

    返回
    ------
    np.ndarray
        与 recs 等长的连续时间（秒），以首个样本为 0 参考。
    """
    if not recs:
        return np.asarray([], dtype=float)

    if sort:
        recs = _sort_records_by_time(recs)

    t0 = None
    out = []
    for r in recs:
        y = int(r["year"]); m = int(r["month"]); d = int(r["day"])  # 可能抛 KeyError，便于尽早暴露格式问题
        sod = float(r["seconds"])  # seconds-of-day
        dt = datetime(y, m, d) + timedelta(seconds=sod)
        if t0 is None:
            t0 = dt
        out.append((dt - t0).total_seconds())
    return np.asarray(out, dtype=float)


def build_continuous_time_seconds(
    data_dict: Dict[str, List[dict]], *, sort: bool = True
) -> Dict[str, np.ndarray]:
    """对多颗卫星批量生成连续时间轴（秒）。键为卫星名，值为连续时间数组。"""
    out: Dict[str, np.ndarray] = {}
    for name, recs in data_dict.items():
        out[name] = build_continuous_time_seconds_for_one(recs, sort=sort)
    return out


def build_continuous_time_hours(
    data_dict: Dict[str, List[dict]], *, sort: bool = True
) -> Dict[str, np.ndarray]:
    """与 build_continuous_time_seconds 相同，但返回单位为小时。"""
    secs = build_continuous_time_seconds(data_dict, sort=sort)
    return {k: v / 3600.0 for k, v in secs.items()}


# =============================
# Allan 类稳定度计算
# =============================

try:
    import allantools
except Exception as e:  # pragma: no cover
    raise ImportError("allantools 未安装，请先 pip install allantools") from e


def _guess_rate_hz(seconds: np.ndarray) -> Optional[float]:
    if seconds.size < 2:
        return None
    diffs = np.diff(seconds)
    med = np.median(diffs)
    if med > 0:
        return 1.0 / med
    return None


def _select_dev_fn(mode: str):
    mode = mode.lower()
    if mode == "adev":
        return allantools.adev
    if mode == "mdev":
        return allantools.mdev
    if mode == "hdev":
        return allantools.hdev
    raise ValueError(f"Unsupported deviation type: {mode}")


def _resolve_mode(mode: Optional[str], cfg: Optional[SchemaConfig]) -> str:
    """若 mode 未给出，则优先使用 cfg.dev_mode，否则默认 "adev"。"""
    if mode is None:
        if cfg is not None and isinstance(cfg.dev_mode, str):
            return cfg.dev_mode.lower()
        return "adev"
    return mode.lower()


def compute_dev(series_dict: Dict[str, np.ndarray],
                time_dict: Optional[Dict[str, np.ndarray]] = None,
                rate_hz: Optional[float] = None,
                mode: Optional[str] = None,
                cfg: Optional[SchemaConfig] = None) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """对若干个序列分别计算稳定度。

    参数
    ------
    series_dict: Dict[str, np.ndarray]
        需要计算的序列，例如 origin_phase 或 estimate_phase 等。
    time_dict: Optional[Dict[str, np.ndarray]]
        可选，若提供则优先用来自动估计采样率。
    rate_hz: Optional[float]
        若提供则使用该值；否则尝试从 time_dict 估计；仍不可得时默认 0.1 Hz。
    mode: Optional[str]
        "adev" | "mdev" | "hdev"；若为 None，则使用 cfg.dev_mode 或默认 "adev"。
    cfg: Optional[SchemaConfig]
        若提供，将用于解析 dev_mode 以及默认 rate_hz。
    """
    out: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    mode_use = _resolve_mode(mode, cfg)
    dev_fn = _select_dev_fn(mode_use)

    for name, arr in series_dict.items():
        arr = np.asarray(arr, dtype=float)

        # rate 优先级：参数 > cfg.rate_hz > 从时间估计 > 0.1
        rate_use = rate_hz if rate_hz is not None else (cfg.rate_hz if cfg is not None else None)
        if rate_use is None and time_dict is not None and name in time_dict:
            rate_use = _guess_rate_hz(np.asarray(time_dict[name], dtype=float))
        if rate_use is None:
            rate_use = 0.1
        taus, sigmas, errors, _ = dev_fn(arr, rate=rate_use)
        out[name] = (taus, sigmas, errors)
    return out


# =============================
# 可视化
# =============================

def plot_series(
    origin_series: Optional[Dict[str, np.ndarray]] = None,
    estimate_series: Optional[Dict[str, np.ndarray]] = None,
    *,
    # 新增：只画一组序列（如残差）
    series_only: Optional[Dict[str, np.ndarray]] = None,
    series_only_label: str = "series",
    # 时间轴
    time_seconds: Optional[Dict[str, np.ndarray]] = None,
    x_in_hours: bool = False,
    # 视觉与文字
    title: str = "Time Series",
    ylabel: str = "Value (unit)",
    # 新增：外观控制
    origin_style: str = "--",
    estimate_style: str = "-",
    series_only_style: str = "-",
    linewidth: float = 1.3,
) -> None:
    """
    通用时间序列绘图：
    1) 兼容旧用法：传 origin_series 与 estimate_series -> 画两条对比曲线。
    2) 新用法：只传 series_only（例如残差） -> 只画一条曲线。
    3) 自动以同名键对齐，长度按最短截齐；若提供 time_seconds，则用其作为横轴，否则用 epoch 索引。
    """
    plt.figure(figsize=(6, 4))

    def _safe(d: Optional[Dict[str, np.ndarray]]) -> Dict[str, np.ndarray]:
        return d if isinstance(d, dict) else {}

    origin_series = _safe(origin_series)
    estimate_series = _safe(estimate_series)
    series_only = _safe(series_only)
    time_seconds = _safe(time_seconds) if isinstance(time_seconds, dict) else {}

    # 情况 A：只画 series_only（比如残差）
    if series_only and not origin_series and not estimate_series:
        any_drawn = False
        for name, y in series_only.items():
            y = np.asarray(y, dtype=float)
            n = len(y)
            if n == 0:
                continue
            if name in time_seconds:
                t = np.asarray(time_seconds[name], dtype=float)[:n]
                x = (t / 3600.0) if x_in_hours else t
                xlabel = "Time (h)" if x_in_hours else "Time (s)"
            else:
                x = np.arange(n, dtype=float)
                xlabel = "Epoch Index"
            plt.plot(x, y[:len(x)], series_only_style, linewidth=linewidth,
                     label=f"{name} - {series_only_label}")
            any_drawn = True

        if not any_drawn:
            plt.xlabel("Epoch Index"); plt.ylabel(ylabel)
            plt.title(title); plt.grid(True); plt.tight_layout(); plt.show()
            return

        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.title(title)
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.show()
        return

    # 情况 B：对比 origin vs estimate（旧用法）
    if origin_series or estimate_series:
        # 用并集取名，再在循环里做“都有才画”
        names = sorted(set(origin_series.keys()).union(estimate_series.keys()))
        if not names:
            plt.xlabel("Epoch Index"); plt.ylabel(ylabel)
            plt.title(title); plt.grid(True); plt.tight_layout(); plt.show()
            return

        any_drawn = False
        for name in names:
            if name not in origin_series or name not in estimate_series:
                continue
            y1 = np.asarray(origin_series[name], dtype=float)
            y2 = np.asarray(estimate_series[name], dtype=float)
            n = min(len(y1), len(y2))
            if n == 0:
                continue
            y1 = y1[:n]; y2 = y2[:n]

            if name in time_seconds:
                t = np.asarray(time_seconds[name], dtype=float)[:n]
                x = (t / 3600.0) if x_in_hours else t
                xlabel = "Time (h)" if x_in_hours else "Time (s)"
            else:
                x = np.arange(n, dtype=float)
                xlabel = "Epoch Index"

            plt.plot(x, y2, estimate_style, linewidth=linewidth, label=f"{name} - estimate")
            plt.plot(x, y1, origin_style,   linewidth=linewidth, label=f"{name} - origin")
            any_drawn = True

        if not any_drawn:
            plt.xlabel("Epoch Index"); plt.ylabel(ylabel)
            plt.title(title); plt.grid(True); plt.tight_layout(); plt.show()
            return

        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.title(title)
        plt.grid(True)
        plt.legend()
        plt.tight_layout()
        plt.show()
        return

    # 情况 C：什么都没传
    plt.xlabel("Epoch Index")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    plt.show()



def plot_dev(origin_dev: Optional[Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]] = None,
             estimate_dev: Optional[Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]] = None,
             residual_dev: Optional[Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]] = None,
             sigmatype: Optional[str] = None,
             cfg: Optional[SchemaConfig] = None,
             x_lim: Optional[Tuple[float, float]] = None,
             y_lim: Optional[Tuple[float, float]] = None,
             legend_cols: Optional[int] = 3,
             merge_origin_label: bool = False,
             origin_group_label: Optional[str] = None) -> None:
    """稳定度对比作图。若 sigmatype 未给定，则使用 cfg.dev_mode 或默认 "adev"。

    当 origin_dev 包含很多卫星时，可用 merge_origin_label 将卫星图例合并为一项。
    """
    plt.figure(figsize=(6, 5))

    # 统一颜色映射
    names = set()
    for d in (origin_dev, estimate_dev, residual_dev):
        if d:
            names.update(list(d.keys()))
    names = sorted(list(names))
    palette = ['#0C5DA5', '#FF2C00', '#00B945', '#FF9500', '#845B97', '#474747', '#9e9e9e']
    name_to_color = {n: palette[i % len(palette)] for i, n in enumerate(names)}

    def _plot_one(
        d: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]],
        label_suffix: str,
        marker: str,
        group_label: Optional[str] = None,
    ):
        first_visible = True
        for name, (taus, sigmas, _errors) in d.items():
            if taus is None or len(taus) == 0:
                continue
            label = f"{name} - {label_suffix}"
            if group_label is not None:
                label = group_label if first_visible else "_nolegend_"
                first_visible = False
            plt.plot(taus, sigmas, marker, label=label, color=name_to_color[name])

    if origin_dev:
        origin_label = None
        if merge_origin_label:
            origin_label = origin_group_label or f"Origin satellites (n={len(origin_dev)})"
        _plot_one(origin_dev, "origin", 's--', group_label=origin_label)
    if estimate_dev:
        _plot_one(estimate_dev, "estimate", 'o-')
    if residual_dev:
        _plot_one(residual_dev, "residual", 'x:')

    # 解析稳定度类型
    mode_label = (sigmatype or (cfg.dev_mode if cfg is not None else "adev")).upper()

    plt.xscale("log"); plt.yscale("log")
    if y_lim is not None:
        plt.ylim(list(y_lim))
    if x_lim is not None:
        plt.xlim(list(x_lim))
    plt.xlabel("Tau (s)")
    plt.ylabel(mode_label)
    plt.title(f"{mode_label} Stability Comparison")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    handles, labels = plt.gca().get_legend_handles_labels()
    if handles:
        if legend_cols is None:
            plt.legend()
        else:
            plt.legend(ncol=legend_cols)
    plt.tight_layout()
    return plt

#============================
# 记录截断
#============================
from typing import Dict, List, Optional

def truncate_records(
    data_dict: Dict[str, List[dict]],
    discard: int = 0,
    max_len: Optional[int] = None,
    select_ids: Optional[List[str]] = None,
    drop_empty: bool = True,
) -> Dict[str, List[dict]]:
    """
    对多星记录做统一“丢弃起始样本 + 限制最大长度”的截断，返回新的数据字典。

    参数
    ------
    data_dict : Dict[str, List[dict]]
        形如 { "G15": [record1, record2, ...], ... } 的数据字典。
    discard : int
        丢弃每颗卫星开头的样本个数，默认 0。
    max_len : Optional[int]
        截断后的最大样本数；为 None 则不限制。
    select_ids : Optional[List[str]]
        若提供，只处理并返回这些键；否则对 data_dict 的所有键生效。
    drop_empty : bool
        截断后若序列为空，是否从结果中剔除该键。默认 True。

    返回
    ------
    Dict[str, List[dict]]
        截断后的新字典（不会修改输入 data_dict）。
    """
    if discard < 0:
        raise ValueError("discard 不能为负数")
    if max_len is not None and max_len < 0:
        raise ValueError("max_len 不能为负数")

    keys = select_ids if select_ids is not None else list(data_dict.keys())
    out: Dict[str, List[dict]] = {}

    for k in keys:
        recs = data_dict.get(k, [])
        if not recs:
            # 原数据不存在或为空，跳过
            if not drop_empty:
                out[k] = []
            continue

        # 先丢弃，再限长
        recs2 = recs[discard:] if discard > 0 else list(recs)
        if max_len is not None:
            recs2 = recs2[:max_len]

        if recs2 or not drop_empty:
            out[k] = recs2

    return out


# ============================
# 残差计算与对齐工具
# ============================

from enum import Enum

class AlignMode(str, Enum):
    """序列对齐策略：
    - 'truncate': 取同名序列最小长度并对齐头部（速度快，适合源自同一记录流）
    - 'time': 基于 seconds 的交集时间戳对齐（更稳健，适合存在缺失/重排）
    """
    TRUNCATE = "truncate"
    TIME = "time"


def _pairwise_residual(
    origin: Dict[str, np.ndarray],
    estimate: Dict[str, np.ndarray],
    *,
    align: AlignMode = AlignMode.TRUNCATE,
    time_seconds: Optional[Dict[str, np.ndarray]] = None
) -> Dict[str, np.ndarray]:
    """
    对同名序列做 residual = origin - estimate。
    - 对齐：truncate 或基于 seconds 的交集对齐。
    - 对 NaN：保持原样（你也可以在外面先做清洗）。
    """
    out: Dict[str, np.ndarray] = {}
    names = sorted(set(origin.keys()).intersection(estimate.keys()))
    for name in names:
        y1 = np.asarray(origin[name], dtype=float)
        y2 = np.asarray(estimate[name], dtype=float)

        if align == AlignMode.TRUNCATE:
            n = min(len(y1), len(y2))
            if n > 0:
                out[name] = y1[:n] - y2[:n]
        else:
            if time_seconds is None or name not in time_seconds:
                # 回退到 truncate
                n = min(len(y1), len(y2))
                if n > 0:
                    out[name] = y1[:n] - y2[:n]
            else:
                t = np.asarray(time_seconds[name], dtype=float)
                # 两个序列可能等长/共时采样；若确有丢失，需要用户分别提供各自 time_dict。
                # 这里假设 origin/estimate 同步采样，直接 truncate 即可。
                n = min(len(y1), len(y2), len(t))
                if n > 0:
                    out[name] = y1[:n] - y2[:n]
    return out


def compute_residuals_all(
    data_dict: Dict[str, List[dict]],
    cfg: Optional[SchemaConfig] = None,
    *,
    align: AlignMode = AlignMode.TRUNCATE
) -> Tuple[
    Dict[str, np.ndarray],  # phase residuals
    Dict[str, np.ndarray],  # frequency residuals
    Dict[str, np.ndarray]   # aging residuals
]:
    """
    直接从 data_dict 中抽取“原始 vs 估计”的三类序列并计算残差：
    - phase: origin_phase - estimate_phase (四状态优先采用 estimate_total_phase)
    - frequency: origin_frequency - estimate_frequency
    - aging: origin_aging - estimate_aging
    """
    # 抽取
    time_dict = extract_time_seconds(data_dict)
    origin_phase = extract_origin_phase(data_dict)
    origin_freq  = extract_origin_frequency(data_dict)
    origin_aging = extract_origin_aging(data_dict)

    est_phase = extract_estimate_phase(data_dict, cfg=cfg)
    est_freq  = extract_estimate_frequency(data_dict)
    est_aging = extract_estimate_aging(data_dict)

    # 计算残差
    res_phase = _pairwise_residual(origin_phase, est_phase, align=align, time_seconds=time_dict)
    res_freq  = _pairwise_residual(origin_freq,  est_freq,  align=align, time_seconds=time_dict)
    res_aging = _pairwise_residual(origin_aging, est_aging, align=align, time_seconds=time_dict)
    return res_phase, res_freq, res_aging



def load_iem_to_standard_dict(filepath: str):
    """
    适配器：顺序读取变长 IEM 文件。
    格式: Year Month Day SoD [SatID Diff] [SatID Diff] ... [IEM Val]

    逻辑：从时间列之后开始遍历，遇到卫星读卫星，遇到 "IEM" 读 IEM 并结束。
    """
    import pandas as pd
    import os
    import numpy as np
    from datetime import datetime, timedelta

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    records = []
    base_time = None

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('%'): continue

            parts = line.split()
            # 最小长度检查：4个时间 + 至少(IEM + Val) = 6
            if len(parts) < 6: continue

            # 1. 解析基础时间
            try:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                sod = float(parts[3])
            except ValueError:
                continue

            dt = datetime(y, m, d) + timedelta(seconds=sod)
            if base_time is None: base_time = dt
            t_rel = (dt - base_time).total_seconds()

            row = {'_time': t_rel}

            # 2. 顺序解析剩余部分
            # 从索引 4 开始 (第5列)
            idx = 4
            while idx < len(parts):
                token = parts[idx]

                if token == "IEM":
                    # === 遇到 IEM 标识符，读取数值并结束 ===
                    if idx + 1 < len(parts):
                        try:
                            row['Ensemble'] = float(parts[idx+1])
                        except ValueError:
                            pass # 或者设为 NaN
                    break # IEM 位于最后，读完即可退出循环

                else:
                    # === 默认为卫星 ID ===
                    # 检查是否有对应的 Diff 值
                    if idx + 1 < len(parts):
                        try:
                            val = float(parts[idx+1])
                            # 记录卫星数据
                            row[f'Sat_{token}'] = val
                        except ValueError:
                            pass
                    # 跳过 [ID, Val] 这两列，继续处理下一个
                    idx += 2

            records.append(row)

    # 3. Pandas 对齐与转换
    df = pd.DataFrame(records)
    if df.empty: return {}, {}

    df.set_index('_time', inplace=True)
    df.sort_index(inplace=True)

    series_dict = {}
    time_dict = {}
    time_arr = df.index.values

    for col in df.columns:
        series_dict[col] = df[col].values
        time_dict[col] = time_arr

    return series_dict, time_dict
