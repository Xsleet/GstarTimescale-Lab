# 论文第 4.4 节实验：用贝叶斯优化调整噪声参数

这一节按四步完成：**默认噪声参数运行一次 → 贝叶斯优化 → 用优化后的参数再运行一次 → 比较结果。** 第一次不用手动修改噪声参数，先取得默认结果；优化时，每组候选参数都会实际交给 GSTAR 运行。

实验使用 **2 只 mRO + 2 只 CSAC，20 天，10 秒采样**。前 10 天供优化程序寻找参数，后 10 天用来比较默认参数和优化参数。**比较前后的输入数据、时间范围和其他设置相同，只改变过程噪声参数。** 数据已经提供，不需要生成新时钟，也不需要轨道或 STK。

![四只原始钟与两组参数结果的 ADEV 示例](preview/fig4_16.svg)

这张图用来认识结果的形式。下面的优化会真正运行程序产生新结果，不会读取这张图或预先保存的最优参数来代替搜索。

## 准备环境与数据

在包含 `lab.py` 的仓库目录打开 PowerShell，按[首页](../../README.md)安装单独提供的授权运行包。首次创建 Python 环境；已有环境也请执行安装依赖这一行，以安装新增的优化依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.txt

.\.venv\Scripts\python.exe tools/thesis_section44.py fetch --kind inputs --output Runs/thesis44/inputs
```

已有 `inputs` 就不用重复下载。输入包约 116 MB，包含 5 个异构组的 20 天 CLK/PFD；下面默认选择第 1 组。

## 1. 使用默认噪声参数运行一次

先准备默认参数实验目录。`--variant baseline` 使用案例提供的默认噪声参数，`--window evaluation` 选择后 10 天，作为最终比较的共同时间段：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section44.py prepare-case --inputs Runs/thesis44/inputs --variant baseline --window evaluation --output Runs/thesis44/test_initial
```

打开 `Runs/thesis44/test_initial/config/`，可以看到三个主要文件：

| 文件 | 可以直接修改的内容 |
|---|---|
| `file_table` | 运行配置、对象配置和基础表的路径 |
| `Timescale.cfg` | 起始时间、时长、采样间隔、输入输出路径、秩亏补偿方法 |
| `session.obj` | 每只钟的初始不确定度和过程噪声参数 |

第一次保持这些配置不变，直接运行程序，再绘制结果：

```powershell
Push-Location Runs/thesis44/test_initial
& ..\..\..\engine\GstarTimescale.exe config/file_table
Pop-Location
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/thesis44/test_initial/results --output Runs/thesis44/test_initial
Start-Process .\Runs\thesis44\test_initial\figures\adev.png
```

现在已经得到一份默认结果：`test_initial/results/IEM.txt` 是组合结果，`SIM1.txt`～`SIM4.txt` 对应四只原始钟。`test_initial/figures/adev.png` 中有 **四只原始钟 + 默认参数组合，共五条 ADEV 曲线**；曲线越低，表示在对应平均时间 τ 下越稳定。

本次运行时间为 **2026-01-11 00:00:00 至 2026-01-21 00:00:00 之前，GPST**；时长 864000 秒，采样间隔 10 秒。默认二状态、无谐波、Greenhall。保留这个目录，最后直接用它和优化结果比较。

秩亏补偿仍可以在 `Timescale.cfg` 的 `Rank deficiency remedy` 中填写 `NONE / SUMZERO / BROWN / GREENHALL / KPW`。本节先固定 Greenhall，专门观察扩散系数的作用；也可以准备时加 `--method BROWN` 开展另一组实验。

## 2. 使用贝叶斯优化寻找噪声参数

