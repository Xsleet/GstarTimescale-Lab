# 分级实验任务

每次只改变一个主要因素。完成后提交你自己的参数表、曲线、数据表和解释；不要提交教师的程序包。

## 实验 1：跑通并解释结果

运行默认 10 天案例。指出四只钟与 Ensemble，解释相位图和 ADEV 的不同含义。在精确 τ 表中取 10、1000、86400 秒三个点，记录 Ensemble、最佳单钟、二者比值及有效项数。说明为什么最长 τ 的证据比较弱。

## 实验 2：同类模型与异构模型

```powershell
.\.venv\Scripts\python.exe lab.py run --case basic --output Runs/lesson2_basic
.\.venv\Scripts\python.exe lab.py run --case heterogeneous --output Runs/lesson2_heterogeneous
```

基础案例是“初始钟差 + 固定频率偏差 + 白相位噪声”，四钟噪声标准差分别为 0.1、0.2、0.3、0.4 ns。异构案例加入白频噪声和频率随机游走，见 [参数说明](../examples/heterogeneous/README.md)。

观察哪个模型在不同 τ 有不同排序。两组实验的生成模型和滤波配置都不同，因此这不是严格的单因素“异构一定优于同构”证明。请解释比较的局限。

## 实验 3：随机性与可重复性

```powershell
.\.venv\Scripts\python.exe lab.py run --seed 2026 --output Runs/lesson3_seed2026
.\.venv\Scripts\python.exe lab.py run --seed 2027 --output Runs/lesson3_seed2027
.\.venv\Scripts\python.exe lab.py run --seed 2028 --output Runs/lesson3_seed2028
```

选定相同 τ，比较不同种子的 ADEV。先描述单次实验，再汇总多次实验。三个种子只适合练习；正式统计研究应根据目标误差设计更多重复。不要只保留结果最好的种子。

## 实验 4：集中式与分布式（教师指导）

```powershell
.\.venv\Scripts\python.exe lab.py run --architecture distributed_if --output Runs/lesson4_if
.\.venv\Scripts\python.exe lab.py run --architecture distributed_ci --output Runs/lesson4_ci
```

保持种子、时长和时钟参数相同，先检查各架构日志，再比较输出。在 CI 架构中同时记录选定节点和其它节点，不能只取一个节点就评价全网。默认教学验收以 centralized 为基准；这些选项供探索，不宣称所有异构参数下都已经通过性能验证。

## 实验 5：研究时长与统计支持

以 10 天为起点，再尝试 20 天，使用新目录。比较公共 τ 的有效项数及数值变化；长记录并不自动消除模型误差。启动器允许使用 `--days` 改时长，但起点固定在 2026 年，不能跨过该年的支持边界。

## 每次实验的记录模板

| 项目 | 填写内容 |
|---|---|
| 研究问题 | 你要检验什么，而不只是“运行成功” |
| 版本与环境 | 仓库版本、runtime.json、Python 依赖 |
| 输入条件 | 模型、种子、时长、采样、架构 |
| 改动 | 相对基准只改变了什么 |
| 检查 | 日志、完整性、公共区间、数值有限 |
| 指标 | 相同 τ 的 ADEV、比值、有效项数 |
| 结论边界 | 哪些只是本次合成实验的结果 |

真实钟数据接入、缺测、拓扑变化、ISL 和模型失配可以作为后续课题，但需要单独定义输入格式、校验和分析，不应直接套用当前四钟案例的 PASS 标记。
