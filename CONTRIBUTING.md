# 参与实验仓库

欢迎反馈教程不清楚、安装不顺畅、生成格式或分析问题。请用最小合成案例说明问题，并提供复现命令。不要上传维护者发放的程序、私有源码、访问令牌或真实敏感数据。

本仓库只维护公开实验层。核心算法的问题由维护者回到私有工程处理；不要在公开 PR 中粘贴其实现。

运行公开工具测试（不需要核心程序）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

提交前暂存所需公开文件，再执行 `.\.venv\Scripts\python.exe tools/check_public_tree.py` 检查 Git 索引。不得使用 `git add -f engine` 绕过忽略规则。

Python 使用 4 空格缩进、pathlib 和临时目录测试。修改生成器应验证文件名、行数、双向符号、种子可复现性；修改分析应验证五条曲线、公共时间区间和目标 τ 直接计算。DataProcess 快照有哈希校验，不要只改快照代码而不检查来源。

提交消息采用 `feat(lab): ...`、`fix(report): ...`、`docs: ...` 等形式。PR 写清受影响流程、运行的检查和已知限制。
