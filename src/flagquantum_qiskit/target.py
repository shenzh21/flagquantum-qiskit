"""声明 Qiskit 转译器可保留的指令，并提供标准门身份检查。

Target 是编译能力声明，不是完整的执行校验器。具体参数、位数、控制状态、
保存子类型和资源限制仍须由 validation/program 等模块检查；不能仅凭一个
自定义指令与已知门同名就执行它。此模块不转译也不运行线路。
"""

# 固定位数指令用实例注册；初始化、矩阵和控制流等可变形式用类注册。
from qiskit.circuit import (Measure, Parameter, Reset, IfElseOp, WhileLoopOp, ForLoopOp,
                           SwitchCaseOp, BreakLoopOp, ContinueLoopOp, Instruction)
from qiskit.circuit.library import (
    CXGate, CZGate, HGate, IGate, PhaseGate, RXGate, RYGate, RZGate,
    SGate, SdgGate, SwapGate, TGate, TdgGate, UGate, XGate, YGate, ZGate, Initialize, UnitaryGate,
)
from qiskit.transpiler import Target

# 这些 Parameter 是 Target 的符号占位，表示门接受相应连续参数，
# 不是用户线路的未绑定参数，也不会在 backend.run 中隐式替用户赋值。
_theta, _phi, _lam = (Parameter(name) for name in ("theta", "phi", "lam"))
# 同一组 17 个标准门原型供 Target 声明和校验层识别使用。
# 字典键便于查找，最终身份检查还会比较具体类型，避免只按 name 接收。
GATES = {gate.name: gate for gate in (
    IGate(), HGate(), XGate(), YGate(), ZGate(), SGate(), SdgGate(),
    TGate(), TdgGate(), RXGate(_theta), RYGate(_theta), RZGate(_theta),
    PhaseGate(_theta), UGate(_theta, _phi, _lam), CXGate(), CZGate(), SwapGate(),
)}


def make_target(num_qubits: int) -> Target:
    """为后端创建一个 Target，声明 num_qubits 容量及受理的指令种类。

    num_qubits 是后端准入上限，不会在这里分配 2**num_qubits 的状态空间。
    不提供特定量子位的 properties，表示这些指令不受某个硬件耦合图限制；
    这也不代表提供了真实硬件误差率、门时长或完整 Aer 内部指令兼容性。
    """

    target = Target(description="FlagQuantum ideal CPU statevector", num_qubits=num_qubits)
    # 固定门实例携带位数和参数签名；测量/reset 也明确属于目标能力。
    for gate in (*GATES.values(), Measure(), Reset()):
        target.add_instruction(gate)
    # 类形式允许不同位数/块内容的合法实例保留到 backend.run 再做严格预检。
    for name, cls in (("initialize",Initialize),("unitary",UnitaryGate),
        ("if_else",IfElseOp),("for_loop",ForLoopOp),("while_loop",WhileLoopOp),
        ("switch_case",SwitchCaseOp),("break_loop",BreakLoopOp),("continue_loop",ContinueLoopOp)):
        target.add_instruction(cls,name=name)
    # 扩展指令按名称向 transpile 声明。这里使用通用 Instruction 类，
    # 以免导入 Target 就必须加载可选 Aer；并非接受任意同名对象的全部语义。
    # program/noise 会另行检查指令结构、参数与实际支持的子类型。
    for name in ("save_statevector","save_probabilities","save_probabilities_dict","save_expval","set_statevector","kraus","quantum_channel"):
        target.add_instruction(Instruction,name=name)
    return target


def is_standard_gate(operation: object) -> bool:
    """判断对象的名称与具体类型是否匹配标准门原型，返回布尔值。

    Qiskit 可能给标准门使用共享单例的派生类型，因此允许原型实际类型和
    base_class 两种精确类型；不使用宽泛 isinstance 接受任意自定义子类。
    本函数只检查身份，不验证参数是否已绑定、控制状态是否受支持等细节。
    """

    prototype = GATES.get(getattr(operation, "name", None))
    return prototype is not None and type(operation) in {
        type(prototype), prototype.base_class,
    }
