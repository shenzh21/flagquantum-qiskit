# 0.2 基础 Aer 功能兼容矩阵

对照 Qiskit 2.6.2 / Aer 0.18.4，计算依赖真实 FlagQuantum 0.3.1；2026-11-19。支持指经过本项目测试的接口子集，不意味着复刻 Aer 所有选项。验证数量与运行证据见 [VALIDATION.md](VALIDATION.md)。

| 类别 | 已接通的接口与语义 | 明确边界 |
|---|---|---|
| Backend/Job/Result | transpile→run→counts，批次，hex原始memory与标准格式化，metadata，缓存同步Job | 无取消/异步队列/云服务 |
| 参数 | assign_parameters；parameter_binds每线路一个字典、等长值列表按index配对；含global_phase | 不做笛卡尔积；执行前不能有未绑定参数 |
| 标准门 | id,h,x,y,z,s,sdg,t,tdg,rx,ry,rz,p,u,cx,cz,swap，measure/reset | 其他门先transpile；未知custom不能仅凭name冒充支持门；开放控制先分解 |
| 初态/矩阵 | initialize字符串/整数/复向量、子集reset+prepare；UnitaryGate；全寄存器set_statevector可中途覆盖 | 有限/归一化/幺正预检；statevector覆盖要求全位且顺序一致；不支持set_density_matrix |
| 状态保存 | save_statevector默认最后一次，pershot列表，conditional经典hex分组 | 全寄存器；返回Statevector容器；不支持save_density_matrix/unitary/stabilizer |
| 概率/期望 | save_probabilities/probabilities_dict，qargs顺序；save_expval的Pauli组合；average/unnormalized累加/pershot/conditional | probabilities_dict为整数键；不支持save_expval_var；重复label或counts/memory保留键拒绝 |
| 中途测量/reset | 真FQ坍缩/reset；量子位到经典位映射；初始经典0；重复写位覆盖 | 不返回自动逐步轨迹 |
| 经典控制 | if/else，for含局部参数，while，switch含default，嵌套break/continue；Bool/Uint表达式 | 不支持Store/standalone Var、Float/Duration、stretches；每shot与for编译展开有预算 |
| 噪声 | Aer NoiseModel默认/局部量子误差；Kraus/QuantumChannelInstruction；常见Pauli、depolarizing、amplitude/phase damping、reset类通道；读出误差 | 局部通道最多5位且受内存预算；custom passes/nonlocal noise和重叠相关读出组拒绝 |
| 噪声顺序 | gate/reset后，measure前，真实坍缩后读出；local覆盖default；gate/matrix按label匹配，measure/reset等按name | 典型转译会分解门，NoiseModel须匹配提交线路的实际门；不自动改写噪声模型 |
| V2 primitives | Qiskit BackendSamplerV2 / BackendEstimatorV2通用包装器，多PUB、多寄存器与metadata | Estimator是采样估计，非默认精确值；按Qiskit wrapper契约准备线路 |
| 空输出 | 无测量/save可成功返回空data；不偷偷补测量；零classical Sampler PUB为空DataBin | get_counts在无counts时按Qiskit报错 |
| 设备/精度 | CPU 已有验收；本地新增 cpu/cuda/cuda:N；CPU/CUDA complex64/complex128，同设备局部 RNG | 原生默认 single/double 路线通过；最新两精度适配器验收通过，CUDA single 缺 Triton 明确诊断，见 GPU.md；无方法选择/多机/自动微分/性能承诺；不保证 CPU/GPU 逐 shot 相同 |

## 不能混同的细节

