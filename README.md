# GstarTimescale Lab · 时间尺度实验与分析工具

**时钟组合与时间尺度分析工具：生成时钟数据 → 运行组合时间尺度 → 打开报告 → 比较五条 ADEV 曲线。**

本项目提供 GSTAR 时间尺度的运行接口、实验配置、数据生成与结果分析工具。核心求解程序通过授权渠道单独提供，不在这个仓库、Git 历史或 GitHub Releases 中。安装运行包后即可使用，无需 C++ 编译环境。

可以运行内置合成案例，也可以通过 `file_table` 和 `Timescale.cfg` 接入已有标准数据。默认示例为 **2 只 CSAC + 2 只 mRO、10 天、10 秒采样**；另有四只同类白相位噪声模型的基础案例。内置案例使用 PFD 时钟比对，不需要 STK、轨道数据或 Jupyter。

**配置文件直接公开、直接编辑：** [运行配置 Timescale.cfg](config/Timescale.cfg) · [对象与噪声参数 session.obj](config/session.obj) · [文件索引 file_table](config/file_table) · [配置目录说明](config/README.md)。自己的实验推荐使用“复制配置 → 编辑 → 运行”的流程。

**论文实验入门：** [第 4.3 节：从数据到 ADEV](examples/thesis-section43/README.md)带你完成“下载数据 → 运行分析 → 打开报告”，解释秩亏补偿、ADEV 计算和图 4.7～4.11 的主要结论，**无需核心程序**。另有 CLK/PFD 输入与可编辑配置，供授权用户从观测重新解算。首次使用关注怎么算、怎么用、怎么看图，详细数据说明可按需阅读。

![异构案例的四只原始钟和组合时间尺度 ADEV](docs/images/heterogeneous-adev.svg)

*上图是固定种子的案例预览。CSAC/mRO 参数是研究预设，不代表某款物理钟的标定性能；单次结果不能证明所有情况下都能改善。*

## 第一次使用：按顺序做这六步

### 1. 下载公开实验仓库

点击本页右上方 **Code → Download ZIP**，解压到空间充足的磁盘；进入包含 `lab.py` 的文件夹。建议使用简短英文目录名。也可以使用 Git：

```powershell
git clone https://github.com/Xsleet/GstarTimescale-Lab.git
cd GstarTimescale-Lab
```

公开仓库 ZIP 和独立运行包是两个不同的文件。不要把受限分发的程序包上传到 GitHub。

### 2. 安装 Python，创建独立环境

