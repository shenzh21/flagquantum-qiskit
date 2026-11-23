# 架构与实现契约

0.2.0，2026-11-19。第一阶段理想末端采样已扩展为基础 Aer 功能；实际范围见 [COMPATIBILITY.md](COMPATIBILITY.md)，运行证据见 [VALIDATION.md](VALIDATION.md)。第一阶段历史测试留在 `tests/drafts/phase1/`。本工具是适配包，不是独立重写的量子数值模拟器。

## 主流程

```text
QuantumCircuit / 电路列表 + 可选 parameter_binds
  → Qiskit transpile(circuit, backend)（读取 backend.target）
  → backend.run：展开绑定、校验所有输入、规范化、捕获 sidecar
  → 受支持标准门、仅末端测量且无噪声：严格 import_qiskit → FQ Circuit.from_ir.sample
    或一般路径：program 编译经典控制/保存/初始化/矩阵门/噪声
                → trajectory 解释经典逻辑
                → fq_ops 调用固定版本 FQ 数值内核
  → 量子位/经典位写入映射、保存聚合、hex counts / memory
  → Qiskit Result + 同步 JobV1
```

不默认跑两套完整 passes。Qiskit负责依据Target分解/路由；适配器做必要结构校验与表示转换。FQ Circuit内部融合不等于完整FQ compiler；未接入 `fq.plan/run` 完整流程。切换路线必须另记ADR并验证语义。

## 模块责任

| 文件 | 责任 |
|---|---|
| backend.py | BackendV2/Options，批次展开后的调度，统一Job/Result |
| target.py | 已验证标准门和专用指令能力，拒绝仅凭name冒充门 |
| validation.py | 输入/参数/选项/容量/经典寄存器预检，快路径分类 |
| contracts.py | RunRequest、CircuitSidecar、PreparedCircuit内部类型 |
| conversion.py | strict importer与sidecar，保留用户信息但不灌入FQ |
| engine.py | 末端采样路径，FQ Circuit.from_ir.sample |
| program.py | 经典块映射/表达式预检，初始化分解、矩阵/保存/噪声专用指令转换 |
| fq_ops.py | 精确固定FQ0.3.1私有数值边界，端序转换、状态读取 |
| trajectory.py | Qiskit经典控制、局部RNG、每shot状态隔离、输出聚合 |
| noise.py | Aer NoiseModel/局部Kraus表示转换和经典读出矩阵采样 |
| results.py / job.py | 末端样本经典映射、结果容器、缓存结果与sidecar副本 |

