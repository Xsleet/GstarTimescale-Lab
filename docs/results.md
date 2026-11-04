# 结果文件与图片

直接运行程序后，先看 `Timescale.cfg` 中的 `Project directory`。首页默认设为 `results`，因此结果在实验目录的 `results/` 下。绘图单独进行，命令见[首页](../README.md)。

想先对照实际图片理解文件，请看[两个初始样例的相位、ADEV 与数值对照](example-results.md)。

## 程序输出在哪里，分别是什么？

| 文件 | 内容 | 初次使用重点 |
|---|---|---|
| `IEM.txt` | 组合时间尺度及逐对象中间量 | 每行末尾 `IEM` 后面的相位值 |
| `SIM1.txt`～`SIM4.txt` | 每只钟的原始值和估计值 | 第 5 列原始相位 |
| `gstar.log` | 配置读取、历元处理、完成或错误消息 | 先确认程序已结束，再画图 |
| 其他诊断文件 | 协方差、权重等输出，依配置而定 | 可以等需要研究时再阅读 |

这些都是文本文件。可以用编辑器查看前几行，也可以用 Python 读取。首次使用只需认识 IEM、SIM 和日志；图片由后续绘图脚本生成。

### IEM.txt：组合时间尺度

一行的结构是：

```text
年 月 日 当天秒数  对象编号 差值  对象编号 差值 ... IEM 组合相位
```

例如，一行以 `2026 01 01 30.0` 开始，表示 2026-01-01 00:00:30 GPST。最后的 `IEM 1.5e-8` 表示该历元的组合相位为 `1.5e-8` 秒，也就是 15 ns。

**绘制组合时间尺度时，读取 IEM 标记后面的数值。** 前面成对的编号和差值是方法相关的中间量，不是四只原始钟的相位。程序内部编号也不必与配置里的 0101～0104 文本编号相同；找原始钟请使用对应的 SIM 文件。

### SIM*.txt：单只钟的原始值与估计值

首页的二状态、无谐波案例每行有 9 列：

| 列号（从 1 开始） | 含义 | 单位 |
|---|---|---|
| 1～3 | 年、月、日 | — |
| 4 | 当天秒数 SoD | s |
| 5 | 原始钟相位 | s |
| 6 | 原始分数频率偏差 | 无量纲 |
| 7 | 原始频率漂移率 | s⁻¹ |
| 8 | 估计相位状态 | s |
| 9 | 估计频率状态 | 无量纲 |

例如第 5 列为 `2e-9`，表示原始钟相位为 2 ns。**比较“单钟和组合”的 ADEV 时，使用第 5 列，不是第 8 列。** 改变状态模型或增加谐波后，后续估计列会变化，绘图脚本的 `TREND_STATE`、`NUM_HARMONICS` 应与配置对应。

10 天示例输入每钟 86400 点；当前默认解算输出为第 30～863990 秒的 86397 点。前几个历元受插值和初始化影响。比较的各条曲线使用相同实际日期和采样区间。

## 绘图脚本如何工作？

[tools/plot_results.py](../tools/plot_results.py) 的顶部给出输入目录、输出目录、钟名和采样间隔。下面的代码按四步排列：

1. 读取 IEM/SIM 文件，检查日期及采样间隔，保存各路相位原值。
2. 把秒换成纳秒，绘制相位变化图。
3. 复用 DataProcess 的 `compute_dev → plot_dev` 函数，计算并绘制 ADEV。
4. 保存曲线数值，以及指定平均时间 τ 上直接计算的结果。

它不读取示例 manifest，不要求使用某个启动器，不调用核心程序。只要实际文本结果和绘图设置匹配，就可以单独运行：

```powershell
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/manual_case/results --output Runs/manual_case
```

改了结果目录后，例如：

```powershell
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/manual_case/results/noise_test --output Runs/manual_case/noise_test
```

新增或减少钟时，可以编辑 `CLOCK_IDS`，或传 `--clocks SIM1 SIM2 SIM3`。改变采样间隔后，对应修改 `SAMPLE_INTERVAL_S` 或传 `--interval`。脚本也核对文件中的实际间隔，避免把 20 秒数据当成 10 秒数据计算。

所有路径按脚本顶部或命令指定；默认输出到结果目录的上一级。同一输出目录再次绘图会更新图片和数值表。需要保留两次图时，用不同的 `--output`。

## 两张图怎么看？

**相位图 `phase.png`**：横轴为距离第一个有效输出历元的天数，纵轴为纳秒。默认每条曲线减去自己的首个相位，便于比较变化；这由 `PHASE_ZERO_FIRST` 控制。CSV 始终保存相位原值，不能从图上统一的起点判断绝对同步精度。

**ADEV 图 `adev.png`**：横轴 τ 是平均时间，单位秒；纵轴是分数频率 Allan 偏差，无量纲。两轴都使用对数刻度。同一 τ 上 ADEV 更低，表示相应平均时间上的频率变化更小。先看 10 秒附近的短期表现，再看 1000 秒及更长 τ。

默认共有 **5 条曲线**：SIM1～SIM4 是四只原始钟，Ensemble 是组合时间尺度。在不同 τ 上表现可能不同，不需要找一条处处最优的曲线。

图形和计算复用[现有 DataProcess 函数](../tools/dataprocess_snapshot/README.md)，使用非重叠 `allantools.adev`。相位仍以秒输入，计算采样率为 `1 / SAMPLE_INTERVAL_S`。

## 输出的图片和数值表

| 路径 | 内容 |
|---|---|
| `figures/phase.png/.pdf/.svg` | 相位变化图 |
| `figures/adev.png/.pdf/.svg` | 原始钟与组合时间尺度的 ADEV 图 |
| `analysis/phase.csv` | `epoch_gpst`、首个输出起算的 `elapsed_s`、各钟及 Ensemble 相位原值（秒） |
| `analysis/adev.tsv` | 默认倍频 τ 上的曲线数值 |
| `analysis/stability_summary.tsv` | 指定 τ 上直接计算的 ADEV、误差估计、有效项数 |
| `analysis/plot_summary.json` | 本次实际读取的路径、时间范围、钟名、采样设置 |

PNG 可直接打开，PDF/SVG 适合插入报告。TSV 可以用文本编辑器、Python 或电子表格软件读取。

默认指定 τ 为 10、30、100、300、1000、3000、10000、30000、86400 秒。脚本选择采样间隔和数据长度支持的点，直接调用 AllanTools 计算，不从图上插值。

`sample_count` 是非重叠 ADEV 的二阶差分项数，`adev_error` 是库返回的误差估计。长 τ 的有效项数会更少：先用表格理解这一点，再逐步研究不确定度。

## 其他入口的结果

第 4.3 节的 `analyze` 读取公开归档，重算多种方法的图；要画自己重新解算的单个结果，仍可使用本页的独立脚本。`compare-rerun` 则用于新旧时间尺度对照。

可选一键案例会额外产生 HTML、根目录 `phase.csv`、`summary.json` 等。这些是[自动报告功能](convenience-commands.md)的输出，直接运行 exe 并不需要它们。

分布式输出可能分布在多个节点/分量子目录。请明确选择其中包含 `IEM.txt` 和对应钟文件的目录，再传给 `--results`；该图代表所选输出，不会自动平均所有节点。
