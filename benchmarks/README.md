# Benchmark 选型与探索记录

当前采用容易复现的轻量方案：**固定 3 个公开 QASMBench 输入，用独立进程分别执行 FlagQuantum 与 Aer，再对照 Qiskit Statevector。** 无需安装新的 benchmark 框架。完整候选调研保留在 [方案比较](research.md)。

此次选择的是 QFT 4 比特、QAOA 6 比特、Ising 10 比特，来源固定到上游 commit `357b942396d5c2b7cbc1c229c585a6ef5ccaebac`。线路来自公开套件，执行器和比较规则由本项目编写，不称为 QASMBench 官方认证。`nv-quantum-benchmarks` 和 qibojit-benchmarks 作为未来规模化计时框架备选，尚未安装或接入。

## 已完成的公开实例验证

CPU/CUDA double 的 3 个公开实例均通过原始振幅和归一化误差阈值 `1e-10`。主要对比使用同一个 Torch 2.11.0+cu128 环境，见 [同环境 CPU 报告](results/qasmbench_cpu_torch211_double_isolated_2026-11-23.json) 和 [GPU 报告](results/qasmbench_cuda_double_isolated_2026-11-23.json)。同时比较 FQ/Aer、FQ/原始电路的 Qiskit Statevector、Aer/原始电路，以及公共转译前后是否等价。

| 公开实例 | FQ CPU/GPU 对 Aer 的最大振幅误差 | Aer CPU 中位数 | FQ CPU 中位数 | FQ GPU 中位数 |
| --- | --- | --- | --- | --- |
| QFT 4 | 3.97e-16 | 1.047 ms | 3.187 ms | 10.807 ms |
| QAOA 6 | 3.67e-15 | 10.338 ms | 37.628 ms | 194.072 ms |
| Ising 10 | 3.96e-15 | 9.466 ms | 41.959 ms | 135.900 ms |

这是 i9-14900HX / RTX 5070 Laptop GPU 上 Windows/Python 3.11、FQ 0.3.1、Torch 2.11.0+cu128、Aer 0.18.4、Qiskit 2.6.2 的小规模试验；CPU 1 线程，预热 2 次、重复 5 次。时间包括引擎对象/作业开销及完整状态向量回到 CPU，不含公共转译、FQ 严格导入。GPU 计时前后同步。**这三例没有显示 FQ 或 GPU 加速，不能代表大线路性能。** Aer 仍用 CPU，不是 GPU 对 GPU 的框架横评。源文件、源码哈希、各次耗时和转换步骤均保存在报告。

初次 [Torch 2.14.1+cpu 的 double 报告](results/qasmbench_cpu_double_isolated_2026-11-23.json) 也保留原样：三例同样通过，但不与不同 Torch 版本的 GPU 时间混算加速比。主要表的 Aer 时间取自同环境 CPU 基线那一轮；GPU 轮也独立运行了 Aer CPU，原始报告内可见自然计时波动。

**FQ 默认 complex64 所对应的 single 也已完成 CPU/GPU 验证。** 使用同一个 Torch 2.11.0+cu128 + `triton-windows 3.6.0.post26` 环境，公开输入不变；结果见 [CPU single](results/qasmbench_cpu_single_reference_double_2026-11-23.json) 和 [GPU single](results/qasmbench_cuda_single_reference_double_2026-11-23.json)。

| 公开实例 | FQ GPU single / Aer double 最大振幅误差 | FQ CPU single 中位数 | FQ GPU single 中位数 |
| --- | --- | --- | --- |
| QFT 4 | 3.03e-8 | 3.163 ms | 11.015 ms |
| QAOA 6 | 1.15e-6 | 39.393 ms | 206.969 ms |
| Ising 10 | 2.80e-7 | 45.790 ms | 149.279 ms |

