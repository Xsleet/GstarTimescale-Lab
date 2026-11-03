# 学生指南

## 你实际在研究什么

钟差（phase / clock offset）描述一只钟相对参考时间的偏离，单位为秒。频率偏差描述钟差随时间增长的快慢，是无量纲的分数频率。真实时钟有随机噪声，单只钟可能短期表现好、长期表现差。

组合时间尺度（Ensemble / IEM）是利用多只钟的比对信息得到的共同时间参考。这个仓库让你控制输入实验，读取组合结果；你不需要先读懂核心 C++ 工程。

默认实验流程：

```text
时钟参数 + 随机种子
        ↓
四路合成钟差 → CLK 文件 + 双向 PFD 比对数据
        ↓
教师提供的 GstarTimescale.exe
        ↓
四路原始钟 + IEM 输出
        ↓
公共时间区间上的五条 ADEV + HTML 报告
```

PFD 是直接的钟差比对。这里采用 `diff(A,B)=clockA-clockB`，反方向取相反数；没有星间距离、光行时或轨道几何，所以不需要 STK。输入配置对应 `satellite + OBS P`，不能仅把字母改为 `I` 就宣称完成了 ISL 实验。

## 默认案例参数

| 参数 | 值 |
|---|---|
| 时钟 | 0101/0102 为 CSAC，0103/0104 为 mRO |
| 输出标签 | SIM1/SIM2/SIM3/SIM4，按上述顺序对应 |
| 起点 | 2026-01-01 00:00:00 GPST（固定仿真起点） |
| 时长 / 采样 | 10 天 / 10 秒 |
| 每钟输入 | 86,400 个相位点，单位秒 |
| 拓扑 | 四钟全互连，6 对双向 PFD |
| 算法入口 | centralized，二状态，无周期项 |
| 随机种子 | 默认基准 2026；四钟独立种子 2027、2028、2030、2031 |

GPST 是实验使用的时间尺度，不是电脑本地时间。改变电脑日期不会改变模拟起点。启动脚本目前固定采样间隔和时钟数；不要只改表头后继续使用旧数据。

## 一个实验目录有什么

每次运行将配置、输入和输出放在同一目录：

```text
Runs/heterogeneous_10days/
  config/         file_table、Timescale.cfg、session.obj、参数清单与编号映射
  clocks_raw/     四钟原始相位（秒）
  clk/            核心程序读取的标准钟差文件
  pfd/            双向钟差观测
  logs/           控制台和分析日志
  results/        求解输出与 gstar.log
  analysis/       ADEV 数值表、分析来源、检查记录
  figures/        PNG、PDF、SVG
  tools/          保留的实验工具目录
  phase.csv       四钟与 IEM 的公共历元相位
  summary.json    结果检查摘要
  README.md       实验设置与精确 τ 结果
  report.html     浏览器报告
```

`config/manifest.json` 记录时长、采样、随机种子、架构、模型及输入数量；`clock_manifest.yaml` 便于阅读实际噪声参数。不要把这些生成文件单独拿出来而丢掉其余实验记录。

## 修改生成后的输入

初学时优先通过 `lab.py run` 的参数做实验。进阶时可以先准备，再修改某一个配置。下面示范手动运行，不会重新生成输入：

```powershell
.\.venv\Scripts\python.exe lab.py prepare --output Runs/manual_case
Set-Location Runs/manual_case
# 此处按教师要求编辑 config/ 下的配置，记录所有变更
& ..\..\engine\GstarTimescale.exe config/file_table 2>&1 | Out-File logs/console.log -Encoding utf8
# 检查退出码，并检查 results/gstar.log 的错误；失败时不要继续解释图形
$LASTEXITCODE
Set-Location ../..
.\.venv\Scripts\python.exe lab.py report --output Runs/manual_case
```

核心程序必须以实验目录作为工作目录，`file_table` 中使用相对路径。运行前可先执行 `lab.py doctor` 确认程序完整性；手动调用本身不经过启动器校验。

自动报告只适用于本案例的四钟、二状态输出；它依据生成时的 manifest 标注实验。如果你修改时长、钟数、状态数、架构或模型，必须同时保持清单、配置和数据一致，必要时编写新的分析程序。不能拿旧 manifest 的标题给另一个实验背书。首轮课程建议不要手动改这些结构性参数。

## 复现一项结论

记录仓库版本、程序版本、命令、种子、模型、采样和架构；保存原始输入与完整输出。启动器成功执行求解后将程序版本、哈希记录到 `config/runtime.json`。固定种子有助于复现，但更换依赖或运行平台可能产生末位数值差异。

比较算法时应复用相同输入，比较相同时间段、相同 τ 和相同样本支持。结果缺失、日志报错、NaN 或 Inf 都必须先解决，不能通过删掉“坏点”让图好看。
