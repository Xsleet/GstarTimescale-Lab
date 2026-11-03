# 论文第 4.3 节：相对钟差观测下的秩亏补偿

本案例公开毕业论文第 4.3 节的**仿真数据、原始解算结果中的相位和协方差、可编辑运行配置、图表重算工具**。覆盖图 4.7～4.11、表 4.1～4.2。数据不是在轨实测数据，也不是首页内置随机案例。

**无需核心程序即可下载数据、重新计算 ADEV、绘图并查看 HTML 报告。** 从 CLK/PFD 重新解算仍需单独获得授权运行包。公开 Release 只包含数据；没有核心源码或可执行程序。

当前版本如实保留论文、绘图脚本和归档数据间的差异，**不宣称表 4.2 所有印刷数值已经完全复现**。请先阅读下方“核对结果与限制”。

![异构四组的原始钟和四种方法 ADEV 重算预览](preview/fig4_11.svg)

其余预览：[图 4.7](preview/fig4_7.svg) · [图 4.8](preview/fig4_8.svg) · [四钟最大值对照](preview/fig4_8_max.svg) · [图 4.9](preview/fig4_9.svg) · [图 4.10](preview/fig4_10.svg)。这些是从公开数据重算的图，原始数值随数据包提供。

## 第一次使用：重算图表

先下载本仓库，在包含 `lab.py` 的目录打开终端。Windows 推荐 Python 3.11/3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.txt
.\.venv\Scripts\python.exe tools/thesis_section43.py fetch --kind analysis --output Runs/thesis43/data
.\.venv\Scripts\python.exe tools/thesis_section43.py analyze --data Runs/thesis43/data --output Runs/thesis43/analysis
Start-Process .\Runs\thesis43\analysis\report.html
```

Linux/macOS 的数据分析使用相同依赖，把 `.\.venv\Scripts\python.exe` 换成 `.venv/bin/python`。核心运行包只支持 Windows x64。图中文字使用可用的系统字体；导出曲线及数值不依赖中文字体。

下载地址、压缩包大小、解压大小、SHA256 均固定在 [data-release.json](data-release.json)。程序先校验整个压缩包，再校验每个文件；已有目录不会覆盖。建议在空间充足的磁盘上预留 **4 GB**，需要同时保留多次解算时再增加空间。第二次分析换一个输出目录，例如 `Runs/thesis43/analysis_v2`。

若自动下载失败，可从 [数据 Release](https://github.com/Xsleet/GstarTimescale-Lab/releases/tag/thesis-section43-data-v1) 手动下载 `thesis-section43-analysis-v1.zip`，然后执行：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section43.py fetch --kind analysis --archive "thesis-section43-analysis-v1.zip" --output Runs/thesis43/data
```

不要把 ZIP 的下载路径写进 `--data`；`--data` 指的是经 `fetch` 安装后的目录。下载只需 Python 标准库；分析需要 `requirements-demo.txt`。

## 运行后看什么

| 结果 | 内容 |
|---|---|
| `report.html` | 可离线打开的完整结果页，包含图和核对表 |
| `figures/fig4_7.svg`、`.png` | 无补偿 NONE 下四个成员钟的后验标准差，首日有效数据 |
| `figures/fig4_8.svg`、`.png` | 沿用归档绘图脚本：第 1 个成员钟的标准差，首日 |
| `figures/fig4_8_max.svg`、`.png` | 补充核对：按正文描述，取每个历元四钟标准差最大值 |
| `figures/fig4_9.svg`～`fig4_11.svg` | 三种配置的 ADEV，每个子图包含四只原始钟和四种方法 |
| `tables/adev_octave.csv` | 全部 15 组、120 条序列的逐点 ADEV、误差估计和有效项数 |
| `tables/adev_exact_by_group.csv` | 异构 5 组在 10、100、1000、10000、100000 秒处直接计算的 ADEV |
| `tables/table4_2_audit.csv` | 论文印刷值、5 组重算值、图示 4 组重算值和差异 |
| `tables/covariance_points.csv` | 协方差图的完整有效数值点；绘图下采样不影响此表 |
| `validation.json` | 文件校验、曲线数值核对及论文表格匹配数量 |

参考曲线点见 [adev_octave.csv](reference/adev_octave.csv)，分组映射见 [group_mapping.csv](reference/group_mapping.csv)。仅画图成功不等于论文全部数值通过；报告会明确显示仍不匹配的表格单元格。

