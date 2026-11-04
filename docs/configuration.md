# 配置与自定义数据运行

核心程序从 `file_table`、`Timescale.cfg` 和 `session.obj` 读取配置。可执行文件封装了求解实现，**没有把运行模式、起始时间和数据路径固定在程序中**。

完整、可直接编辑的原生文件已放在公开的 [config 目录](../config/README.md)。将整个目录复制到自己的实验中，或者先按首页准备示例输入，然后直接编辑实验目录里的配置。主要流程是“编辑配置 → 直接运行 exe → 单独绘图”。

## 运行与绘图入口

| 入口 | 适用情况 | 行为 |
|---|---|---|
| `GstarTimescale.exe config/file_table` | 主要入口，直接执行编辑过的配置 | 读取标准输入并写出 IEM、SIM 和日志 |
| `tools/plot_results.py` | 对实际结果单独画图 | 可编辑路径、钟名、采样参数；输出图片与数值表 |
| `lab.py run` | 使用内置的四钟合成案例 | 生成输入和配置，运行核心，生成五线 ADEV 与 HTML |
| `lab.py execute` | 已有自己的配置与标准输入 | 按原配置运行核心，保留配置和输入；保存执行日志，不自动套用示例报告 |

内置生成器目前固定从 **2026-01-01 00:00:00 GPST** 开始，四只钟、10 秒采样。`--days` 调时长，`--architecture` 调架构，`--output` 调整个实验目录。它暂时没有 `--start`、`--end` 或外部 CLK/PFD 参数。

若使用其它起点、采样率、输入位置或已准备的数据，使用下面的配置入口，无需修改 C++ 或重新编译。

## 配置文件分工

`file_table` 指向配置和辅助表，例如：

```text
+FileTable
 TimescaleCfg config/Timescale.cfg
 object config/session.obj
 satinf config/svinf.dat
 leapsc config/leap.sec
 paninf config/pan_info
-FileTable
```

数据行前保留一个空格。上述路径都相对于**运行工作目录**，不是相对于 file_table 所在的 config 子目录。

`Timescale.cfg` 控制时间、采样、算法选项和数据路径；`session.obj` 控制参与对象、观测类型和各钟噪声参数。更换对象或观测链路时，两个文件及基础表必须一致。

## 哪些设置可以改

| 目标 | 配置字段 | 说明 |
|---|---|---|
| 开始时间与时长 | `Start time&session length` | 年月日时分秒、运行秒数、时间系统 |
| 结束时间 | 无单独 End 字段 | 结束时刻 = 开始时刻 + 运行秒数 |
| 处理间隔 | `Processing interval` | 单位秒，应与输入覆盖和插值能力匹配 |
| 估计架构 | `Estimation architecture` | `centralized`、`distributed_if`、`distributed_ci` |
| 解算范围 | `Timescale scope` | `satellite` 或 `constellation`，须匹配观测类型 |
| 钟状态模型 | `Clock Trend state num`、`Clock Harmonics state num` | 默认示例为二状态、零周期项；其它组合由核心校验 |
| 秩亏处理 | `Rank deficiency remedy` | 核心识别 NONE、SUMZERO、BROWN、GREENHALL、KPW；并非所有组合都已在本仓库验证 |
| 结果目录 | `Project directory` | 核心结果和 gstar.log 的位置 |
| 钟差输入 | `LEO Clk full name`、`GNSS Clk full name` | 文件名可使用 `-YEARDOY-` 等核心支持的日期占位符 |
| 轨道输入 | `LEO Sp3 full name`、`GNSS Sp3 full name` | ISL 等需要轨道的场景使用 |
| 观测输入 | `PFD data directory`、`ISL data directory` | 选择实际使用的观测目录 |
| 输出方式与日志 | `Distributed output mode`、`Clock state output flag`、`Log level` | 按核心支持的取值配置 |

例如，从 2026-01-01 00:00:00 开始，运行到 2026-01-11 00:00:00：

