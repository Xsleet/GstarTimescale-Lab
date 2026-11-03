# 故障排查

## python 找不到，或者版本不对

在 PowerShell 运行 `python --version`。使用 64 位 Python 3.11/3.12，关闭并重新打开安装前的终端。安装了多个 Python 时，可用 `py -3.12 -m venv .venv` 明确选择版本；后续命令始终使用 `.\.venv\Scripts\python.exe`。

## NumPy、pandas 或 matplotlib 导入失败

典型提示包括 `numpy.dtype size changed` 或 `module compiled using NumPy 1.x`。这通常是混用了环境或二进制依赖版本，不是核心算法报错。

在新的仓库副本中重新按 README 创建 `.venv`，安装 `requirements-demo.txt`。不要为了此实验批量升级系统 Python/Anaconda。执行 `lab.py doctor` 时会显示实际解释器路径，可以据此检查是否选错环境。

## 核心程序在哪里下载

向维护者领取对应版本 ZIP，网上只公开教程和脚本。没有维护者授权的程序包无法完成求解，但可以先学习文档和运行 `lab.py prepare`。

## Archive SHA256 mismatch / Runtime file changed

可能拿到了旧版本、下载不完整或文件被修改。核对 `engine-release.json` 的版本，向维护者重新领取匹配程序。不要删掉校验代码或自行改哈希以“让它通过”。若维护者确实升级了程序，请同时使用匹配版本的公开仓库。

## engine already exists

安装器保护已有安装，不直接覆盖。升级时将新版本公开仓库解压到新目录，再安装匹配程序包；保留旧目录便于复现实验。不要把新旧版本文件混合放在 engine 中。

## Output directory is not empty

`run` 和 `prepare` 都要求输出目录不存在或为空。换一个名字，例如 `--output Runs/heterogeneous_second_run`。如果只想重新绘图，使用 `lab.py report --output 原实验目录`。

init 同样拒绝覆盖非空实验目录，避免丢失已经编辑的参数。已有实验直接修改配置并使用 execute，不需要再次初始化。

## 修改 config 后，一键示例为什么没有变化

根目录 config 是公开原生模板，init 把它复制到实验目录；execute 读取实验里的实际配置。prepare/run 是合成示例生成器，会按照命令行选项独立生成配置。自己的实验请使用 init → 编辑实验目录里的配置并准备输入 → execute。

如果改的是根目录模板，之前已经初始化的实验不会自动更新；请直接编辑那次实验的 config 文件。

## 运行很久，或者磁盘空间不够

10 天案例生成完整 CLK/PFD 输入及多路结果，需要数百 MB 级空间；多组实验会累积。把仓库放在空间充足的磁盘，先检查 `Runs/` 下有哪些旧实验。确认完成归档后再自行清理，不要把程序包当作结果删除。

运行阶段查看 `logs/console.log` 和 `results/gstar.log`。不要只因为暂时没有 HTML 就重复启动。默认核心程序超时为 1800 秒，确有需要可以使用 `--timeout 3600`。

首次安装科学计算库时 pip 可能在系统临时目录解包；C 盘紧张时，可先在另一磁盘建立临时目录，并在当前 PowerShell 会话把 `TEMP`、`TMP` 指向该目录。安装时添加 `--no-cache-dir` 可减少持久缓存。

## 程序被安全软件隔离或报告缺少系统组件

该程序未做商业代码签名，不要通过关闭系统防护解决。先核对运行包来源和哈希，再由维护者或系统管理员检查。首版运行包只依赖 Windows 系统运行库；不要求复制编译工具目录中的 DLL。旧系统、ARM 或其它系统暂不在运行包支持范围内。

## execute 完成后没有 HTML

这是自定义配置入口的预期行为。它保留配置，检查退出码与日志，不默认把自定义结果交给四钟示例报告。使用对应的数据完整性检查和分析流程，见 [配置指南](configuration.md)。

## Project directory is not empty / start years after 2026

前者表示结果目录已有内容，请在 Timescale.cfg 中指定新目录，原结果不会被启动器清空。后者是当前核心已有的起始年份限制，不是电脑日期错误；更晚的输入日期需要匹配的核心版本。

## HTML 没生成或 ADEV 报错

先看退出码和错误消息。报告会拒绝不连续历元、NaN/Inf、原始钟与 IEM 不对齐、输出文件数不符等情况。不要删除数据行后掩盖问题。检查 `config/manifest.json` 是否与输入和配置对应，依赖是否安装在当前解释器中。

## 为什么最长 τ 只有很少的样本

这是长平均时间在有限长度记录中的统计限制，通常不是程序故障。默认 10 天案例在 τ=1 天时只有 8 个二阶差分项，见 [结果说明](results.md)。

## 报告问题时提供什么

提供 Windows/Python 版本、公开仓库版本、runtime 版本、命令、种子和最小错误文本。删除本机用户名、私有数据路径及敏感实验内容。**不要把 engine、维护者 ZIP、私有源码或包含这些内容的整个工程压缩包上传到 Issue。**
