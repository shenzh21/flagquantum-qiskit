# 0.2 验证记录

历史产品验收日期：2026-11-19。Windows / Python 3.11 / Qiskit 2.6.2 / 官方FlagQuantum 0.3.1 Windows ABI3 wheel / Torch 2.14.1+cpu / 测试参考Aer0.18.4。研究源码0.4.0未修改、未注入运行环境。测试时适配器为editable0.2.0；交付wheel另做安装验证。下述190项是历史累计用例，不代表2026-11-23独立仓库整理时重新跑过同一套测试；仓库验证应单列新记录。

## 2026-11-23 独立仓库验证

另一次完整验证基于 Git 快照 `c289a6d7eb5da9a3baf9de84b47043092120fc40` 的干净导出目录：**190 passed in 42.29s**，0失败、0错误、0跳过。确认导入干净目录源码后执行测试，再从同一快照构建0.2.0 wheel，安装至独立目标目录并从包目录外运行 Bell 与动态线路 smoke，均成功。复用现有固定版本依赖，不是新平台或从零下载依赖的验证。详细命令、导入来源、源码与 wheel 散列见 [repository_validation_2026-11-23.json](tests/results/repository_validation_2026-11-23.json)。这是新的完整运行，与下方186加针对性回归的历史记录分开；本段文档补充发生在验证构建后，未重建该 wheel，也没有替换本地历史交付包。

## 真实运行结果

- 完整测试：**186 passed in 33.71s**，0失败/0跳过，含全部17条用户QASM回归。
- 随后修正canonical全幅initialize相位：兼容模块 **42 passed in 16.35s**；新增逆序初始化差异特征例 **1 passed in 3.58s**。
- 累计 **190个不同用例通过**。这是完整186加针对性最终回归，不冒称最终版本一次190全量运行。
- `python -m pip check`：No broken requirements found；源码compileall成功。
- 最终0.2 wheel安装后，从包目录外导入确认来自`.venv/Lib/site-packages`；标准Bell（1000shots、seed7）为 `{'00':484,'11':516}`，compiled仍2位。原机器绝对路径保留在历史JSON中，不是复现所需目录。
- wheel目录外动态/reset/save/memory、噪声、parameter_binds、V2 Sampler/Estimator全部smoke通过，Aer.run被禁止；另一个独立子进程完全阻断Aer导入，核心Bell仍通过。当前`.venv`保留wheel安装而非editable。
- wheel包含13个Python模块和4个dist-info文件，无upstream/tests/缓存/venv；METADATA含构建时的0.2 README快照及aer extra，不包含后续文档/主页修改。SHA256为 `6d1576f07571d0aa4700df285b6b8ec78a74186166a95eb7e4ca2421948478a2`。
- 用户17条线路最大精确概率误差 `9.769962616701378e-15`，阈值 `2e-9`；L1阈值 `2e-8`。每条8192shots，统计容差事前设定，未按结果放宽。

完整版本/命令/源码哈希/测试哈希见 [phase2_verification.json](tests/results/phase2_verification.json)，JUnit分别为 [完整测试](tests/results/phase2_pytest.xml)、[相位回归](tests/results/phase2_phase_regression.xml)、[逆序初始化](tests/results/phase2_reverse_initialize.xml)。用户线路细节见 [user_circuits.json](tests/results/user_circuits.json)。

以下为项目根目录中的复现命令，不表示本次文档维护再次执行了测试。测试源码修改前先按README切换为editable；`--no-isolation`构建需要当前环境具备 `setuptools>=77` 与 `wheel`。

```powershell
.venv\Scripts\python.exe -m pytest -q --junitxml=tests/results/phase2_pytest.xml
.venv\Scripts\python.exe -m pytest tests/test_aer_compatibility.py -q
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m build --wheel --no-isolation
```

## 验证覆盖与来源

覆盖基础用户流程、17标准门×2精度、非对称端序与经典映射、多寄存器/重复写位、批次/绑定/memory/seed、输入和默认选项隔离、保存复相位/概率子集/期望/conditional/pershot、initialize三形式/纠缠子集/set_statevector/矩阵门、嵌套经典控制与循环预算、噪声顺序/局部优先/label/读出反馈、V2多PUB及metadata、空输出、保存预算及拒绝路径。

