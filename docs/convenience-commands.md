# 可选便利命令

主要学习流程见[首页](../README.md)：编辑原生配置、直接运行 exe、单独绘图。下面保留现有自动化工具，便于批量准备、环境检查或快速演示；它们不是完成实验的必经步骤。

在仓库根目录执行，Python 环境和程序按首页准备。

| 命令 | 作用 |
|---|---|
| `lab.py doctor` | 查看依赖和运行包是否就绪 |
| `lab.py init --output Runs/my_case` | 只复制配置模板，随后自行放入数据 |
| `lab.py inspect --workdir Runs/my_case` | 查看配置实际解析出的时间和路径 |
| `lab.py execute --workdir Runs/my_case` | 运行已有配置并保留执行记录，要求结果目录为空 |
| `lab.py prepare --output Runs/my_case` | 生成示例数据与初始配置，不解算 |
| `lab.py run` | 新建默认 10 天异构案例，生成输入、解算并生成 HTML |
| `lab.py report --output Runs/heterogeneous_10days` | 对未改动设置的内置案例重建 HTML 报告 |

命令前加 `.\.venv\Scripts\python.exe`，例如：

```powershell
.\.venv\Scripts\python.exe lab.py run
Start-Process .\Runs\heterogeneous_10days\report.html
```

默认一键案例为 `--case heterogeneous --days 10 --seed 2026 --architecture centralized`。四只已有 CSAC 的基础案例使用 `tools/prepare_csac.py` 下载固定仿真数据，随后直接运行 exe，详见 [CSAC 教程](../examples/csac/README.md)。异构生成任务可通过 `--output`、`--seed`、`--days` 调整。

`prepare`/`run` 使用生成器自己的配置逻辑，不读取你修改过的根目录模板。已生成并手动编辑的配置应直接调用 exe，或使用 `execute`；不要再次运行 `run` 期待它保留手动设置。

秩亏补偿选项在各准备入口均可指定：`--method NONE|SUMZERO|BROWN|GREENHALL|KPW`（这里的竖线表示任选一个，不要原样输入）。例如 `lab.py run --method BROWN --output Runs/heterogeneous_brown`；四 CSAC 数据则用 `tools/prepare_csac.py --method KPW --output Runs/csac_kpw`。准备后也可直接修改 Timescale.cfg。已有结果的 `report` 不重新解算，不能用它把某方法的输出改名为另一种方法。

自动 HTML 依据内置案例的生成记录标注实验。自己改过时间、路径、对象或参数后，使用独立的 `tools/plot_results.py`，按实际结果文件绘图。它不依赖生成记录，也不要求先运行 `lab.py`。
