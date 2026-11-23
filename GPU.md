# 单卡 CUDA 接入与验证

状态：2026-11-23，本次源码更新纳入 CUDA 单精度与双精度；安装 Windows Triton 后，原生默认单精度 probe 和两精度适配器最终验收均已通过；版本仍为 0.2.0，不发布新 wheel。历史 CPU wheel 不包含本轮 CUDA 实现。下面的命令供本轮源码使用，不表示任意机器已经验证。整体交付与已知未修复问题见 [交付整理](docs/delivery-2026-11-23.md)。下方阶段记录的未推送描述指记录形成当时。

## 环境与依赖

本轮设备为 NVIDIA GeForce RTX 5070 Laptop GPU，8 GB 显存，驱动 573.24；实际使用 Windows / Python 3.11 / Torch 2.11.0+cu128（CUDA 12.8）及 triton-windows 3.6.0.post26。本轮已确认 Torch CUDA 运算、FQ 双精度 Bell 与随机线路执行在真实设备上；不能仅凭设备存在或 `nvidia-smi` 的 CUDA 版本栏判定。

Qiskit 继续固定 2.6.2，FlagQuantum 固定官方 0.3.1，Aer 对照及对象来源固定 0.18.4。包的 Torch 约束调整为 `>=2.11,<2.15`，允许 CPU 已验证的 2.14.1+cpu 与本轮选择的 2.11.0+cu128；区间不是全版本兼容验收。先安装明确版本的 Torch，再安装本项目，避免依赖解析替换所选运行库。