测试显式拦截AerSimulator.run、BasicSimulator与Qiskit Statevector演化入口，观测真实FQ sample及门/测量/reset/Kraus私有kernel调用；Statevector只作测试参考或生产结果容器。Aer在本环境已安装，仅用于扩展对象/局部通道表示和独立对照，不能沿用首版“环境没有Aer”的当前声明。

独立精确参考与统计对照分开：理想振幅含global_phase严格比较；噪声可能采用不同Kraus分解，比较物理密度/分布，不要求每shot纯态或随机序列一致。噪声2048shots的预定familywise Hoeffding容差为0.06750929627442243；这不是精确状态容差。

## 已确认的Aer差异

- [相关读出历史证据](tests/results/aer_correlated_readout_difference.json)：联合矩阵规定01读为10，本工具返回10、Aer返回01。后续装配诊断确认两条measure分别作用于 `[0]`、`[1]`，不命中Aer的 `[0,1]` 规则；本工具主动合并连续测量，属于规则语义扩展，不能据此声称FQ计算更准确。历史JSON原文保留，解释以本段及兼容矩阵的澄清为准。
- [初始化相位历史证据](tests/results/aer_initialize_phase_difference.json)：两边密度误差约1.13e-16，但保存振幅存在整体相位差。后续探针确认Aer预先给initialize向量乘顶层phase：全幅顺序路径替态，逆序/部分路径reset+prepare可能同时保留旧态phase；本工具后者不额外重乘。这是尚未修正的振幅API差异，不能用物理等价宣称完全兼容。
- Aer0.18.4末尾while在默认裁剪下触发Invalid jump destination；直接运行及transpile优化级别0～3均复现。原线路用 `AerSimulator(method="statevector", enable_truncation=False)` 后成功 `{'1':13}`，不是漏调用transpile。历史测试的循环后最终测量保留；工具另有循环终止和超预算测试。

2026-11-20补充诊断使用显式statevector，而非把旧automatic记录重新命名：[三差异检查](tests/results/diagnostics/statevector-differences/results.json)、[相位分支探针](tests/results/diagnostics/statevector-differences/phase_probe.json)、[while调用与测量装配](tests/results/diagnostics/statevector-differences/while_calling.json)。同目录包含原诊断脚本。JSON于仓库整理时逐字节复制，未改写历史结果；需要重跑时先把脚本复制到新的临时目录，它们会在自身目录输出JSON，避免覆盖这些证据。汇报页的 `site/report-assets/trace_bell.py` 亦为当时wheel环境的诊断脚本，其安装方式字段描述当时环境；不要将源码安装后的重跑冒充原记录。

完整边界见 [COMPATIBILITY.md](COMPATIBILITY.md)。以上耗时是单次验证记录，不构成性能结论。

## 用户数据和历史证据

原ZIP：`standalone_random_circuits.zip`，SHA256 `907a493c68b88c8085b9002483a0f5867b8bd1e16571cd05f652e652173aefc6`。仓库内已保留测试所需QASM与manifest，不需要原机器ZIP路径。仅复制数据，未运行外部脚本/QPY，未改原ZIP；逐文件来源见 [PROVENANCE](tests/fixtures/user_circuits/PROVENANCE.json)。

17条原始线路无测量，测试副本添加measure_all。零初态下均为单一基态输出，不能证明任意输入的完整幺正等价；复杂复振幅由其他测试覆盖。0.2已允许无输出线路成功返回空data，不再沿用首版无测量拒绝约束。

0.1历史86+17测试、无Aer环境与wheel报告保存在 `tests/drafts/phase1/` 及SHA256清单；`tests/results/verification_summary.json` 和 `wheel_smoke.json` 是旧版历史，不代表0.2。最终0.2 wheel目录外验证另见 [phase2_wheel_smoke.json](tests/results/phase2_wheel_smoke.json)。
