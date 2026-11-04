# 分级实验任务

每次只改变一个主要因素，保存参数表、曲线、数据表和解释。分享实验材料时不包含受限分发的运行包。

已有论文数据的复现入口：[毕业论文第 4.3 节：秩亏补偿](../examples/thesis-section43/README.md)。该案例使用归档数据，与下列内置合成实验分别保存；没有核心程序也可以重算 ADEV 和图表。

## 实验 1：跑通并解释结果

按首页直接运行默认 10 天案例，单独执行绘图脚本。先在原始 IEM/SIM 文件中找到相位，再在图上指出四只钟与 Ensemble，解释两张图的不同含义。在数值表中取 10、1000、86400 秒三个点，记录 Ensemble 与单钟的 ADEV。

## 实验 2：同类模型与异构模型

```powershell
.\.venv\Scripts\python.exe tools/prepare_csac.py --output Runs/comparison_csac
.\.venv\Scripts\python.exe tools/run_demo.py --prepare-only --clock-profile csac-mro --days 10 --output Runs/comparison_heterogeneous
```

上面只准备数据。分别打开两组 config，进入各实验目录直接运行同一个 exe，再给 `tools/plot_results.py` 指定各自的 results 和输出目录。步骤与首页相同。

基础案例直接使用已有归档的 CSAC_01～CSAC_04，见 [CSAC 数据来源](../examples/csac/README.md)。异构案例加入白频噪声和频率随机游走，见 [参数说明](../examples/heterogeneous/README.md)。

观察哪个模型在不同 τ 有不同排序。两组实验的数据来源和滤波配置都不同，因此这不是严格的单因素“异构一定优于同构”证明。请解释比较的局限。

## 实验 3：随机性与可重复性

```powershell
.\.venv\Scripts\python.exe tools/run_demo.py --prepare-only --clock-profile csac-mro --seed 2026 --output Runs/repeat_seed2026
.\.venv\Scripts\python.exe tools/run_demo.py --prepare-only --clock-profile csac-mro --seed 2027 --output Runs/repeat_seed2027
.\.venv\Scripts\python.exe tools/run_demo.py --prepare-only --clock-profile csac-mro --seed 2028 --output Runs/repeat_seed2028
```

分别运行并画图，再选相同 τ 比较不同种子的 ADEV。先描述单次实验，再观察多次结果的变化。默认仍是 10 天、10 秒采样；保留每组结果供比较。

## 实验 4：集中式与分布式（进阶）

复用同一份输入，在不同的 Timescale.cfg 副本中将 `Estimation architecture` 分别改为 `centralized`、`distributed_if`、`distributed_ci`，每套指定独立的 `Project directory`。用 file_table 切换配置后直接运行程序。

保持种子、时长和时钟参数相同，先检查各架构日志，再比较输出。在 CI 架构中同时记录选定节点和其它节点，不能只取一个节点就评价全网。默认实验验收以 centralized 为基准；这些选项供探索，不宣称所有异构参数下都已经通过性能验证。

## 实验 5：研究时长与统计支持

以 10 天为起点，再用输入准备命令的 `--days 20` 准备 20 天数据，使用新目录。读取生成的起始时间与运行秒数后再运行程序。比较公共 τ 的有效项数及数值变化；生成器起点固定在 2026 年。

## 每次实验的记录模板

| 项目 | 填写内容 |
|---|---|
| 研究问题 | 你要检验什么，而不只是“运行成功” |
| 版本与环境 | 仓库版本、engine-release.json 中的程序版本、Python 依赖 |
| 输入条件 | 模型、种子、时长、采样、架构 |
| 改动 | 相对基准只改变了什么 |
| 检查 | 日志、完整性、公共区间、数值有限 |
| 指标 | 相同 τ 的 ADEV、比值、有效项数 |
| 结论边界 | 哪些只是本次合成实验的结果 |

真实钟数据接入、缺测、拓扑变化、ISL 和模型失配可以作为后续课题，但需要单独定义输入格式、校验和分析，不应直接套用当前四钟案例的 PASS 标记。