## 实验条件及图表映射

时间范围为 **2026-01-01 00:00:00 GPST 至 2026-01-11 00:00:00 GPST，结束点不包含在内**。采样间隔 10 秒，每只钟的标准输入有 86400 个历元。解算输出公共区间是 30～863990 秒，共 86397 点；分析不补零、不插值、不去趋势。

| 表 4.1 方案 | 数据配置名 | 每组成员 |
|---|---|---|
| S1 | `csac_only` | 4 × CSAC |
| S2 | `mro_only` | 4 × MRO |
| S3 | `mixed_2plus2` | 2 × MRO + 2 × CSAC，按此顺序映射到 clock1～4 |

每种配置保留 5 个原始实验组，共 15 组。不同方案可复用同一源钟，不应将跨方案的所有组当成独立统计样本。

| 论文对象 | 数据选择 | 方法 / 统计量 |
|---|---|---|
| 图 4.7 | 三种配置的 group02，与 Word 内嵌图对应 | NONE；四钟逐钟后验标准差 |
| 图 4.8 | 三种配置的 group02，与 Word 内嵌图对应 | SUMZERO / BROWN / GREENHALL；见下方口径差异 |
| 图 4.9 | CSAC 同构组 | 四只原始钟 + 四种有效补偿方法 |
| 图 4.10 | MRO 同构组 | 同上 |
| 图 4.11 | 异构组 | 同上 |
| 表 4.2 核对 | 异构 group01～05，另列图示四组口径 | 逐组 ADEV 的算术平均，不是先平均相位再求 ADEV |

图 4.9～4.11 的面板映射为 **LEO 01→group01、LEO 02→group02、LEO 03→group04、LEO 04→group05**。这是原绘图脚本的选择；未丢弃 group03，数据包和表格中仍保留它。

图 4.7/4.8 的正文写 LEO 01，但 Word 实际插入的图片与 `group02` 候选图匹配。本工具按实际插图选择 group02；不能仅根据正文的 LEO 01 标签推定这两图来自 group01。

`SUMZERO` 对应论文的 Centroid，另有 Brown、Greenhall、KPW。`NONE` 是不稳定对照，不纳入有效时间尺度 ADEV 比较。

解算采用 `satellite + OBS P`、集中式、2 个趋势状态、0 个谐波状态。这里的 `SIM1～4` / `0101～0104` 是**一颗卫星内部的四只钟**；每个 group 是一个独立单星钟组实验。此节不需要轨道、STK 或星间 ISL 数据。每组每天 1 个 CLK 文件、6 个双向 PFD 文件；全输入包共 150 个 CLK 和 900 个 PFD 文件。

## 数据文件含义

分析包：

```text
phase/<configuration>_groupNN.csv
covariance/<configuration>_groupNN/{NONE,SUMZERO,BROWN,GREENHALL}.csv
group_mapping.csv
notebook_summary.csv
source_provenance.json
covariance_coverage.json
manifest.json
```

相位 CSV 的 `time_s` 是相对实验起点的秒数，`clock1_s`～`clock4_s` 和四种方法列的单位都是秒。它们来自归档 `SIM*.txt` 第 5 列和 `IEM.txt` 第 14 列，按公共时间区间保存；用 17 位有效精度导出。四个方法列分别是该方法输出的组合时间尺度相位。

协方差 CSV 保存**首日**四个成员钟的 `phase_variance`，单位 s²；标准差取平方根。NONE 发散后的非有限或非正方差不用于对数图，不伪造后续点。`covariance_coverage.json` 记录实际覆盖。此包没有承诺包含 10 天完整协方差矩阵；10 天完整相位和 CLK/PFD 已保留。

## 从标准输入重新运行核心程序