准备前 10 天的搜索目录，并生成搜索设置。它从同一组默认噪声参数开始：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section44.py prepare-case --inputs Runs/thesis44/inputs --variant baseline --window train --output Runs/thesis44/train
.\.venv\Scripts\python.exe tools/optimize_diffusion.py init --case Runs/thesis44/train --output Runs/thesis44/search.json
```

`init` 只生成可编辑的 `search.json`，**真正的优化由下面的 `run` 命令启动**。第一次可以直接使用默认搜索设置：

```powershell
.\.venv\Scripts\python.exe tools/optimize_diffusion.py run --config Runs/thesis44/search.json --output Runs/thesis44/search
```

贝叶斯优化可以理解为：**先试几组参数，观察哪些结果更好，再根据已有结果选择下一组值得尝试的参数。** 本教程使用 Optuna 的 TPE 方法，优化每只钟的扩散系数 q₁、q₂。

每轮都会执行以下步骤，终端会显示 `Trial 1/12` 等进度：

1. 选择一组 q₁、q₂，换成 √q 写入该轮的 `session.obj`。
2. 调用 `GstarTimescale.exe`，完整运行前 10 天。
3. 用实际输出的组合相位计算 ADEV，并得到评价值。
4. 保存本轮结果，再选择下一组参数。

默认评价 τ=300、1000、3000 秒处的 ADEV，取 `log10(ADEV)` 的平均值，**越小越好**。第 0 轮使用默认参数，随后探索其他参数，最后选出本次搜索中评价值最小的一组。这里第 0 轮运行的是前 10 天，用于给搜索提供起点；第 1 步已经保存的后 10 天默认结果用于最后比较。

| 数据时间段（GPST，结束时刻不包含） | 用途 |
|---|---|
| 2026-01-01 至 2026-01-11，前 10 天 | 优化程序反复运行，选择参数 |
| 2026-01-11 至 2026-01-21，后 10 天 | 第 1 步和第 3 步各运行一次，比较默认参数与优化参数 |

这样可以看到找到的参数在另一段数据上是否仍有效。优化程序只使用前 10 天，不读取第 1 步的结果来挑选参数。

一次 10 天解算在验证机器上约需 2～3 分钟，默认 12 次搜索可能需要半小时左右。每轮结果都保留，建议预留 5 GB；增加次数时相应增加空间。

搜索结束后，打开过程报告：

```powershell
Start-Process .\Runs\thesis44\search\report.html
```

每个散点是一次真实解算，黑线是截至当时的最好评价值。选中的参数保存在 `search/best_parameters.json`。如果仍选中第 0 轮，说明本次搜索没有找到优于默认值的参数，后面的比较曲线可能重合。

## 3. 用优化后的参数再运行一次

以第 1 步的配置为模板，把**这次搜索实际选中的参数**写入新目录：

```powershell
.\.venv\Scripts\python.exe tools/optimize_diffusion.py apply --search Runs/thesis44/search --case Runs/thesis44/test_initial --output Runs/thesis44/test_best
```

打开 `Runs/thesis44/test_best/config/session.obj`，就能看到写入的噪声参数。`apply` 保留第 1 步的数据、时间范围、补偿方法和其他设置，将选中的扩散系数转换成程序需要的数值写入配置，结果输出到新目录。

**`apply` 只是准备配置，还需要运行程序：**

```powershell
Push-Location Runs/thesis44/test_best
& ..\..\..\engine\GstarTimescale.exe config/file_table
Pop-Location
```

优化参数的组合结果现在保存在 `Runs/thesis44/test_best/results/IEM.txt`，默认结果仍在 `test_initial/results/IEM.txt`。

## 4. 比较默认参数与优化参数的结果

```powershell
.\.venv\Scripts\python.exe tools/thesis_section44.py compare-runs --baseline Runs/thesis44/test_initial/results --adjusted Runs/thesis44/test_best/results --output Runs/thesis44/test_comparison
Start-Process .\Runs\thesis44\test_comparison\comparison.png
```

比较图包含 **四只原始钟 + 默认参数组合（Initial parameters）+ 优化参数组合（New parameters），共六条 ADEV 曲线**。先看优化参数曲线在哪些 τ 下低于默认参数，再看是否有其他区间变差。搜索时评价值变好，并不保证后 10 天的所有 τ 都改善。

数值表在 `test_comparison/adev_exact.tsv`，可以直接比较同一个 τ 下的 ADEV；每个 τ 都直接计算，不使用曲线插值。`results/IEM.txt` 最后一列是组合相位，单位秒；`SIM*.txt` 第 5 列是原始钟相位。

想单独查看优化后的一组五条 ADEV 曲线及相位图，可运行：

```powershell
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/thesis44/test_best/results --output Runs/thesis44/test_best
```

到这里，默认运行、贝叶斯优化、优化后运行和结果比较四步已经完成。下面是可选的参数说明与练习。

## 可选：查看每一轮发生了什么

```text
Runs/thesis44/search/
  search.json                 本次搜索设置的快照
  initial_parameters.json     实际起始 q₁/q₂
  trials.csv                  每轮阶段、参数、评分、历史最佳值与失败原因
  trials/trial_000/
    config/session.obj        第 0 轮真正交给程序的参数
    results/IEM.txt           第 0 轮实际组合结果
    results/SIM1.txt ...      原始钟与估计结果
    logs/                     运行日志和严格检查记录
    parameters.json           该轮的 q₁/q₂
    score.json                实际 ADEV、误差估计和评价值
  trials/trial_001/ ...        其他轮次，结构相同
  best_parameters.json        本次搜索选中的 q₁/q₂
  best_case/config/           选中参数对应的原生训练配置
  summary.json               最佳试验编号及训练区间
  figures/convergence.png     实际收敛曲线
  report.html                 搜索过程报告
