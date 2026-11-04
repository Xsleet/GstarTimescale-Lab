# 可直接编辑的 GSTAR 原生配置

这里的文件是完整配置模板，可以直接下载、阅读和修改。配置参数与核心求解实现分开提供；**修改这些文件不需要 C++ 源码或重新编译**。

| 文件 | 主要修改内容 |
|---|---|
| [Timescale.cfg](Timescale.cfg) | 起始时间、运行秒数、采样间隔、运行架构、输入与结果路径 |
| [session.obj](session.obj) | 参与对象、观测类型、各钟初始不确定度与过程噪声参数 |
| [file_table](file_table) | 上述配置与基础表的位置索引 |
| [svinf.dat](svinf.dat) | 四个示例对象的编号和名称；采用固定列宽格式 |
| [leap.sec](leap.sec) | 时间转换使用的闰秒表 |
| [pan_info](pan_info) | 当前 PFD 模板的面板表占位文件 |

模板默认是 **2 CSAC + 2 mRO、2026-01-01 开始、10 天、10 秒采样、centralized**。默认噪声配置对应公开的 [异构研究参数](../examples/heterogeneous/clocks.json)，不代表已标定的物理设备。这里不包含 CLK/PFD 数据。

## 推荐使用方式

已有自己的数据时，在仓库根目录复制出一个独立实验：

```powershell
New-Item -ItemType Directory -Path Runs/my_case
Copy-Item -Recurse config Runs/my_case/config
```

这会复制配置目录，不生成数据，也不调用程序。目录里多带一个说明文件不影响运行。随后直接编辑：

```text
Runs/my_case/config/Timescale.cfg
Runs/my_case/config/session.obj
Runs/my_case/config/file_table
```

把自己的标准 CLK/PFD 数据放到该实验的 `clk/`、`pfd/`，或在 Timescale.cfg 中指向已有数据位置。随后运行：

```powershell
Push-Location Runs/my_case
& ..\..\engine\GstarTimescale.exe config/file_table
Pop-Location
.\.venv\Scripts\python.exe tools/plot_results.py --results Runs/my_case/results --output Runs/my_case
```

也可以用文件管理器把整个配置目录复制过去。`file_table` 的 `TimescaleCfg`、`object` 两行指定实际读取的文件，所以可以保存多套 `.cfg`/`.obj`，再修改索引来切换。文件名大小写应保持一致。修改仓库根目录模板不会影响已经复制出的实验。

没有自己的数据时，先按[首页](../README.md)生成 10 天输入，再编辑该实验的配置、直接调用 exe、单独绘图。`--prepare-only` 负责初次准备，不要在手动改配置之后再次生成同一个实验。

`lab.py init/inspect/execute` 仍可使用，见[可选便利命令](../docs/convenience-commands.md)。

## 怎么修改

- **开始/结束**：`Start time&session length` 写开始年月日时分秒、持续秒数和时间系统。结束时刻由开始时刻加持续秒数得到；修改时间不会自动生成对应日期的数据。
- **输入/输出**：相对路径从实验工作目录解析，例 `clk/...` 指向实验根目录下的 clk。配置中的路径值不能含空格或引号。
- **架构**：`Estimation architecture` 可选 centralized、distributed_if、distributed_ci。
- **时钟参数**：session.obj 每行尾部的 `Phase:[初始标准差,扩散系数]`、`Frequency:[初始标准差,扩散系数]` 和 `Link_Noise:{Default:标准差}` 可修改。扩散系数不是指定 τ 的 ADEV；格式和参数含义见 [异构案例](../examples/heterogeneous/README.md)。
- **参数与数据的区别**：session.obj 描述求解器采用的先验和噪声假设，修改它不会改变已有 CLK/PFD 数据。若研究实际输入噪声的变化，需要重新生成数据；若研究模型失配，可以有意采用不同假设，并在实验记录中说明。
- **对象编号**：默认 0101/0102 为 CSAC，0103/0104 为 mRO；CLK 记录使用三位编号 101–104，输出标签 SIM1–SIM4。修改对象时要同步 session.obj、svinf.dat 与输入数据。
- **格式**：保留配置数据行前的空格、段落标记和字段名；svinf.dat 保留固定列宽。建议用 VS Code 等纯文本编辑器保存为 UTF-8，不要用电子表格软件重新排版。

其它模型和 ISL 需要匹配的输入、基础表与分析，不能只改一个开关就转换观测类型。完整字段和已知限制见 [配置指南](../docs/configuration.md)。
