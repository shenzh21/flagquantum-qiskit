# 验证范围

测试中的 Qiskit `Statevector` 仅作独立参考；生产后端必须进入真实 FlagQuantum。`test_backend.py` 包装 `fq.Circuit.sample` 并禁止 Qiskit `Statevector` / `BasicSimulator` 的执行入口，检查执行来源。

- `test_backend.py`：CPU counts、batch/memory和基础接口，包括位序、经典位映射、重复写位、多寄存器、相位、seed、默认选项和 RNG 隔离、容量与拒绝路径。
- `test_conversion.py`：严格导入、规范化、附带信息保留、layout 不重复应用、Job 防御性拷贝。
- `test_gate_semantics.py`：17 种 Target 门在非对称复振幅上的精确比较，分别验证 single/double。参考使用 Qiskit 的位序转换功能，实际值来自真实 FQ 状态；生产保存接口另由test_aer_compatibility.py验证。
- `test_user_circuits.py`：用户 ZIP 中全部 17 条 QASM 的端到端回归，每次写出独立的 `results/user_circuits_<UTC时间戳>.json`（含微秒）。原始线路没有测量，因此测试在副本中加入 `measure_all()`；0.2后端允许无输出线路返回空data，不隐式测量。
- `test_aer_compatibility.py`：参数绑定、保存/状态输入/矩阵/相位/输出预算及Aer差异。
- `test_dynamic.py`：经典控制、循环/表达式、真实FQ私有kernel来源。
- `test_noise.py`：量子通道、读出反馈、模型优先级、相关噪声。
- `test_primitives.py`：Qiskit通用V2 Sampler/Estimator。
- `test_benchmarks.py`：4 种精度组合的容差判定，以及双精度超差必须失败；worker 使用可控输出，仅验证 benchmark 工具逻辑。
- `test_gpu.py`：设备/精度验证与 CUDA 执行，其中 11 项需要实际 CUDA 环境。
- `drafts/phase1/`：原0.1测试与结果逐字节历史。
- `drafts/backend_contract_draft.py.txt`：原始草稿的逐字节存档，包含首版当时规划的 batch/memory 契约；当前0.2已支持这些功能。该文件仅为历史资料，pytest不收集它。

独立克隆后，先按 [README](../README.md) 创建 Python 3.11 环境并安装固定 CPU 依赖。随后在仓库根目录安装 editable 和测试依赖，再运行完整测试；已有环境无需重新创建。仅需检查已安装 wheel 时无需切换安装方式，但仍需测试依赖。测试不依赖原工作区、原始 ZIP 或相邻研究目录，也不会向 `sys.path` 注入外部源码。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

可按文件运行针对性回归，例如 `.\.venv\Scripts\python.exe -m pytest tests/test_aer_compatibility.py tests/test_dynamic.py tests/test_noise.py tests/test_primitives.py -q`。2026-11-23 独立审查完整运行了 CPU 215 通过、11 CUDA 跳过，以及 GPU 环境 226 通过（其中 11 项实际 CUDA），详见 [审查报告](../AUDIT-2026-11-23.md)；更早的 190 项是历史记录，见 [VALIDATION.md](../VALIDATION.md)。`test_user_circuits.py` 每次运行自动生成带 UTC 时间戳的新 JSON，不覆盖历史 `results/user_circuits.json`；部分运行或失败也保留独立报告，`all_passed` 不会误标为真。

用户数据位于 `fixtures/user_circuits/`。`PROVENANCE.json` 记录原 ZIP 路径、ZIP SHA256 和逐文件 SHA256；只复制了 QASM2 与 manifest，没有执行 ZIP 附带的 Python/QPY，也没有用其验证报告作为正确性证据。manifest 的 `source_gate_count` 描述导出前来源，不能直接当作 QASM 门数。

夹具路径由测试文件自身的位置确定。来源记录和历史报告中的绝对路径仅记录当时的执行环境，不是新环境必须存在的路径。`.gitattributes` 保留夹具、历史草稿和报告的原始字节，避免 Git 的换行转换破坏哈希证据。`drafts/` 下文件以 `.txt` 保存，不会作为当前 pytest 用例执行。

数据回归以原始无测量 QASM 的 Qiskit `Statevector` 概率为独立参考。实际 FQ 精确概率须同时满足最大绝对差 `2e-9`、L1 差 `2e-8`；再检查后端 8192 shots 的分布。固定 `seed_simulator=seed_transpiler=20261118`、double/CPU、Torch 一线程、Qiskit 优化级别 1。

采样阈值在运行前确定：单 bin 差使用 Hoeffding 加全部 bin/17 条线路的 union bound，累积分布差使用 DKW 加 17 条线路的 union bound，每组检验族的 `alpha=1e-8`。总变差另作记录，不假装有限 shots 必须等于精确概率。精确概率与统计采样使用不同验收标准；这些正确性测试不是性能基准。

JSON 的 `all_passed` 只有在全部 17 条实际执行并通过时才为真。文件还保存版本、原始与编译后门数/位数、哈希、误差、阈值、counts 和耗时；文件缺失代表尚无该次数据回归结果。