```

可以打开任意一轮的 `config/session.obj` 查看实际输入，用 `score.json` 对照实际 ADEV 和评分。候选值可以变差，失败试验也会在 `trials.csv` 中保留。

想单独重画搜索过程，而不重新搜索：

```powershell
.\.venv\Scripts\python.exe tools/optimize_diffusion.py plot --search Runs/thesis44/search
```

## 可选：调整贝叶斯优化设置

运行第 2 步的搜索命令前，可以打开 `Runs/thesis44/search.json` 调整设置：

| 字段 | 含义与练习建议 |
|---|---|
| `trials` | 总试验次数，默认 12，包含第 0 次原参数运行；想更充分搜索可改为 30 或 50 |
| `startup_trials` | 初始探索次数，默认 4；后续使用 TPE 贝叶斯优化选择候选值，必须小于总次数 |
| `seed` | 随机种子，默认 42，便于按相同顺序重复实验 |
| `objective_taus_s` | 评价哪些平均时间，默认 `[300, 1000, 3000]` 秒，关注中期表现 |
| `parameters` 中的 `0101`～`0104` | 分别控制四只钟 |
| 每只钟的 `q1/q2 → enabled` | `true` 表示参与搜索，`false` 表示固定在训练 `session.obj` 当前值 |
| `q1/q2 → min/max` | 扩散系数的搜索下限、上限；**这里直接填 q，不需要开平方** |

初始范围围绕训练配置生成，默认 q₁ 为当前值的 0.25～4 倍，q₂ 为 0.1～100 倍。可以把四只钟 q₁ 的 `enabled` 改成 `false`，只优化 q₂；也可以只启用一只钟的 q₂，观察一维搜索。几次试验不能说明已经收敛。

优化由公开的 Python 脚本和 Optuna TPE 驱动，核心滤波求解仍在封装程序中。想研究搜索策略，可阅读或修改 [optimize_diffusion.py](../../tools/optimize_diffusion.py) 的 `score_phase`、搜索范围与采样器设置。TPE 的参数说明见 [Optuna 官方文档](https://optuna.readthedocs.io/en/v4.5.0/reference/samplers/generated/optuna.samplers.TPESampler.html)。本教程用仿真组合相位的 ADEV 评分；在没有真值的在轨观测中，需要另行设计评价指标。

## 可选：手动修改一次噪声参数

学会主流程后，也可以亲自改一个参数，观察它的作用。程序用噪声参数构造过程噪声矩阵 Q。`session.obj` 中 `0101`、`0102` 是两只 mRO，对应 `SIM1.txt`、`SIM2.txt`；`0103`、`0104` 是两只 CSAC，对应 `SIM3.txt`、`SIM4.txt`。

每行末尾可以看到：

```text
Phase:[初始相位标准差,相位过程噪声系数]
Frequency:[初始频率标准差,频率过程噪声系数]
```

这里的过程噪声系数使用标准差形式；本教程以 q₁、q₂ 表示它们的平方：

```text
q₁ = Phase 第二个数的平方       → 填入 Phase 的数 = √q₁
q₂ = Frequency 第二个数的平方   → 填入 Frequency 的数 = √q₂
```

例如第 1 只 mRO 的默认 `Frequency` 第二个数是 `2.897e-13`，对应 q₂≈`8.392609e-26`。把这个数改成 `5.794e-13`，就将 q₂ 增大了 4 倍。**逗号前的初始标准差保持不变**。

另建一份后 10 天配置，打开它的 `session.obj` 修改；保留主流程的默认结果和优化结果：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section44.py prepare-case --inputs Runs/thesis44/inputs --variant baseline --window evaluation --output Runs/thesis44/manual
notepad Runs/thesis44/manual/config/session.obj
# 保存修改并关闭编辑器后，再执行下面的命令。
Push-Location Runs/thesis44/manual
& ..\..\..\engine\GstarTimescale.exe config/file_table
Pop-Location
.\.venv\Scripts\python.exe tools/thesis_section44.py compare-runs --baseline Runs/thesis44/test_initial/results --adjusted Runs/thesis44/manual/results --output Runs/thesis44/manual_comparison
Start-Process .\Runs\thesis44\manual_comparison\comparison.png
```

这是额外的参数敏感性练习。若根据后 10 天结果反复挑参数，这段数据就参与了调参，不能再视为独立验证。

## 可选：重画保存的论文实验图表

想先看原实验的主要现象，或者尚未取得运行包，可使用约 71 MB 的分析包：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section44.py fetch --kind analysis --output Runs/thesis44/data
.\.venv\Scripts\python.exe tools/thesis_section44.py analyze --data Runs/thesis44/data --output Runs/thesis44/analysis
Start-Process .\Runs\thesis44\analysis\report.html
```

输出图 4.12、4.13、4.15、4.16、4.17，以及扩散系数、搜索记录和改善率表；图 4.14 的思路就是本教程实际执行的“候选参数 → 求解 → 评价 → 再搜索 → 独立验证”。这条可选路径只是重画保存数据，不会启动新的搜索。

归档示例中，τ=1000 秒的四组平均 ADEV 从约 5.94×10⁻¹² 降至 4.90×10⁻¹²；你自己的搜索预算、目标 τ 和起始参数不同，结果不必完全相同。比较时既要看改善区域，也要看其他 τ 是否付出了代价。

数据下载页：[第 4.4 节数据包](https://github.com/Xsleet/GstarTimescale-Lab/releases/tag/thesis-section44-data-v1)。自动下载失败可在 `fetch` 后增加 `--archive 下载的ZIP路径`。再次运行时请使用新的输出目录，保留旧实验便于对比。

进一步查阅：[配置选项](../../docs/configuration.md) · [输出列说明](../../docs/results.md) · [数据与验证记录](validation.md)。
