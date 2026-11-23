# ADR 002：基础 Aer 功能兼容的执行边界

日期：2026-11-19。用户已明确授权在本轮实现基础模拟功能，覆盖此前第一阶段限制。GPU、多算法选择、分布式及性能调优不在本轮范围。

保留 `FlagQuantumBackend`，以 Qiskit Backend/Job/Result 和 Aer 指令对象表达 batch、memory、parameter_binds、保存状态/概率/期望值、初始化/矩阵门、动态控制和噪声。Aer 仅是可选的对象定义与测试参考依赖，生产不得调用 Aer/BasicSimulator/Statevector 计算线路。

实际执行依赖固定 FQ 0.3.1。保留受支持标准门、barrier与末尾测量且无活动噪声的 `Circuit.from_ir().sample()` 快路径；矩阵门、初始化和保存等走一般路径。一般路径由适配器解释 Qiskit 经典控制和保存位置，量子门、测量坍缩、reset、Kraus 通道分别调用官方 FQ `_apply_instruction`、`_measure_wire`、`_reset_instruction`、`apply_kraus_batched`；这些私有函数集中在 `fq_ops.py`，升级 FQ 必须重新做独立数值验证。不得把适配器写成第二个量子态演化器。

采用这一方案是因为 FQ DynamicCircuit 默认未测经典位为 -1 且拒绝提前读，而 Qiskit 经典位初值为0；FQ importer 也不能完整表达 Qiskit 结构化控制流及 Aer save 指令。适配层拥有初始经典零值、block bit映射、for局部参数、if/while/switch/break/continue、循环预算及输出聚合；FQ拥有量子数值。每个执行block的global_phase都要计入纯态。

标准静态量子段继续 strict importer；明确识别的矩阵门、初始化、save/control/noise 指令通过专门转换处理，不使用 allow_lossy=True。矩阵与振幅的Qiskit低位顺序只在表示转换边界反转，量子位身份和控制/目标不反转。

噪声转换允许 QuantumError→Kraus 的局部表示变换，但真正的状态演化使用FQ。预检局部矩阵/通道展开内存；门/reset后应用量子噪声，measure前应用量子噪声，读出噪声在真实坍缩后修改经典观测。局部noise覆盖默认noise，门label作为匹配键。相邻测量组支持共同读出矩阵。

2026-11-23整理时补充已核实边界（不改变实现）：连续测量合并属于本工具的匹配扩展，Aer0.18.4逐measure查qubits键，单比特measure不命中双比特规则；initialize全幅替态与部分reset+prepare分支对旧相位的处理不同，当前部分/逆序初始化仍有振幅兼容差异；Aer末尾while诊断可用 `enable_truncation=False` 正常执行。依据及原始诊断见 [兼容矩阵](COMPATIBILITY.md) 与 [验证记录](VALIDATION.md)，不能把这些差异统一归因于模拟算法。

save_statevector默认single（最近一次），probabilities/expectation默认average；pershot/conditional/unnormalized按子类型处理，conditional按保存位置的经典值分组。重复label及counts/memory保留键拒绝。无任何输出请求可成功返回空data，不隐式补测量；存在经典寄存器及显式输出时保留经典零值。batch按输入及参数绑定序展开；memory使用逐shot hex值，Result负责显示寄存器分组。single仅保留最后值、average/accum在线sum/count，list才保存所有值，跨label/conditional bucket/循环累计检查预算。

所有输入/未执行分支在数值执行前预检；循环有每shot明确上限。资源预算包括输出保存和局部矩阵。禁止忽略不支持的选项、静默改精度/设备或模拟器。

验收分为API/绑定/经典映射、精确状态/相位/期望值、初始化/矩阵门、动态控制、量子/读出噪声、通用V2 primitives及既有回归。旧否定用例保留历史副本，新功能用正例替代旧拒绝；不能仅以拒绝代表本轮类别已实现。