single 的振幅和归一化阈值预设为 `5e-5`；六个 FQ CPU/GPU 案例全部满足。GPU 最大归一化误差约 `9.59e-6`。**Aer double 在这里仅作为高精度正确性参照，不作为 single 的公平性能对手；性能表只比较同精度、同环境的 FQ CPU/GPU。** 本轮仍没有小线路 GPU 加速结果。

早先同精度 CPU single 的 [原始失败记录](results/qasmbench_cpu_single_isolated_2026-11-23.json) 保持原样：FQ 三例均完成，对 Qiskit 的最大振幅误差约 `1.71e-6`，最大归一化误差约 `1.52e-5`；Aer QFT 完成，但 Aer QAOA/Ising 子进程退出 `3221226356`。改用 double 参照不表示这个 Aer single 问题已修复。

记录中的 GPU 峰值是 Torch allocator 的 allocated/reserved 计数，不是整张显卡的所有驱动/运行时占用。初期缺少 Triton 时 GPU single 路径受阻；本轮安装兼容的可选 Triton Windows 实现后，才补测上述 single 结果，没有禁用官方 dispatcher 或偷偷改用 double。设备与接口证据分别见 [早期未装 Triton 的原生验证](../tests/results/gpu_native_validation_2026-11-23.json)（含 single 失败）、[保留 FQ 默认优化的 Triton 原生验证](../tests/results/gpu_triton_validation_2026-11-23.json)（实际 JIT/矩阵/CX/RY-RZ/loop 通过）及 [最新两精度适配器与 wheel 验收](../tests/results/gpu_triton_adapter_validation_2026-11-23.json)（226 项全套通过，其中 11 项实际 CUDA）。这些是不同阶段和层级的证据，不替代本页公开实例的数值与计时结果。

```powershell
# 每轮重跑先生成 UTC 时间戳；runner 也会拒绝覆盖已有输出。
$reportStamp = [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss.fffffff'Z'")
.venv\Scripts\python.exe benchmarks\run_qasmbench.py --output "benchmarks\results\qasmbench_double_$reportStamp.json"

# 若已准备本文对应的独立 GPU 环境：
.venv\Scripts\python.exe benchmarks\run_qasmbench.py --device cpu --fq-python .cache\gpu-research\venv\Scripts\python.exe --aer-python .cache\gpu-research\venv\Scripts\python.exe --output "benchmarks\results\qasmbench_cpu_torch211_$reportStamp.json"
.venv\Scripts\python.exe benchmarks\run_qasmbench.py --device cuda:0 --fq-python .cache\gpu-research\venv\Scripts\python.exe --aer-python .cache\gpu-research\venv\Scripts\python.exe --output "benchmarks\results\qasmbench_cuda_double_$reportStamp.json"

# single 用 Aer double 仅做正确性参照；两侧精度和比较用途写入报告。
.venv\Scripts\python.exe benchmarks\run_qasmbench.py --device cpu --precision single --aer-precision double --fq-python .cache\gpu-research\venv\Scripts\python.exe --aer-python .cache\gpu-research\venv\Scripts\python.exe --output "benchmarks\results\qasmbench_cpu_single_$reportStamp.json"
.venv\Scripts\python.exe benchmarks\run_qasmbench.py --device cuda:0 --precision single --aer-precision double --fq-python .cache\gpu-research\venv\Scripts\python.exe --aer-python .cache\gpu-research\venv\Scripts\python.exe --output "benchmarks\results\qasmbench_cuda_single_$reportStamp.json"
```

`--precision` 指定 FQ 精度；不提供 `--aer-precision` 时 Aer 跟随 FQ 精度，保持原有默认行为。显式选择不同精度时，报告将比较标记为 `accuracy_reference_with_different_precision`，不得计算同精度跨框架加速比。

当前容差按参与比较的精度确定：单引擎对 Qiskit 参考时，double 为 `1e-10`、single 为 `5e-5`；FQ/Aer 之间只要任一侧为 single，就使用 `5e-5`，两侧 double 才使用 `1e-10`。转译前后 Qiskit 参考比较仍为 `1e-10`。这是本项目预设验证标准，不是 Aer 官方统一容差。v4 修复了 FQ double / Aer single 被错误套用 `1e-10` 的问题，旧报告不改写。

