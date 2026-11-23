# 全局状态指令与转译置换研究

研究日期：2026-11-23。对应完整审查 F1；只做研究，没有修改生产源码、正式测试或历史记录，没有安装依赖或提交推送。版本固定为 Qiskit 2.6.2、Aer 0.18.4、FlagQuantum 0.3.1。

## 结论与建议

**save 和 set 不能用同一个“删除顺序限制”补丁解决。**

- `save_statevector` 可以接受覆盖全体量子位的排列，继续返回**提交线路此刻的物理位序**，不依据 qargs 或 final_layout 重排振幅。这符合本项目现有位序契约，也与 Aer 对同一 compiled circuit 的结果一致。必须仍拒绝缺位/重复位/错误宽度。
- `set_statevector` 暂时应保留对非标准排列的明确拒绝，并提示使用不消除置换的编译流程。简单放开会把“目前拒绝”变成“能够运行但可能改变原线路的逻辑结果”。
- 本项目的全连接模拟器可以显式采用 `transpile(circuit, backend, routing_method="none")`，不提供非平凡 initial_layout，来保留本例的 SWAP 与 canonical 全局指令。该流程已实际验证；它不是任意耦合受限硬件的通用建议。
- 若要求所有带 set 的输入都继续使用无额外参数的默认 `transpile(circuit, backend)`，需要单独设计保留/规范化全局指令语义的编译集成或推动上游修复，不能声称换一下 Target 注册类型即可完成。

这是一项安全的分步建议，**不是已经完整修复 F1**：本次没有发布代码变化。

## 两位例子：读取与替换的区别

```python
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from flagquantum_qiskit import FlagQuantumBackend

backend = FlagQuantumBackend(num_qubits=2)
qc = QuantumCircuit(2)
qc.x(0)
qc.swap(0, 1)
qc.set_statevector([0, 1, 0, 0])  # 全局替态为 |01>
qc.measure_all()
```

原线路在 Aer 返回 `01`。默认转译消去 SWAP，并将后续 set/measurement 的接线交换；但 set 的数组仍是 `[0,1,0,0]`。Aer 用该数组直接替换整态，随后交换后的测量接线给出 `10`。当前适配器在 set 的 qargs 为 `[1,0]` 时拒绝，因此尚未静默产生这个错误结果。

若把 set 换成 save，save 只读取物理寄存器，没有把一个新的逻辑态写入错误的坐标。它可读取 compiled 的物理态 `[0,1,0,0]`；原线路的逻辑态是 `[0,0,1,0]`，两者通过该位置的置换相联系。返回哪种表示必须明确。本项目已选择提交线路的位序，所以不能暗中再应用 final_layout。

更强的反例：`x(0); save(before); swap; save(middle); swap; save(after)` 的最终 layout 已回到 identity，但中间保存所处的置换不同。原线路 middle 为 `|10>`，compiled 的 middle 物理态为 `|01>`。因此仅拿**最终** layout 统一修复所有保存位置并不成立。

## 固定版本源码解释

