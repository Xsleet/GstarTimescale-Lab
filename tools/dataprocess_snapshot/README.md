# DataProcess 频稳单元快照

此目录导出工作区 `Code/DataProcess/LEOTimescale.ipynb` 的零起始 cell 35（helper）和 cell 43（频率稳定度）。目的是让独立克隆 GSTAR 仓库也能复用现有工作流，不要求安装 Jupyter 或获得外部研究工作区。

- `helpers.py`：保留原有解析、`compute_dev`、`plot_dev` 等函数。
- `frequency_stability.py`：保留原有计算与绘图流程，仅将 `base_path`、`sat_ids_origin`、`cfg` 三处配置赋值替换为调用方传入的 `REPORT_*`。
- 导出时统一 LF 并移除行尾空白，没有另写 ADEV 算法或替代绘图函数。
- `provenance.json` 记录原 notebook、两个原 cell 和导出文件的 SHA256。原 notebook 当时含未提交修改，因此以工作文件哈希标识来源。

`run_demo.py` 先检查 IEM 与 SIM1–SIM4 的绝对历元完全相同、连续且数值有限，才执行这些可信仓库代码。调用时指定 `SchemaConfig(trend_state=2, num_harmonics=0, rate_hz=0.1, dev_mode="adev")`；`SHOW_ENSEMBLE=True`，另外两个显示开关为 False。输出严格为四条原始钟和一条 Ensemble 曲线。

原 helper 的 `compute_dev` 使用默认倍频 τ，返回三个数组，不包含有效项数；调用方另用同一个 `allantools.adev` 在曲线 τ 和指定目标 τ 上直接计算并保存第四返回值。不使用最近点或插值代替指定 τ 计算。

`sample_count` 是非重叠 ADEV 使用的二阶差分项数，不是相位总点数或独立自由度。`adev_error` 为库返回误差估计，不宣称置信区间。

未来同步 notebook 时，应重新导出、更新来源哈希，并核对五条曲线、时间对齐和精确 τ 回归。不要把本机绝对路径带回快照。