原始 QASM、LICENSE、NOTICE 和初次下载 manifest 均保持原字节；manifest 中的失败状态是初次探索时的历史快照。本次 runner 明确记录移除的 barrier 和全局末端测量，仅修改内存副本，遇到中途测量、reset、控制流即拒绝；没有使用 `allow_lossy=True`。引擎分别运行在子进程，FQ 进程不导入 Aer，Aer 进程不导入 Torch/FQ。

## 文件与历史探索

本目录已做工作的真实范围：

| 文件 | 状态 |
| --- | --- |
| `run_pilot.py` | 本地自制线路生成与计时原型，**不是 MQT Bench 或 QASMBench 的官方实现** |
| `results/cpu_double_pilot_2026-11-23.json` | 5 个本地线路族 × 3 个规模 × 2 个种子，共 30 个 double 案例完成；不是完整模拟器正确性证明 |
| `probe_aer_single.py`、`probe_aer_isolated.py` | 诊断本机单精度 QFT 子进程退出的最小脚本 |
| `results/aer_*_probe_2026-11-23.json` | 原始命令、stdout/stderr、退出码；原因尚未确定 |
| `fixtures/qasmbench/` | 3 份固定上游版本原始 QASM，附 LICENSE、NOTICE、来源和 SHA256 |
| `run_qasmbench.py`、`qasmbench_worker.py` | 当前轻量执行器：固定公开输入、显式预处理、独立引擎子进程；支持分别指定 FQ/Aer 精度 |
| `results/qasmbench_*_isolated_2026-11-23.json` | 当前公开实例的原始完成/失败记录；single 不全过 |
| `results/qasmbench_*_single_reference_double_2026-11-23.json` | FQ CPU/GPU single 对高精度参照，三例均通过；非同精度跨框架性能比较 |
| `history/*.py.txt` | v2/v3 及 v4 验证时执行脚本原字节快照，匹配报告中的源码哈希；当前 runner 为 v4 |

CPU double 原型的复现方式（每次生成新的时间戳）：

```powershell
$reportStamp = [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss.fffffff'Z'")
.venv\Scripts\python.exe benchmarks\run_pilot.py --precisions double --output "benchmarks\results\cpu_double_$reportStamp.json"
```

原型显式使用 `Circuit.state(refresh=True)` 且每次新建 FQ Circuit，避免把状态缓存命中当成模拟速度。记录公共转译、FQ 严格导入、每例首次调用与预热后的 5 次运行。比较完整主机状态向量，包括 FQ 的端序转换；它不是内核计时，也没有测量适配器端到端性能。CPU 线程固定为 1，不代表各框架最优性能。

已完成 double 试验的 FQ/Aer 最大振幅绝对误差约 `5.56e-16`。4 和 8 比特案例还对照了独立 Qiskit Statevector；12 比特案例只做 FQ/Aer 对照。无噪声、无动态测量、无 shot 抽样验证，无 GPU 结果和显存峰值记录，不可扩展这些结论。

早期自制单精度试验未完成：本机 QFT 子进程出现退出码 `3221226356`（Windows `0xC0000374`）；只运行 Aer 的一次进程成功，另一个计划先运行 Aer 后导入 FQ 的进程却在导入 FQ 之前已退出。**不能由这些有限记录归因于 FlagQuantum、Aer 算法或者库冲突。** 当前公开实例已经采用独立子进程，Aer 两例仍退出，原因仍待定位；没有设置 `KMP_DUPLICATE_LIB_OK` 等掩盖措施。

`history/run_qasmbench_v4_original.py.txt` 保留 v4 运行验证时的原始 CRLF 字节；当前维护脚本在 Git 中统一 LF，逻辑相同，旧报告 SHA256 仍可通过该归档核对。证据与上游夹具禁用换行转换及空白检查，避免为了格式整理改变原字节。