先按主 README 安装授权运行包并通过 `lab.py doctor`。下载输入包后，选择一个组和方法生成可编辑配置：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section43.py fetch --kind inputs --output Runs/thesis43/inputs
.\.venv\Scripts\python.exe tools/thesis_section43.py prepare-case --inputs Runs/thesis43/inputs --group mixed_2plus2_group01 --method GREENHALL --output Runs/thesis43/rerun
.\.venv\Scripts\python.exe lab.py inspect --workdir Runs/thesis43/rerun
.\.venv\Scripts\python.exe lab.py execute --workdir Runs/thesis43/rerun
```

输出在 `Runs/thesis43/rerun/results/`，运行记录在 `logs/`。`config/Timescale.cfg`、`session.obj`、`file_table` 都可修改；配置以相对路径引用共享输入包，移动目录后需保持相对位置或重新生成配置。要复现原条件，请保留 10 天、10 秒、方法和噪声参数不变。可以选择 `csac_only_group01`～`05`、`mro_only_group01`～`05`、`mixed_2plus2_group01`～`05`；方法为 `SUMZERO`、`BROWN`、`GREENHALL`、`KPW` 或 `NONE`。

**`analyze` 分析的是校验过的历史归档，不能拿它给新解算结果盖通过章。** 当前程序的重新解算结果需与对应历史相位单独比较；版本差异见 [验证记录](validation.md)。NONE 是预期发散对照，启动器报错或提前终止应保留日志，不能将其标为成功案例。

运行后可生成独立核对报告，包括四钟、历史时间尺度和新时间尺度的六条 ADEV 曲线：

```powershell
.\.venv\Scripts\python.exe tools/thesis_section43.py compare-rerun --data Runs/thesis43/data --workdir Runs/thesis43/rerun --group mixed_2plus2_group01 --method GREENHALL --output Runs/thesis43/rerun_comparison
Start-Process .\Runs\thesis43\rerun_comparison\report.html
```

该命令不修改解算结果。日志有错误时仍生成失败核对记录，并返回退出码 2；历元有缺测时不压缩时间序列来计算 ADEV。`--group` 是用户声明的来源，须与实际准备的输入一致。

## 核对结果与限制

1. **图表编号和来源已确认。** 对照毕业论文 `博士毕业论文-20261103.docx` 的第 4.3 节；文件 SHA256 记录在 [paper-values.json](paper-values.json)。不包含期刊论文中名称相似的动态噪声第 4.3 节，也不包含毕业论文第 4.4 节贝叶斯优化实验。
2. **统计组数存在差异。** 正文描述 LEO 01～04，绘图选取 4 组，归档表格代码却汇总 5 组。报告同时给出两种均值，未擅自选择其中一种替代论文。
3. **图 4.8 口径存在差异。** 正文说“四钟最大标准差”，现存绘图脚本用固定随机种子选中 SAT01。保留脚本口径，并额外输出 `fig4_8_max`，两者清楚区分。
4. **表 4.2 尚未完全复现。** 原表的五个 τ 与现存 notebook 的默认倍频网格不同。工具在目标 τ 上重新调用 `allantools.adev`，不从相邻点插值。逐格差异在报告中列出；论文原值是单独保存的核对基准，不参与求解或曲线生成。
5. **观测噪声描述与归档设置不同。** 正文写 PFD 标准差 1e-15 s；归档 PFD 生成器直接写入两钟相位差及其反号，没有另加独立鉴相噪声。归档滤波配置 `Link_Noise.Default=1e-14`，`SUMZERO constraint sigma=1e-14`。输入包保留实际归档值，未为了符合文字描述重写观测。
6. **历史输出和当前程序不是同一验证层级。** 历史数据可以重算原绘图统计；当前授权运行包可运行相同标准输入，但并不保证与历史版本逐点相同。已做的重新解算检查及差异见验证记录，不应推断所有 75 个历史算例都已经用当前版本重跑。
7. **归档协方差有非正值。** 不仅 NONE，Brown、Greenhall 的部分对角元素也为零或负数。公开 CSV 原样保留；沿用原绘图脚本只对正且有限的值开方，不取绝对值、不裁剪成正数。补充 max 图要求同历元四个值均有效。此筛选能复现绘图处理，但不是“协方差正定性已验证”的证明；数量与范围见验证记录。

## 来源与复现方法

原始实验集为 `pfd_rankremedy_suite` 的 `day01_10`。公开前逐文件核对了源结果和第四章独立归档的 SHA256，并只导出本节需要的列。所有重算使用与 `Chapter4.ipynb` 相同的非重叠相位 ADEV：`allantools.adev(phase, rate=0.1, data_type="phase")`。图采用默认倍频 τ；精确统计表显式传入目标 τ。原始绘图计算函数独立执行后生成仓库内参考点，再核对公开 CSV 的重算结果。

为了让无需私有工作区的用户运行，本案例将原 notebook 的相关分析步骤移植为命令行工具，改为公开数据包和相对路径；版式、字体可能与 Word 内嵌图片不同，不宣称像素完全相同。没有重新生成随机钟、没有修改核心算法、没有公开完整论文、核心源码或运行包。