Qiskit 2.6.2 的 `DefaultInitPassManager` 在优化级别 2/3 且 `routing_method != "none"` 时加入 `ElidePermutations`。该 pass 位于布局之前；遇到 SWAP 更新内部映射，其余指令只替换 qargs，原参数保持不变。Rust 实现不接收 Target，没有“某个全局状态指令不可置换”的 Target 查询。[固定版本 init 插件](https://github.com/Qiskit/qiskit/blob/2.6.2/qiskit/transpiler/preset_passmanagers/builtin_plugins.py#L140-L154)、[固定版本 ElidePermutations](https://github.com/Qiskit/qiskit/blob/2.6.2/crates/transpiler/src/passes/elide_permutations.rs#L98-L114)。

Aer 0.18.4 的 save 检查指令宽度后复制整条物理状态向量；set 分支直接用参数数组初始化整个寄存器，均不依据 qargs 的顺序重排。initialize 则显式接收 qubits 参数，所以同样的接线变换能够正确作用到局部准备态，不能把 initialize 与 set 当成可直接互换的别名。[固定版本 Aer 状态执行与保存](https://github.com/Qiskit/qiskit-aer/blob/0.18.4/src/simulators/statevector/statevector_state.hpp#L500-L572)、[initialize 路径](https://github.com/Qiskit/qiskit-aer/blob/0.18.4/src/simulators/statevector/statevector_state.hpp#L984-L1018)。

Aer 的公开文档将 save/set 描述为全宽模拟器状态指令，而不是一个可任意对子系统施加的普通局部操作；文档本身未完整规定所有排列场景，因此上面的固定版本实现和实际探针是本研究关于顺序行为的直接依据。[Aer 指令库](https://qiskit.github.io/qiskit-aer/apidocs/aer_library.html)、[保存指令方法](https://qiskit.github.io/qiskit-aer/apidocs/circuit.html)。

## 实际验证的备选方案

本次运行 36 个主探针与 6 个后续检查，均使用小型 CPU 线路，不作性能结论。

| 尝试 | 观察 |
|---|---|
| 手工将 Save/Set append 到 `[1,0]` | 非对称复态 `[1,2j,3,-4j]/sqrt(30)` 与 `[0,1]` 顺序的 Aer 输出完全相同，确认忽略 qargs 顺序 |
| Target 改用具体 `SaveStatevector`/`SetStatevector` 类 | 仍消去 SWAP，仍将 qargs 改成 `[1,0]`；不能修复 |
| 直接以 AerSimulator 为 transpile backend | 同样出现 set 的全局输入与测量重排不一致，适配器并非唯一触发方 |
| `routing_method="none"`，不指定 initial_layout | 不运行 ElidePermutations，SWAP 保留；set 示例 Aer/FQ 都返回 `01` |
| `optimization_level=0` | 本例保持原接线，Aer/FQ 都返回 `01`；代价是减少整体优化 |
| `qubits_initially_zero=False` | ElidePermutations 仍执行，无效 |
| `initial_layout=[0,1]` | ElidePermutations 仍在实际布局之前执行，无效 |
| 插入 barrier | barrier 也只被重映射，不清除置换，无效 |
| `routing_method="none", initial_layout=[1,0]` | 初始布局本身仍可排列全局 set，原 Aer `01`、compiled Aer `10`；该安全示例不覆盖用户主动重排初始布局 |
| 研究进程内仅放宽 save 的完整覆盖检查 | 三个不同保存位置均与同一 compiled circuit 的 Aer 振幅误差 0；set 检查保持原样，磁盘源码 SHA256 未变 |

主探针开始时曾尝试 Aer 默认容量加显式 initial_layout，造成编译宽度大于原保存宽度，Aer 明确拒绝；最终矩阵省略该大容量组合，且数值 helper 限制至 4 位。另一次试图给 Target.num_qubits 赋值被只读属性拒绝。两个探索错误单独保留日志，不算通过案例或新的适配器缺陷。

## Target 和 backend hook 能做什么

Target 主要表达指令种类、参数、允许 qargs 和设备属性，没有“全局态参数在置换下必须同步改变”的专用语义字段；而本次 elision pass 不读 Target。把通用 Instruction 类换成具体 Aer 类的实测结果也印证这一点。[Target 文档](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qiskit.transpiler.Target)。

BackendV2 提供自动选择 translation/scheduling stage plugin 的公开 hook，没有对应的 init/routing 默认 hook。`get_translation_stage_plugin()` 所选阶段晚于已经发生的 init elision：它可以做后续验证或专门的语义规范化，但不能凭这个 hook “提前不执行” elision。若用它恢复 set，必须明确可靠获得每个位置的源坐标、原始指令含义与布局变换，且覆盖手工 reversed qargs、重复保存/替态和控制流；不能靠最终 layout 猜测，更不应偷偷重跑第二套完整 passes。[BackendV2 官方 hook 说明](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qiskit.providers.BackendV2)。

可行但需另行设计的长期方向是：使用显式受控的 init stage/pass manager，在全局状态指令存在时禁止不保语义的置换，或使上游 pass 在这些指令处正确物化/规范化映射。仅提供一个可选 `init_method` 插件仍需要调用者显式选择，不等于无参数默认 BackendV2 工作流自动修复。更改全局 Qiskit 状态、猴子补丁上游、将 set 偷换成 initialize 均不建议。

## 上游归属与必须回归的范围

set 的逻辑差异可在只使用 Qiskit/Aer 时复现，且源码能解释原因；因此可以确定是固定版本组合的转译与全局指令语义互操作缺陷。**没有查到或声称维护者已确认的对应 issue/修复版本**，不把自主推断写成官方结论。save 的物理输出变化本身则不等于数值错误，需要按 API 表示契约解释；适配器对全宽排列的拒绝属于自身限制过严。

建议后续实施时至少覆盖：

1. save：默认/0/1/2/3 优化、完整手工排列、非对称复态、两次 SWAP 与中间保存、conditional/pershot、嵌套全宽映射；比较同一提交线路的物理向量，同时显式区分原逻辑向量。
2. set：`swap; set|01>; measure_all`、非对称复态、set 前后门与多次 set、非平凡 initial_layout、手工 reversed qargs；同时比较原线路与转译线路的测量映射，不能只看保存的数组恰好相同。
3. 输入完整性：部分位/重复位/错误维数仍拒绝；相位覆盖契约不变；不引入 layout 二次应用；initialize 的现有差异单独保持。
4. CPU/CUDA × single/double 的代表性用例；若增加编译 plugin，wheel entry point 与包目录外标准调用需要单独验收。

可立即使用的已验证流程（本项目全连接 backend，无额外初始布局）：

```python
compiled = transpile(qc, backend, optimization_level=2, routing_method="none")
result = backend.run(compiled, shots=8).result()
assert result.get_counts() == {"01": 8}
```

没有进行生产修复，未重跑不相关完整测试。研究证据见下方带时间戳清单；源代码和审查前既有结果/fixtures/历史归档哈希保持不变。其他 agent 正在授权修改的报告输出逻辑不归本研究所有，不以其变动作为历史篡改。

证据清单：`.cache/state-directive-research/research_manifest_20261123_150203.json`。

- `probes.json`：`.cache/state-directive-research/probes_20261123_150203.json`。
- `followup.json`：`.cache/state-directive-research/followup_20261123_150203.json`。
- `probes.py`：`.cache/state-directive-research/probes_20261123_150203.py`。
- `followup.py`：`.cache/state-directive-research/followup_20261123_150203.py`。
- `probes-final.log`：`.cache/state-directive-research/probes-final_20261123_150203.log`。
- `followup-final.log`：`.cache/state-directive-research/followup-final_20261123_150203.log`。