需要 **Windows 10/11 x64** 和 **64 位 Python 3.11 或 3.12**。从 [Python 官方下载页](https://www.python.org/downloads/windows/)下载安装；安装时勾选添加 Python 到 PATH。依赖集合也支持 Python 3.10，但首版验证使用 3.11/3.12，暂不使用 3.13 及更新版本。

在这个文件夹打开 PowerShell，执行：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.txt
```

后续一直使用 `.\.venv\Scripts\python.exe`，**不需要执行 Activate.ps1**，也不需要修改 PowerShell 执行策略。独立环境可避免与已有 Anaconda、NumPy 等发生版本冲突。

### 3. 安装核心运行包

通过维护者认可的授权渠道获取 `GstarTimescale-engine-0.1.0-windows-x64.zip`。它没有公开下载地址。将下面引号里的内容替换为运行包的实际路径，**无需先解压**：

```powershell
.\.venv\Scripts\python.exe lab.py install-engine "GstarTimescale-engine-0.1.0-windows-x64.zip"
```

安装器校验整个 ZIP 和内部文件的 SHA256，安装到 `engine/`。版本不匹配、文件损坏或存在额外文件时会拒绝安装。安装不会执行 ZIP 中的程序。

### 4. 检查环境

```powershell
.\.venv\Scripts\python.exe lab.py doctor
```

看到 Windows、Python packages、Runtime SHA256 三项 `PASS` 后继续。有错误先看 [故障排查](docs/troubleshooting.md)。

### 5. 选择自己的配置，或先运行示例

**已有标准数据：直接编辑配置。**

```powershell
.\.venv\Scripts\python.exe lab.py init --output Runs/my_case
```

打开 `Runs/my_case/config/Timescale.cfg` 修改模式、时间与路径；打开 `session.obj` 修改对象及噪声参数。把匹配的 CLK/PFD 数据放入实验目录，或在配置中指向已有位置，然后运行：

```powershell
.\.venv\Scripts\python.exe lab.py inspect --workdir Runs/my_case
.\.venv\Scripts\python.exe lab.py execute --workdir Runs/my_case
```

init 只复制配置，不生成数据。execute 按编辑后的配置执行，不改写配置；详细操作见 [config/README.md](config/README.md)。

**没有数据：跑完整的 10 天异构示例。**

```powershell
.\.venv\Scripts\python.exe lab.py run
```

默认参数为 `--case heterogeneous --days 10 --seed 2026 --architecture centralized`。10 天是**仿真时间**，无需等待现实中的 10 天。程序先生成数据，再求解，最后绘图。运行耗时取决于电脑；日志位于实验文件夹的 `logs/`。请预留磁盘空间，完整案例会生成数百 MB 级数据。

### 6. 打开结果

上面的内置示例完成后，可以直接打开 HTML：

```powershell
Start-Process .\Runs\heterogeneous_10days\report.html
```

也可以在文件管理器中双击该 HTML。报告无需联网，包含：

- 四只原始钟和组合时间尺度的相位曲线；
- **五条 ADEV 曲线**，以及相同目标 τ 下的数值比较；
- 有效样本数、运行检查结果、CSV/TSV 数据和 PNG/PDF/SVG 图片链接。

从 [如何读结果](docs/results.md) 开始：先认识坐标和单位，再比较哪段平均时间上有所改善。

自己的配置通过 execute 运行时，结果位于 `Project directory` 指定的目录，执行记录位于实验的 `logs/execute_.../`。自定义分析须与对象、时间和状态模型匹配，不自动套用内置示例 HTML。

## 常用实验命令

每次实验使用新输出目录，已有结果不会自动覆盖。

```powershell
# 基础案例：四只同类噪声模型、不同噪声幅度的合成钟
.\.venv\Scripts\python.exe lab.py run --case basic --output Runs/basic_10days

# 换一个随机种子，仍运行 10 天
.\.venv\Scripts\python.exe lab.py run --seed 2027 --output Runs/heterogeneous_seed2027

# 只生成输入，不需要核心程序或科学计算依赖
.\.venv\Scripts\python.exe lab.py prepare --output Runs/inputs_only

# 已有结果重新生成报告，不重跑核心程序
.\.venv\Scripts\python.exe lab.py report --output Runs/heterogeneous_10days

# 查看所有选项
.\.venv\Scripts\python.exe lab.py run --help
```

`prepare` 生成的目录不能再交给 `run`，因为 `run` 会创建全新的实验。编辑已准备的配置后，使用下面的 `execute` 入口。

## 自己的数据、运行模式和时间范围

**这些参数可以调整，不需要重新编译核心程序。** `Timescale.cfg` 指定运行架构、开始时间、运行秒数、采样间隔、输入文件和结果目录；`session.obj` 指定对象和噪声参数。

```powershell
# 只复制原生配置模板，不生成数据
.\.venv\Scripts\python.exe lab.py init --output Runs/custom_case

# 编辑 Runs/custom_case/config/ 中的原生文件，并准备匹配数据
# 查看已有配置实际解析出的起止时间、架构和路径
.\.venv\Scripts\python.exe lab.py inspect --workdir Runs/custom_case

# 按已有配置运行，不重新生成数据或改写配置
.\.venv\Scripts\python.exe lab.py execute --workdir Runs/custom_case
```

也可以手动复制公开的 config 目录到实验中使用。init/execute 不会替你同步或覆盖参数；修改根目录模板只影响之后新建的实验。`prepare`/`run` 则是另一条合成示例流程，配置由生成器创建，不读取你修改后的根目录模板。

结束时刻由“开始时刻 + 运行秒数”确定。内置案例生成器的起点仍固定为 2026-01-01；自定义时间范围通过已有配置入口运行。当前核心会拒绝起始年份大于 2026 的任务。

完整字段、路径规则和运行示例见 **[配置指南](docs/configuration.md)**。自定义运行只检查退出码和日志，不自动套用内置案例的 HTML 分析模板。

## 文档导航

| 你要做什么 | 看哪里 |
|---|---|
| 认识时钟、PFD、时间尺度和文件结构 | [用户指南](docs/user-guide.md) |
| 调整模式、时间、采样和输入输出路径 | [配置指南](docs/configuration.md) |
| 从零开展几个小课题 | [分级实验任务](docs/experiments.md) |
| 理解相位、ADEV、长 τ 样本数 | [结果说明](docs/results.md) |
| 理解 2 CSAC + 2 mRO 的具体参数 | [异构案例](examples/heterogeneous/README.md) |
| 安装失败、没有图、运行目录已存在 | [故障排查](docs/troubleshooting.md) |
| 管理运行包、升级与私有工程 | [维护者指南](docs/maintainer-guide.md) |
| 查看哪些内容已经验证 | [验证范围](docs/validation.md) |

## 公开范围与适用边界

公开内容覆盖使用接口、配置和分析工具，核心求解实现通过独立 Windows x64 程序提供。没有运行包也可以阅读文档、预览配置和生成输入；实际求解需要授权运行包。

自动生成与报告流程目前围绕四钟、二状态、PFD 示例组织。自定义配置入口不限制为该示例，但 ISL、轨道、其它钟数和状态模型需要自行准备匹配数据与分析。分布式架构及其它模式不代表已在所有参数组合下完成验证。

`engine/`、`Runs/` 和二进制文件默认被 Git 忽略；提交钩子与 CI 检查公开文件。它们用于减少误提交，不是防拷贝或授权控制。请勿将私有程序包添加到公开仓库、Issue、Release 或 CI 附件。编译后的程序也不是不可逆的加密。

使用范围见 [LICENSE.md](LICENSE.md)，问题反馈见 [CONTRIBUTING.md](CONTRIBUTING.md)。