1. FQ使用MSB振幅顺序，Qiskit使用LSB；矩阵、状态向量、概率子集与Kraus均在明确边界转换一次，不交换控制/目标身份。block的局部qubits/clbits映射到提交线路；每次block的global_phase进入状态。
2. 噪声从有限维QuantumError转换为canonical Kraus后由FQ抽样。与Aer混合unitary实现可能有不同轨迹分解，逐shot纯态、整体相位及同seed样本不承诺一致；检验量子通道/密度/平均分布。无噪声相位敏感输出仍严格比较。
3. 相关读出组要求连续测量序列包含整组量子位。本工具主动合并连续测量，再应用联合读出矩阵，这是相对于 Aer0.18.4 的规则匹配扩展，并非 FQ 数值更准确。Aer 按单条 measure 的 qubits 键查找规则；测试的两条单比特 measure 分别为 `[0]`、`[1]`，不匹配 `[0,1]` 联合规则。因此同一规则下本工具把01读成10，而 Aer 保持01。当前尚未改为逐指令兼容语义；[固定版本源码](https://github.com/Qiskit/qiskit-aer/blob/0.18.4/src/noise/noise_model.hpp#L589) 与 [装配诊断](tests/results/diagnostics/statevector-differences/while_calling.json) 支持这一解释。
4. Aer0.18.4 的某个末尾 while 例在默认裁剪设置下报 `Invalid jump destination`；直接 run 和先 transpile（优化级别0～3）均复现。显式 `AerSimulator(method="statevector", enable_truncation=False)` 后原线路成功，不需要额外末尾测量。这不是遗漏转译，也不是状态向量算法不同；[诊断记录](tests/results/diagnostics/statevector-differences/while_calling.json) 包含成功配置。历史对照测试中的末尾测量仍原样保留，本工具实现未因此改变。
5. single仅保留最后值，average/accum在线累计，list保留每次保存；conditional每个键独立聚合。与Aer优化后的静态pershot列表长度细节不承诺完全一致；动态保存按实际访问记录。累计结果预算针对单实验，不能视为整个进程的严格配额。
6. 经典寄存器必须是不重叠、连续的标准布局；loose classical bits/别名寄存器拒绝，防Result显示错误。用户metadata可包含Qiskit对象，保留但不整包传给FQ。
7. Aer是可选的指令/NoiseModel对象来源，核心Bell、动态与V2线路可以不导入Aer。生产不得调用Aer.run/BasicSimulator/Statevector演化；Statevector容器和局部Kraus表示转换不是替代计算引擎。
8. canonical顺序全幅 initialize 清除旧态和旧分支相位，再乘顶层 circuit.global_phase；set_statevector 则清除此前全部相位且不重加顶层 phase。Aer0.18.4 在 initialize 中先给准备向量乘顶层相位：全幅顺序分支直接替换旧态，而逆序全幅/部分分支 reset 后作用准备态，可能同时保留旧态相位，形成额外相位因子。本工具后者采用 reset+prepare，没有额外重乘顶层相位，因此保存振幅存在真实 API 兼容差异；所诊断组合的密度/观测等价不能代替逐振幅一致。目前尚未更改实现。[相位探针](tests/results/diagnostics/statevector-differences/phase_probe.json) 和 [Aer initialize 源码](https://github.com/Qiskit/qiskit-aer/blob/0.18.4/src/simulators/statevector/statevector_state.hpp#L984) 提供机制依据，不以这些特例放宽一般理想相位验收。

## 全局状态指令的转译限制（未修复）

[Issue #1](https://github.com/shenzh21/flagquantum-qiskit/issues/1) 跟踪此项。默认优化级别 2/3 消去 SWAP 后，完整 `save_statevector` / `set_statevector` 的 qargs 可能被排列；当前后端仍要求标准顺序并拒绝。save 与 set 需要分别修复，不能盲目删掉检查。全连接后端可临时使用 `routing_method="none"`，且不主动重排 initial_layout。详见 [研究](docs/state-directive-research-20261123_150203.md)与 [可运行复现](docs/research/state-directives/README.md)。

## CUDA 接入状态（2026-11-23）

本次源码更新纳入 GPU 接入，版本仍为 0.2.0；不发布新 wheel。设备默认 CPU；CUDA 不可用、编号错误或与 CPU 专用采样开关冲突时明确拒绝，不静默转回 CPU。Torch 包约束扩为 `>=2.11,<2.15` 以容纳独立 CUDA 环境；这不是对区间内每个版本完成验收的声明。Qiskit 2.6.2 与 FQ 0.3.1 继续精确固定。此前 double-only 阶段 CPU 完整检查为 214 passed、6 CUDA skipped（33.89s）；CUDA 环境全套为 220 passed、0 skipped（38.89s），其中实际 CUDA 用例为 6 个，其余多数默认 CPU，不能把 skip 或全部 220 项算成 CUDA 数值验证。旧原生 probe 因当时缺 Triton 导致 single 失败，报告总体 all_passed=false 保留；新环境安装 triton-windows 3.6.0.post26 后，保持全部 FQ 默认优化的 single probe 已通过。当前适配器恢复 CUDA single/double，缺 Triton 时明确诊断，最新完整验收已通过。详细安装和边界见 [GPU.md](GPU.md)。

[double-only 阶段适配器报告](tests/results/gpu_adapter_validation_2026-11-23.json)另确认独立安装 wheel 的目录外 CUDA Bell/动态反馈 smoke 与 pip check 通过。此结果在验证 wheel 构建后补入文档，没有重测或重建；文档变化不代表 wheel 内嵌说明同步更新。

最新 [Windows Triton 原生报告](tests/results/gpu_triton_validation_2026-11-23.json) 全通过；安装 Windows 分发包不改变 FQ 源码或默认优化，也不意味着主线 Linux wheel 支持 Windows。安装方法见 GPU.md。

最新 [默认 Triton 适配器验收报告](tests/results/gpu_triton_adapter_validation_2026-11-23.json)记录 CPU 215 passed、11 CUDA skipped（33.94s），CUDA 环境 226 passed、0 skipped（41.47s），其中 11 个实际 CUDA 用例。冻结快照 wheel 的隔离安装、目录外 CUDA single Bell/动态反馈及 pip check 通过；本段为构建后文档补充，不重测或重建该 wheel。
