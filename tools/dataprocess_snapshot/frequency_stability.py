import os
import numpy as np
import matplotlib.pyplot as plt

# 假设 SchemaConfig, load_iem_to_standard_dict, compute_dev,
# load_all_data, extract_origin_phase, plot_dev 都已在上下文定义或引入

# ==============================================================================
# 1. 配置区
# ==============================================================================
base_path = REPORT_BASE_PATH
iem_filename = "IEM.txt"
iem_full_path = os.path.join(base_path, iem_filename)

# 指定需要对比的原始卫星ID
sat_ids_origin = REPORT_ORIGIN_IDS

# 配置 ADEV 计算参数
cfg = REPORT_SCHEMA

# ------------------------------------------------------------------------------
# 【控制开关】
# ------------------------------------------------------------------------------
SHOW_ENSEMBLE  = True   # True: 计算并绘制 IEM (Ensemble) 曲线; False: 跳过
SHOW_RESIDUALS = False   # True: 计算并绘制钟差 (Residuals) 曲线; False: 跳过
SHOW_LAST_COL  = False   # True: 绘制 IEM.txt 最后一列的稳定度曲线; False: 跳过
# ------------------------------------------------------------------------------

# ==============================================================================
# 2. 第一部分：尝试处理 IEM 文件 (Ensemble 和 Residuals)
# ==============================================================================
ens_dev_results = None
res_dev_results = None

need_process_iem = (SHOW_ENSEMBLE or SHOW_RESIDUALS)

if need_process_iem:
    if os.path.exists(iem_full_path):
        print(f"Loading IEM data from {iem_full_path}...")
        iem_series, _ = load_iem_to_standard_dict(iem_full_path)

        if iem_series:
            def clean_nan(d):
                clean = {}
                for k, v in d.items():
                    valid = v[np.isfinite(v)]
                    if len(valid) > 10:
                        clean[k] = valid
                return clean

            if SHOW_ENSEMBLE:
                print("Processing Ensemble data...")
                ensemble_data = {k: v for k, v in iem_series.items() if k == 'Ensemble'}
                ensemble_data_clean = clean_nan(ensemble_data)
                if ensemble_data_clean:
                    print("Computing ADEV for Ensemble...")
                    ens_dev_results = compute_dev(ensemble_data_clean, cfg=cfg)
                else:
                    print("Warning: Ensemble data found but invalid (too short or all NaNs).")

            if SHOW_RESIDUALS:
                print("Processing Residuals data...")
                residual_data = {k: v for k, v in iem_series.items() if k != 'Ensemble'}
                residual_data_clean = clean_nan(residual_data)
                if residual_data_clean:
                    print("Computing ADEV for Residuals...")
                    res_dev_results = compute_dev(residual_data_clean, cfg=cfg)
                else:
                    print("Warning: Residual data found but invalid.")
        else:
            print("IEM.txt 存在但在读取时为空，跳过 IEM 处理。")
    else:
        print(f"Warning: {iem_filename} 不存在。无法绘制 IEM 或 Residuals。")
else:
    print("User config: Skipping IEM and Residuals processing.")


# ==============================================================================
# 2.5 读取 IEM.txt 最后一列
# ==============================================================================
last_col_dev_results = None

if SHOW_LAST_COL:
    if os.path.exists(iem_full_path):
        print("Reading last column from IEM.txt...")
        last_col_vals = []
        with open(iem_full_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('%') or line.startswith('#'):
                    continue
                parts = line.split()
                try:
                    last_col_vals.append(float(parts[-1]))
                except (ValueError, IndexError):
                    continue
        if len(last_col_vals) > 10:
            last_col_arr = np.array(last_col_vals)
            last_col_arr = last_col_arr[np.isfinite(last_col_arr)]
            print(f"  读取到 {len(last_col_arr)} 个有效数据点，计算 ADEV...")
            last_col_dev_results = compute_dev({"IEM Last Col": last_col_arr}, cfg=cfg)
        else:
            print("Warning: IEM.txt 最后一列有效数据不足。")
    else:
        print(f"Warning: {iem_filename} 不存在，跳过最后一列处理。")


# ==============================================================================
# 3. 第二部分：处理单星原始文件 (Origin) - 【始终执行】
# ==============================================================================
print(f"Loading Origin Satellite data for: {sat_ids_origin}...")
sat_filepaths = [os.path.join(base_path, f"{sid}.txt") for sid in sat_ids_origin]

origin_data_dict = load_all_data(sat_filepaths, cfg)
origin_phase_data = extract_origin_phase(origin_data_dict)

print("Computing ADEV for Origin Satellites...")
origin_dev_results = compute_dev(origin_phase_data, cfg=cfg)


# ==============================================================================
# 4. 稳定度作图
# ==============================================================================
print("Plotting...")

plot_dev(
    origin_dev=origin_dev_results,
    residual_dev=res_dev_results,
    estimate_dev=ens_dev_results,
    cfg=cfg,
    legend_cols=None
)

# 叠加最后一列曲线
if last_col_dev_results:
    for name, (taus, sigmas, _) in last_col_dev_results.items():
        if taus is not None and len(taus) > 0:
            plt.plot(taus, sigmas, 'D-.', label=name, color='#845B97')
    plt.legend(ncol=3)

# 动态生成标题
title_parts = ["Origin"]
if ens_dev_results:
    title_parts.append("Ensemble")
if res_dev_results:
    title_parts.append("Residuals")
if last_col_dev_results:
    title_parts.append("Last Col")

mode_name = cfg.dev_mode.upper()
plt.title(f"Stability Comparison: {' vs '.join(title_parts)} ({mode_name})")

plt.grid(True, which="both", linestyle='--', linewidth=0.5)
plt.tight_layout()
plt.show()
