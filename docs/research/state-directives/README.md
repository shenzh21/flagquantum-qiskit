# F1：全状态指令与转译排列

这是诊断与研究资料，不是生产模块，也不由 pytest 自动收集。未修复问题及原因见 [研究结论](../../state-directive-research-20261123_150203.md)。

`reproduce.py` 是整理后的最小可运行复现：使用当前已安装的适配器，比较 save/set 在默认转译与 `routing_method="none"` 下的表现。没有修改上游或适配器，没有 source injection，也没有研究阶段的内存补丁。

```powershell
# 在仓库根目录，先按根 README 安装当前源码与 test extra
.venv\Scripts\python.exe docs\research\state-directives\reproduce.py
```

输出默认为 `.cache/state_directives_<UTC微秒时间戳>.json`；可用 `--output` 指定新文件，已有文件一律拒绝覆写。JSON 记录真实导入位置；请确认使用当前源码安装，而非旧 wheel。诊断捕获预期拒绝，不以进程退出 0 代表功能已修复。

`archive/` 保留 2026-11-23 的 36 个主案例、6 个补充检查、原始脚本与日志。均按字节复制并以 `.gitattributes` 禁用换行转换；`MANIFEST.json` 记录仓库相对路径、字节数与 SHA256。原脚本使用当时的缓存输出路径，已存为 `.py.txt` 防止被当作当前入口执行。特别是 followup 原脚本曾在研究进程内放宽 save 检查，它证明候选方案可行，不代表磁盘生产实现已修改。

原始研究清单中的 `.cache` 路径和未提交状态描述当时环境，保持原文；在本仓库克隆中请用本目录索引。历史 JSON 是观察记录，不作为新的数值验收，也没有将其拒绝/差异改写为通过。

本次可移植脚本的实际运行见 [4 个最小案例](results/state_directives_20261123T070703.055812Z.json)：默认 save/set 被拒绝；关闭该置换优化后均成功，set 的原线路与转译后测量结果均为 `01`。