本轮查阅的 [PyTorch 官方 cu128 wheel 索引](https://download.pytorch.org/whl/cu128/torch/) 提供 `torch-2.11.0+cu128-cp311-cp311-win_amd64.whl`。使用官方 CUDA 版 PyTorch 的运行库，不额外安装 CUDA Toolkit，不升级系统驱动。原有 CPU `.venv` 保留，CUDA 使用另一环境。

## 在新 GPU 环境安装

在本仓库根目录运行 PowerShell；已有可用 GPU 环境不必重建。示例使用 `.venv-gpu`，实际本轮安装可位于忽略的 `.cache` 子目录。两者均不应提交到 Git。

```powershell
py -3.11 -m venv .venv-gpu
.venv-gpu\Scripts\python.exe -m pip install --upgrade pip
.venv-gpu\Scripts\python.exe -m pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
.venv-gpu\Scripts\python.exe -m pip install triton-windows==3.6.0.post26
.venv-gpu\Scripts\python.exe -m pip install -e ".[test]"
.venv-gpu\Scripts\python.exe -m pip check
.venv-gpu\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CUDA unavailable')"
```

Windows 使用 [triton-lang/triton-windows](https://github.com/triton-lang/triton-windows) 的 [3.6.0.post26 分发包](https://pypi.org/project/triton-windows/3.6.0.post26/)，导入名仍为 `triton`。它是 Windows 移植分支，不是主线面向 Linux 的 `triton` wheel；这里不使用 `flagquantum[cuda]` 拉取主线包。该 Windows wheel 自带所需编译工具链，首次运行可能包含 JIT 开销，不需要额外安装系统 CUDA Toolkit。

`.[test]` 包含本轮验证需要的 Aer/pytest；只运行不含 Aer 对象的标准线路时，可安装 `-e .`。PyTorch 显示 CUDA 可用只是前置检查，仍需运行真实 FQ 和适配器测试。

## 用法

```python
from qiskit import QuantumCircuit, transpile
from flagquantum_qiskit import FlagQuantumBackend

backend = FlagQuantumBackend(device="cuda:0", precision="single")
circuit = QuantumCircuit(2)
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
compiled = transpile(circuit, backend, seed_transpiler=7)
result = backend.run(compiled, shots=1000, seed_simulator=7,
                     memory=True).result()
print(result.get_counts())
print(result.results[0].metadata)
```

- 默认 `device="cpu"`；`cuda` 使用校验时 Torch 当前 CUDA 设备；`cuda:N` 显式选择编号。
- 可在 `run(..., device="cuda:0")` 覆盖本次运行，不改变后端默认选项。
- 无设备、编号错误、CUDA 初始化失败均明确拒绝，不静默回退 CPU。
- CPU 与 CUDA 均支持 `precision="single"`（complex64）/ `"double"`（complex128）。适配器默认仍是 CPU/double；上面的 single 是显式选择，符合 FQ 原生默认数值精度。本轮没有改写 FQ 的配置或默认优化。CUDA single 缺少可导入的 Triton 时提前报告安装问题；检测到模块并不等于验证任意版本兼容。同 seed 不保证 CPU 与 GPU 产生逐 shot 相同结果，也不保证与 Aer 相同随机序列。

## 哪部分在 GPU，哪部分在 CPU

标准门且只在末尾测量的路径，由真实 FQ `Circuit.from_ir(..., device=...)` 演化与采样；样本设备验证后传回 CPU，按 Qiskit 经典位映射构造结果。一般路径中，FQ 状态、量子操作与局部随机生成器使用请求设备；Python 解释经典控制，保存值回传 CPU。GPU 并不替代 Qiskit 转译、经典分支或 Job/Result 组装。

## 限制与验收口径

- 只接入单设备；未实现多 GPU、分布式、多算法选择、自动微分或性能自动调优。
- 保守估算同时检查 `max_memory_mb` 和当时空闲显存。它不是预留或峰值硬保证，其他进程和 FQ/Torch 临时量仍可能导致 OOM；8 GB 也不是任意线路可用的固定容量。
- 若启用上游 CPU 专用 `FQ_CPU_VECTORIZED_ROW_SAMPLING`，CUDA 请求明确拒绝；用户需自行关闭该选项，适配器不修改进程环境。
- 动态执行逐 shot 调度，经典反馈、同步、矩阵准备和输出回传可能主导时间；小线路不承诺 GPU 更快。
- 最新两精度适配器验收：CPU **215 passed、11 CUDA skipped（33.94s）**；CUDA 环境 **226 passed、0 skipped（41.47s）**。其中 **11 个实际 CUDA 用例**，其余多数默认 CPU。此前 double-only 阶段的 220 项另存为历史。
- 精确振幅/概率按数值容差比较，随机样本按分布比较；不以相同 counts 冒充真实 GPU 执行证据。

本轮 benchmark 先采用少量固定 QASMBench 输入和轻量 Aer/FQ 比较脚本，便于本机复现；不是 NVIDIA 官方框架跑分。框架选型与未安装的候选方案见 [benchmarks/research.md](benchmarks/research.md)。历史 CPU 结果和本轮新记录分开维护，见 [VALIDATION.md](VALIDATION.md)。

## 阶段一：未安装 Triton 的原生探针（历史）

[原生 GPU 验证记录](tests/results/gpu_native_validation_2026-11-23.json) 保存成功与失败样本：

- CUDA 双精度 Bell 2048 shots：`00=1007`、`11=1041`；确认采样张量位于 `cuda:0`，局部 seed 可重放且全局 CUDA RNG 不变。
- 3、8、12 位随机双精度线路对 Qiskit 的最大原始振幅误差为 `5.93e-16`，均通过事前 `2e-11` 阈值；原生双精度字段 `complex128_cases_all_passed=true`。
- 单精度默认进入未安装的 Triton 分支；关闭四个单比特可选优化后，CX 序列仍会进入没有对应禁用开关的 Triton 路径。这说明单靠关闭局部优化不够；该阶段未安装 Triton，也未修改上游源码。后续通过安装匹配的 Windows Triton 解决，而非继续关闭 FQ 优化。
- **报告总体 `all_passed=false`**，它保留了单精度失败，不应被描述为所有原生测试通过。当时适配器暂限双精度并提前拒绝单精度；该阶段验收通过，仍不能抹去当时环境的原生单精度失败。

独立环境 `pip check` 通过，使用 setuptools 81；701 个 FQ Python 源文件保持原样。此探针不是吞吐 benchmark，不证明任意线路、显卡或 CUDA 版本兼容。

## 阶段一：double-only 适配器验收与构建快照（历史）

[适配器 GPU 验收报告](tests/results/gpu_adapter_validation_2026-11-23.json) 的 `all_passed=true`。CPU 全量结果在确认源码/测试哈希一致后复用；CUDA 环境执行完整 220 项，其中 6 项实际使用 CUDA，其他默认 CPU 用例也在该依赖环境通过。固定快照构建 wheel，安装至独立目标目录并从包目录外执行 CUDA Bell 与动态测量反馈 smoke，均通过；环境 `pip check` 通过。Bell 256 shots 为 `00=132, 11=124`，动态反馈 17 shots 为 `10=17`，报告确认 `device=cuda:0`。

这段验收结论在验证 wheel 构建后补入文档，没有重新运行测试或重建该 wheel；其 METADATA 中的 README 仍为构建时快照。该结论对应当时的 double-only 源码快照；随后恢复两精度的改动需新验收。版本仍为 0.2.0，改动尚未推送。

另有 [公开 QASMBench 实例比较](benchmarks/README.md)：同一个 Torch 2.11.0+cu128 环境中的 3 例 double CPU/GPU 数值均通过，但这些小线路 GPU 比 CPU 更慢；不作 GPU 加速承诺，Aer 对照仍是 CPU。

## 阶段二：保持 FQ 默认配置，启用 Windows Triton

[原生 Triton 验证记录](tests/results/gpu_triton_validation_2026-11-23.json) 的 `all_passed=true`。Torch 仍为 2.11.0+cu128，只在独立 GPU 环境增加 `triton-windows==3.6.0.post26`；所有 `FQ_*` 环境覆盖为空，没有关闭 FQ 可选优化，也没有修改其 701 个 Python 源文件或使用 CPU/其他引擎 fallback。

已实际执行 Triton JIT 向量加法、3/8/12 位随机 single 线路的单比特矩阵与 CX 序列，以及 20 位 RY/RZ pair 和 RX/RZ loop 优化分支。最大原始振幅误差约 `3.18e-7`，低于事前 `2e-5` 阈值；single Bell 4096 shots 为 `00=2037`、`11=2059`。运行统计确认相应优化分支确实执行，环境 `pip check` 通过。这是默认优化路线的真实数值验证，不是仅能导入 `triton`。

适配器现恢复 CUDA single/double，保留 CPU/double 默认；缺少 Triton 时对 CUDA single 给出明确依赖诊断。最新适配器全套与独立安装 wheel 的验收已通过，旧 double-only 报告保持原样。该验收记录形成时 GPU 改动尚未推送，版本仍为 0.2.0；本次源码更新已纳入。

## 阶段二：两精度适配器最终验收

[默认 Triton 适配器验收报告](tests/results/gpu_triton_adapter_validation_2026-11-23.json) 的 `all_passed=true`。CPU 215 项通过、11 项 CUDA 跳过的全套结果经源码/测试哈希匹配后复用；Torch 2.11.0+cu128 / triton-windows 3.6.0.post26 环境另行实际运行全套，226 项通过、无跳过，其中 11 项是真实 CUDA 用例。

冻结源码构建 wheel，安装到独立目标目录并从包目录外完成 CUDA single Bell 与动态反馈 smoke；Bell 256 shots 为 `00=132, 11=124`，动态反馈 17 shots 为 `10=17`，确认 `device=cuda:0`；`pip check` 通过。没有修改 FQ 源码、关闭默认优化或使用替代引擎。

此最终结果说明晚于验证 wheel 的构建快照，仅补文档，未重测或重建；wheel 的 METADATA 保留当时 README。当前版本仍为 0.2.0；该验收记录形成时尚未提交或推送，本次源码更新已纳入。

[公开实例报告](benchmarks/README.md)另含同环境、同精度 FQ CPU/GPU single 的 3 例验证；数值通过，这些小线路 GPU 仍更慢。Aer/Qiskit 的高精度参考和计时范围以该报告为准，不将不同精度耗时混为等价性能比较。