```text
 Start time&session length   = 2026 01 01 00 00 00 864000 [GPST]
 Processing interval         = 10

+File Directory
 Project directory           = results/custom_run
 LEO Clk full name           = input/clk/SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK
 GNSS Clk full name          = input/clk/SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK
 PFD data directory          = input/pfd
-File Directory

+Timescale Section
 Timescale scope             = satellite
 Estimation architecture     = distributed_if
 Clock Trend state num       = 2
 Clock Harmonics state num   = 0
 Rank deficiency remedy      = GREENHALL
-Timescale Section
```

这是需要修改的字段片段，不是独立完整配置。完整模板见 [Timescale.cfg](../config/Timescale.cfg)。实际输出历元还取决于输入覆盖、插值和初始化，不保证所有边界时刻都有输出。

## 切换秩亏补偿方法

五个选项始终开放，默认 GREENHALL 只表示初始选择。编辑实际实验目录中的 `Timescale.cfg`，在下面五个值中选一个；只保留一条生效的 `Rank deficiency remedy` 行。

| 值 | 对应方法 | 相关参数 |
|---|---|---|
| `NONE` | 无补偿对照 | 无 |
| `SUMZERO` | 显式约束 / Centroid | `SUMZERO constraint sigma`，默认 `1e-14` |
| `BROWN` | Brown | 本两状态案例无需增加参数 |
| `GREENHALL` | Greenhall | 本案例默认方法 |
| `KPW` | KPW | `KPW max weight`，默认 `0.5` |

例如从 Greenhall 切换到 Brown，复用同一份输入、保留两状态和其它参数，仅修改两行（分别在原来的 File Directory 和 Timescale Section 内）：

```text
 Project directory           = results/brown
 Rank deficiency remedy      = BROWN
```

在实验目录运行同一个 `GstarTimescale.exe config/file_table`。回到仓库根目录，对新结果绘图：

```powershell
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/manual_case/results/brown --output Runs/manual_case/brown
```

继续比较其它方法时，分别使用 `results/sumzero`、`results/greenhall`、`results/kpw`、`results/none`。不要把几个方法写进同一条配置；每次运行选择一个方法。也可以保存多套 cfg，由 file_table 的 TimescaleCfg 行切换。

如果想在准备时指定方法，可以使用下面任一种入口；它们都把选择写入可编辑的 Timescale.cfg：

```powershell
# 已有四 CSAC 数据
.\.venv\Scripts\python.exe tools/prepare_csac.py --method BROWN --output Runs/csac_brown
# 新生成的 2 CSAC + 2 mRO 数据；--method 同样接受上述五个值
.\.venv\Scripts\python.exe tools/run_demo.py --prepare-only --method KPW --output Runs/heterogeneous_kpw
# 可选的一键入口
.\.venv\Scripts\python.exe lab.py run --method SUMZERO --output Runs/heterogeneous_sumzero
```

手动编辑之后，直接运行 exe 或 `lab.py execute` 即可；再次执行准备命令不会替你切换已有实验。NONE 用于研究不补偿时的表现，不能因为它能完成运行就把它当成有效补偿结果。具体运行验证见[验证范围](validation.md)。

## 实际操作：直接运行

在已准备好的实验中编辑三个配置文件，随后在仓库根目录执行：

```powershell
Push-Location Runs/manual_case
& ..\..\engine\GstarTimescale.exe config/file_table
Pop-Location
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/manual_case/results --output Runs/manual_case
```

`file_table` 是程序的参数。若想使用另一套配置，把其中 `TimescaleCfg`、`object` 两行改为新的文件名，例如 `config/Timescale_noise.cfg` 和 `config/session_noise.obj`；程序命令可以保持不变。

原生命令中的相对路径都以 `Push-Location` 进入的实验目录为基准。`Project directory` 决定结果位置；它改变后，绘图脚本的 `--results` 也要对应改变。每个实验使用新的结果目录以保留旧结果；直接运行 exe 没有启动器的目录覆盖保护。