源码在独立 `src/flagquantum_qiskit/`，wheel只包含包和metadata。上游源码不随仓库分发，也不依赖相邻研究目录。[官方固定研究提交](https://github.com/flagos-ai/FlagQuantum/tree/f0e74cf92f1784c5839c647a0781ad5db8cb6b85) 为0.4.0，实际依赖官方发布wheel0.3.1。

## 输入与规范化契约

1. 输入是一个QuantumCircuit或非空列表；parameter_binds每输入线路一个dict，各参数值等长并逐index绑定，包含global_phase。for循环局部参数在编译body时绑定。未绑定运行参数拒绝。
2. `shots` 为正整数；seed为局部生成器，不改全局Torch/NumPy随机状态。批次使用基础seed加实验index，稳定但不承诺与Aer同序列。
3. 标准幺正门经 `allow_lossy=False` importer；默认全零量子态。已识别的控制/测量/矩阵/状态输入/通道/保存走专门转换，不靠有损导入跳过内容。
4. metadata、register/label/barrier差异在sidecar保留。barrier只作为理想无时间调度语义的屏障忽略，工具没有定时/延迟噪声模型。标签仍参与门噪声匹配。
5. sidecar保存名称、metadata、memory slots、cregs、顶层phase/layout、测量写入词法顺序，以及嵌套block annotations/phase/metadata。动态实际分支由解释器执行；静态sidecar不是逐shot执行日志。
6. 所有bit身份来自提交的编译后线路，block的局部bits映射到item外层bits；不再次应用layout。Qiskit bit0为LSB，FQ statevector为MSB，转换边界集中在fq_ops/noise；bit身份本身不反转。
7. 标准连续不重叠cregs允许多寄存器与未写位；loose/alias/noncontiguous classical layout拒绝。任意用户metadata可保留，但不整体交给FQ。
8. 未执行分支也递归预检；未知custom gate、Float/Duration/Store/standalone经典变量等明确拒绝。无输出线路不补测量，空data可成功返回。

## 真实FQ执行边界

末端路径限于 `validation.is_fast` 接受的17种标准门、barrier和末尾measure，且无活动噪声模型或门条件；使用 `Circuit.from_ir(...).sample(...)`，一次抽样后由results按写入顺序映射。初始化、矩阵门、状态保存等即使没有中途测量，也走一般路径。一般路径以FQ初态开始，调用官方 `_apply_instruction`、`_measure_wire`、`_reset_instruction`、`apply_kraus_batched`。经典位初始0，适配器负责if/for/while/switch/break/continue；这是因FQ完整DynamicCircuit默认未写经典位为-1，不等价于Qiskit。

普通门保持严格导入；UnitaryGate转换局部矩阵端序并用FQ unitary Instruction；initialize提取Qiskit标准StatePreparation定义，分解到验证门集，由FQ演化。子集初始化先用FQ reset每位，不能直接替换纠缠子系统振幅。StatePreparation内部合成门不额外应用用户NoiseModel，initialize作为整体再应用自身噪声。

canonical全幅顺序initialize遵循Aer替换语义：清除旧态/旧分支phase，再应用顶层circuit.global_phase和准备态。Aer在initialize时预先给准备向量乘顶层phase，逆序全幅/部分分支的reset+prepare又可能保留原态phase。本工具这些分支没有额外重乘顶层phase，因而保存振幅存在尚未修正的API兼容差异；物理观测等价不能代替振幅一致，详见兼容矩阵。set_statevector全幅覆盖连同此前phase，按Aer行为不重加顶层phase；输入有限、归一化，转换索引一次。

每次进入普通block应用其global_phase，for/while重复block也重复应用。初态/输出向量处理只做表示与显式phase变换，禁止自行实现矩阵乘态、测量坍缩或通道演化代替FQ。

## 噪声与结果

NoiseModel局部误差优先于默认。gate/matrix使用label（存在时），measure/reset/initialize按name；量子噪声在普通门/reset后、measure前。读出矩阵在真实坍缩后采样，只改经典观测，再供条件使用。相关组必须在连续测量组中完整出现，重叠不明确组拒绝。主动合并连续测量是本工具的规则匹配扩展；Aer0.18.4按单条measure的qubits键查找，两个单比特指令不自动命中双比特联合规则。当前实现尚未改为该逐指令匹配语义。

局部QuantumError转换为Kraus是表示转换，最多5位并预检SuperOp/Kraus内存；真正作用量子态使用FQ。不同Kraus展开允许不同逐shot纯态/整体相位，同seed不要求与Aer一致；比较通道/密度/分布。

保存标签是Result.data键：statevector使用Statevector结果容器，概率数组或整数键dict，期望值实数。默认statevector是single最后值，probabilities/expectation是average；pershot list、unnormalized累加、conditional当前经典hex分组明确实现。single/average/accum在线聚合，只有list保留逐次；跨标签与conditional分组累计检查保存预算。重复标签和counts/memory保留标签拒绝。get_memory格式化由Qiskit做，内部保存hex逐shot列表。

Job同步完成，重复result不重算，sidecar属性返回副本。不持有FQ状态/IR作为Job副作用。experiment metadata标明引擎、版本、精度、方法；来源保证另有真实kernel拦截及替代引擎禁用测试，不靠metadata自证。

## 资源、验收与后续变更

num_qubits是容量上限，不是固定分配。max_memory_mb是预检和单实验输出累计预算，不是OS强制峰值配额；批次保留的总结果可能更大。max_loop_iterations限制每shot累计执行及for预编译展开；不能等待无限while。所有改变用户可观察语义的优化需先加等价性测试。

验收包括标准用户流程、端序/经典写位、相位敏感理想保存、初始化/矩阵、批次绑定/memory/seed/状态隔离、动态分支/循环、噪声通道/读出反馈、V2多PUB与metadata、17用户线路、负例、资源预算、实际FQ来源和wheel目录外安装。精确概率/振幅用数值容差，随机分布用事先固定统计阈值，不能把两者混为一谈。

Definition of Done：相关接口均有真实FQ阳性验收；未支持细节明确拒绝并记录；既有回归不破坏；不改upstream；wheel不含研究源码/缓存/venv；安装wheel后在仓库外运行标准流程；README/兼容矩阵/验证记录与最终版本一致。本地单卡 CUDA 两精度接入已另行授权，原生默认路线与最新两精度适配器回归均已通过本机验收，多算法选择与系统性性能调优仍不在本轮，不以性能承诺作为完成条件。

## 设备边界：本地 CUDA 两精度接入

`validation.normalize_device` 接受 `cpu`、`cuda`、`cuda:N`；CPU 请求不初始化 CUDA，`cuda` 规范化为校验时当前设备编号。CUDA 初始化失败、不可用设备和越界编号明确报错，不使用 CPU fallback。默认仍为 CPU。CPU/CUDA 都接受 `precision="single"` / `"double"`；适配器默认 CPU/double 不变。固定 FQ 0.3.1 的单精度 CUDA 默认优化可能调用 Triton；CUDA single 缺少可导入模块时提前报告依赖问题，不降级精度、设备或改写优化配置。Windows 使用已验证的 triton-windows 3.6.0.post26；模块存在仅是预检，实际版本兼容仍依赖真实数值验收。

快路径将设备传给 FQ `Circuit.from_ir` 与同设备局部 `torch.Generator`；FQ 采样后先验证张量设备/形状/值，再把样本传回 CPU 做经典位映射。一般路径的 FQ 初态、门/初始化矩阵、Kraus 算子和局部生成器使用请求设备，经典控制与结果组装留在主机；保存向量/概率显式回传 CPU 后包装为 Qiskit 结果。端序和量子位身份规则保持不变，数值执行仍来自真实 FQ。

CUDA 会检查当前空闲显存与保守估算；`max_memory_mb` 同时保留为输入接收与保存预算，不是显存预留或硬上限，其他进程与临时分配仍可能造成 OOM。FQ 0.3.1 的 `FQ_CPU_VECTORIZED_ROW_SAMPLING` 开关若启用，则明确拒绝 CUDA，而非改写进程环境。跨 CPU/GPU 不保证相同 seed 的逐 shot 样本相同；动态逐 shot 控制、状态回传与同步可能主导耗时。

本节描述本次纳入仓库的 CUDA 实现：未装 Triton 时的原生 single 失败与 double-only 适配器验收均保留为阶段历史。补齐 Windows Triton 后，所有 FQ 环境覆盖为空，真实默认 single 优化路径已验证；恢复两精度的适配器完整回归与隔离安装 wheel 已通过独立新验收，不使用旧阶段结果替代；本轮环境、安装、验证进展与限制见 [GPU.md](GPU.md)。

最新 [默认 Triton 适配器验收报告](tests/results/gpu_triton_adapter_validation_2026-11-23.json)：CPU 215 passed、11 CUDA skipped；CUDA 环境 226 passed、0 skipped，其中实际 CUDA 用例 11 项，其余多数默认 CPU。最终结果说明晚于验证 wheel 快照，本次只补文档、不改实现或重建。