## 可选：通过启动器预览或记录执行

先复制一套原生配置，或把已有配置放到自己的实验目录：

```powershell
.\.venv\Scripts\python.exe lab.py init --output Runs/custom_case
```

init 不生成模拟数据，也不调用核心。直接编辑 `Runs/custom_case/config/Timescale.cfg`、`session.obj`、`file_table`，并准备覆盖所选时间段的匹配输入。配置预览不需要核心程序或科学计算依赖：

```powershell
.\.venv\Scripts\python.exe lab.py inspect --workdir Runs/custom_case
```

预览显示计算出的开始/结束时刻、架构、采样、输入路径、结果目录和辅助表路径。检查确认后运行：

```powershell
.\.venv\Scripts\python.exe lab.py execute --workdir Runs/custom_case
```

如果文件索引不叫 `config/file_table`，可以指定：

```powershell
.\.venv\Scripts\python.exe lab.py execute --workdir Runs/custom_case --file-table config/file_table_custom --timeout 3600
```

`--workdir` 可以是绝对路径；相对路径从本仓库根目录解析。`--file-table` 的相对路径和文件内所有相对路径，都从 workdir 解析。核心配置中的路径支持无空格的绝对路径，也可以使用 `../` 指向其它数据目录。

为防止覆盖结果，execute 要求 `Project directory` 不存在或为空。重跑时修改为新目录。控制台与执行记录放在 `logs/execute_<唯一编号>/`；记录包含配置路径、起止时间、配置与程序哈希、退出码和执行状态。输入和配置不会被启动器改写。

初始化后的配置与仓库根目录模板互相独立。编辑模板不会改变已有实验，重新 init 也不会覆盖非空实验目录。`prepare`/`run` 仍用于合成示例，会按生成器参数创建配置，不读取这套已编辑模板；不要用它们重新生成自己的配置实验。

## 需要注意的边界

- **年份限制**：当前核心版本会拒绝起始年份大于 2026 的任务。这是核心已有行为，与电脑当前日期无关；运行更晚数据需要维护者提供支持该日期的核心版本。
- **路径格式**：核心按空白分隔读取配置中的路径，不支持路径值内的空格或引号。工作目录本身可以带空格，此时在文件内用不带空格的相对路径。不要给 Project directory 使用日期占位符；输入文件名的日期占位符可以保留。
- **输入覆盖**：改起止时间不会自动生成对应日期的数据。CLK、PFD/ISL 及需要的轨道必须覆盖所选时间段。
- **观测匹配**：PFD 使用 `satellite + OBS P`；ISL 使用 `constellation + OBS I`，并需要轨道和正确的距离观测。不能只修改 scope 或一个字母就转换数据类型。
- **独立绘图**：`plot_results.py` 从实际文件读取日期和相位，并核对你指定的钟名及采样间隔；不依赖生成案例时的旧 manifest。首次使用按首页的集中式四钟案例操作。
- **报告范围**：`lab.py report` 仍服务于内置四钟案例，读取其 manifest 和标准 results 目录。不要把改过时间、模型或路径的自定义结果直接交给旧 manifest 生成报告。

当前配置入口支持已有标准数据的运行，不提供任意输入格式转换，也不宣称所有模式组合都已验证。已验证范围见 [validation.md](validation.md)。

## 成员钟退出与加入

[第 5.2 节实验](../examples/thesis-section52/README.md)提供四个异构钟组的完整输入，仍使用上述原生文件。额外的 `membership_schedule.tsv` 定义哪些钟在什么时段参与，`Timescale.cfg` 可修改固定协方差倍率或短窗初始化窗口。

修改日程后，执行 `tools/thesis_section52.py sync-pfd --case 实验目录`，使 PFD 观测端点与日程一致，再运行程序。同步只筛选现有观测、更新 PFD 路径，保留旧数据目录。动态成员使用集中式、PFD、二状态、Greenhall、无谐波；其他案例的补偿选项保持不变。
