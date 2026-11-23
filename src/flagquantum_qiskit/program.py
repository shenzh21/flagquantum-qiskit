"""将 Qiskit 线路编译成适配器可解释的结构，量子数值仍交给 FlagQuantum。

本模块处理指令类型、经典表达式、嵌套块和数据表示，不执行量子态演化。
普通门通过严格导入取得 FQ 指令；初始化、矩阵、保存和控制流各有显式
转换分支。编译得到的 Program 保留块相位与经典位映射，供逐 shot 执行。
"""

from dataclasses import dataclass
import math

import torch
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import (Barrier, Measure, Reset, IfElseOp, WhileLoopOp,
                           ForLoopOp, SwitchCaseOp, BreakLoopOp, ContinueLoopOp)
from qiskit.circuit.library import Initialize, StatePreparation, UnitaryGate
from qiskit.exceptions import QiskitError
from flagquantum.core.ir import Instruction
from flagquantum.ecosystem.qiskit import import_qiskit

from .fq_ops import matrix_from_qiskit
from .target import GATES, is_standard_gate

# 仅接受这些已实现的 Aer 保存指令；不能将其他 save 变体当成默认保存。
SAVES = {"save_statevector", "save_probabilities", "save_probabilities_dict", "save_expval"}


@dataclass
class Node:
    """单条解释器节点，所有 wires/bits 都已映射到最外层实验的索引。

    operation 保留原 Qiskit 对象，供标签、参数与条件读取；kind 是执行分派键。
    payload 按类别保存子 Program、FQ 指令、局部 Kraus 算符或完整初态张量。
    普通量子门统一使用 kind='gate'，但原操作名仍可用于匹配噪声模型。
    """

    kind: str
    operation: object
    wires: tuple
    bits: tuple
    payload: object = None


@dataclass
class Program:
    """一个线路块的节点序列、进入该块时应计入的相位及经典位映射。

    cmap 将该作用域内可引用的 Clbit 对象映射到外层经典内存位置；相位
    在每次实际进入块时应用，因此循环体被执行多次时也会多次计入。
    """

    nodes: list
    phase: float
    cmap: dict


def _is_class(op, cls):
    """识别精确的指令类及其无参构造所得的单例类型，不放行任意子类。"""
    if type(op) is cls: return True
    try: return type(op) is type(cls())
    except TypeError: return False


def compile_program(circuit, request, *, total_qubits=None, qmap=None, cmap=None,
                    labels=None, in_loop=False, expansion=None):
    """递归预检并编译一个块，建立执行器需要的结构和数值输入表示。

    qmap/cmap 将当前块的位连接到最外层实验，避免把局部编号误当全局编号。
    labels 在递归调用间共享，用于拒绝独立保存位置的键冲突；expansion 用
    单元素列表共享 for 展开总量，防止嵌套块各自未超限而总展开量失控。
    未选择的分支也会编译，但量子态只在后续执行器中实际演化。
    """
    # 顶层建立位索引；嵌套调用沿用已经映射到外层的索引和共享预检状态。
    n = total_qubits or circuit.num_qubits
    qmap = qmap or {q: i for i, q in enumerate(circuit.qubits)}
    cmap = cmap or {c: i for i, c in enumerate(circuit.clbits)}
    labels = set() if labels is None else labels
    expansion = [0] if expansion is None else expansion
    nodes = []
    phase = float(circuit.global_phase)
    if not math.isfinite(phase):
        raise QiskitError("Global phase must be finite")
    dtype = torch.complex128 if request.precision == "double" else torch.complex64

    def block(body, item, *, loop=in_loop):
        """按控制流指令的位实参，把子块局部位映射到外层后递归编译。

        经典映射同时保留外层键，使块中的捕获引用仍可定位；子块自身的
        Clbit 键再补入映射。循环上下文决定 break/continue 是否允许出现。
        """
        return compile_program(body, request, total_qubits=n,
            qmap={q: qmap[outer] for q, outer in zip(body.qubits, item.qubits)},
            cmap={**cmap, **{c: cmap[outer] for c, outer in zip(body.clbits, item.clbits)}},
            labels=labels, in_loop=loop, expansion=expansion)

    for index, item in enumerate(circuit.data):
        # op 与 payload 分开保存：执行载荷可能已转换，但标签/条件仍来自 op。
        op = item.operation
        wires = tuple(qmap[q] for q in item.qubits)
        bits = tuple(cmap[c] for c in item.clbits)
        node = Node(op.name, op, wires, bits)
        if _is_class(op, Barrier):
            # 当前模型不模拟时长；屏障不产生量子演化，原始注解由 sidecar 保留。
            continue
        if _is_class(op, Measure) or _is_class(op, Reset):
            # 这两类节点直接使用映射后的位；实际坍缩与 reset 留给 FQ。
            nodes.append(node)
            continue
        if isinstance(op, (IfElseOp, WhileLoopOp)):
            # 先验证条件引用，再编译所有分支；while 的体处于循环上下文。
            validate_condition(op.condition, cmap)
            node.payload = [block(body, item, loop=in_loop or isinstance(op, WhileLoopOp))
                            for body in op.blocks]
        elif isinstance(op, ForLoopOp):
            values, parameter, body = op.params
            if len(values) > request.max_loop_iterations:
                raise QiskitError("For loop exceeds max_loop_iterations")
            # 同一词法循环体的重复展开共用保存标签，不算多个独立保存位置。
            before = set(labels)
            node.payload = []
            for value in values:
                # 预算是整棵编译树共享的总展开次数，不只是当前 for 的长度。
                expansion[0]+=1
                if expansion[0]>request.max_loop_iterations:
                    raise QiskitError("Compiled loop expansion exceeds max_loop_iterations")
                labels.clear(); labels.update(before)
                # 只绑定此 for 的局部参数；strict=False 允许该参数未被体引用。
                bound = body if parameter is None else body.assign_parameters({parameter: value}, strict=False)
                node.payload.append(block(bound, item, loop=True))
            if len(values)==0:
                bound=body if parameter is None else body.assign_parameters({parameter:0},strict=False)
                block(bound,item,loop=True)  # 即使零次循环也预检不可达的循环体。
        elif isinstance(op, SwitchCaseOp):
            # 保留 case 标签与编译块的配对，默认分支由执行器在匹配失败后选择。
            validate_value(op.target, cmap)
            node.payload = [(cases, block(body, item)) for cases, body in op.cases_specifier()]
        elif isinstance(op, (BreakLoopOp, ContinueLoopOp)):
            # 编译只检查词法位置；真正的跳出/继续在执行时通过信号传播。
            if not in_loop:
                raise QiskitError("break/continue must appear in a loop")
        elif op.name in SAVES and type(op).__module__.startswith("qiskit_aer."):
            # Aer 标签直接成为 Result.data 的键，必须避开计数/内存保留键。
            label = op.label
            if label in ("counts","memory"):
                raise QiskitError(f"Save label conflicts with a reserved result key: {label}")
            if label in labels:
                raise QiskitError(f"Duplicate save label: {label}")
            labels.add(label)
            subtype = getattr(op, "_subtype", None)
            # statevector 没有平均子类型；其余保存支持平均、累加或逐次列表。
            # c_ 前缀表示按保存时的经典值分组，不能丢掉前缀按普通保存处理。
            valid = {"single", "list", "c_single", "c_list"} if op.name == "save_statevector" else {
                "average", "accum", "list", "c_average", "c_accum", "c_list"}
            if subtype not in valid:
                raise QiskitError(f"Unsupported save subtype: {subtype}")
            if op.name == "save_statevector" and wires != tuple(range(n)):
                raise QiskitError("save_statevector requires all qubits in circuit order")
            # 此处是单标签的保守入场估计；动态访问次数和 conditional 新分组
            # 还要由执行期 Saves 累计计费，不能仅依靠这里的 shots 估计。
            retained = request.shots if subtype.endswith("list") else 1
            size = (16 if op.name == "save_statevector" else 8) * 2**len(wires)
            if size * retained > request.max_memory_bytes:
                raise QiskitError("Saved output exceeds memory budget")
        elif op.name == "set_statevector" and type(op).__module__.startswith("qiskit_aer."):
            # 完整替态要求全体量子位按线路顺序传入，禁止对子系统直接替振幅。
            if wires != tuple(range(n)):
                raise QiskitError("set_statevector requires all qubits in circuit order")
            vector=torch.as_tensor(op.params[0],dtype=dtype)
            tolerance=1e-6 if dtype==torch.complex64 else 1e-10
            if vector.ndim!=1 or vector.numel()!=2**n or not bool(torch.isfinite(vector).all()) or abs(float(vector.abs().square().sum())-1)>tolerance:
                raise QiskitError("set_statevector requires a finite normalized full state vector")
            # 仅做输入的 LSB→MSB 索引转换及复制，不在适配器中演化量子态。
            node.payload=vector.reshape([2]*n).permute(tuple(reversed(range(n)))).reshape(1,-1).clone().to(request.device)
        elif _is_class(op, Initialize):
            # 从 Initialize 的定义取 StatePreparation，保留字符串、整数与向量
            # 三种输入已被 Qiskit 解析后的语义；不能把 params 统一当向量重建。
            body = QuantumCircuit(len(wires))
            preparation = next(item.operation for item in op.definition.data
                               if isinstance(item.operation, StatePreparation))
            body.append(preparation, range(len(wires)))
            # 这里只合成准备态的门序列，reset/全幅替态由执行器按原 qargs 处理。
            # 准备线路使用局部位，编译时再映射到 initialize 在外层的目标位。
            lowered = transpile(body, basis_gates=list(GATES), optimization_level=0)
            node.payload = compile_program(lowered, request, total_qubits=n,
                qmap={q: wires[i] for i, q in enumerate(lowered.qubits)}, cmap=cmap,
                labels=labels, in_loop=in_loop, expansion=expansion)
        elif _is_class(op, UnitaryGate):
            # 在矩阵转换前估计局部存储，并检查幺正性；矩阵乘态仍由 FQ 执行。
            if 16 * 4**len(wires) * 4 > request.max_memory_bytes:
                raise QiskitError("Unitary matrix exceeds memory budget")
            matrix = matrix_from_qiskit(op.to_matrix(), len(wires), dtype, request.device)
            identity = torch.eye(matrix.shape[0], dtype=dtype, device=request.device)
            if not bool(torch.allclose(matrix.conj().T @ matrix, identity, atol=1e-6 if dtype==torch.complex64 else 1e-10, rtol=0)):
                raise QiskitError("Unitary matrix is not unitary")
            node.kind = "gate"; node.payload = Instruction("unitary", wires, matrix=matrix)
        elif op.name in ("kraus", "quantum_channel"):
            # noise 模块负责验证指令来源、维度和通道表示，payload 是局部算符。
            from .noise import channel_operators
            node.kind = "channel"
            node.payload = tuple(value.to(request.device) for value in channel_operators(
                op, dtype=dtype, max_memory_bytes=request.max_memory_bytes))
        elif is_standard_gate(op):
            # 类型必须属于已支持门集，开放控制态需用户先转译为受支持门。
            if getattr(op, "ctrl_state", None) != getattr(GATES[op.name], "ctrl_state", None):
                raise QiskitError("Unsupported open control state; transpile first")
            for value in op.params:
                if not math.isfinite(float(value)):
                    raise QiskitError("Gate parameters must be finite")
            body = QuantumCircuit(n)
            # 标签只从导入副本移除，原 op 仍保留标签以供后续门噪声匹配。
            copied = op.to_mutable(); copied.label = None
            body.append(copied, wires)
            node.kind = "gate"
            node.payload = import_qiskit(body, allow_lossy=False).ir.instructions[0]
        else:
            # 不凭名字猜测未知自定义指令，也不使用有损导入跳过其语义。
            raise QiskitError(f"Unsupported instruction {index}: {op.name}")
        if getattr(op, "condition", None) is not None:
            validate_condition(op.condition, cmap)
        nodes.append(node)
    return Program(nodes, phase, cmap)


def validate_value(value, cmap):
    """递归检查经典值的类型、结构与位引用是否属于支持范围。

    仅接纳 Bool/Uint 表达式，拒绝独立经典变量，并限制一元算符种类。
    二元表达式在此检查左右子树；具体二元算符是否可执行由 value_of 的
    分派表判断，因此本函数不意味着所有未知二元运算都已提前拒绝。
    """
    from qiskit.circuit import Clbit, ClassicalRegister
    from qiskit.circuit.classical import expr
    if isinstance(value,expr.Expr) and type(value.type).__name__ not in ("Bool","Uint"):
        raise QiskitError("Classical expressions support Bool and Uint only")
    if isinstance(value,expr.Unary) and value.op.name not in ("LOGIC_NOT","BIT_NOT"):
        raise QiskitError(f"Unsupported classical unary operator: {value.op.name}")
    if isinstance(value, Clbit):
        if value not in cmap: raise QiskitError("Unknown classical bit")
    elif isinstance(value, ClassicalRegister):
        for bit in value: validate_value(bit, cmap)
    elif isinstance(value, expr.Var):
        # 寄存器/位引用可以求值，独立 Var 需要额外存储模型，当前未实现。
        if value.standalone: raise QiskitError("Standalone classical variables are unsupported")
        validate_value(value.var, cmap)
    elif isinstance(value, expr.Value):
        # 常量没有需要解析到 cmap 的位引用；表达式类型已在入口检查。
        return
    elif isinstance(value, (expr.Unary, expr.Cast)):
        validate_value(value.operand, cmap)
    elif isinstance(value, expr.Binary):
        validate_value(value.left, cmap); validate_value(value.right, cmap)
    elif isinstance(value, expr.Index):
        validate_value(value.target, cmap); validate_value(value.index, cmap)
    else:
        raise QiskitError(f"Unsupported classical expression: {type(value).__name__}")


def validate_condition(condition, cmap):
    """检查旧式 (位或寄存器, 值) 条件的左项，或新式表达式条件的结构。"""
    validate_value(condition[0] if isinstance(condition, tuple) else condition, cmap)


def value_of(value, classical, cmap):
    """在当前 shot 的经典内存上解释 Bool/Uint 值，不读取量子态。

    寄存器第零位是最低有效位；Uint 的转换、一元位反转和二元结果按
    声明位宽截断。这里返回整数或布尔值，条件是否成立由调用方判定。
    """
    from qiskit.circuit import Clbit, ClassicalRegister
    from qiskit.circuit.classical import expr
    if isinstance(value, Clbit): return classical[cmap[value]]
    if isinstance(value, ClassicalRegister):
        # cmap 负责对象身份到外层槽位的映射，寄存器内部顺序负责整数权重。
        return sum(classical[cmap[b]] << i for i, b in enumerate(value))
    if isinstance(value, expr.Var): return value_of(value.var, classical, cmap)
    if isinstance(value, expr.Value): return value.value
    if isinstance(value, expr.Index):
        # 表达式索引采用最低位为零的约定，得到目标整数的一个二进制位。
        return (value_of(value.target, classical, cmap) >> value_of(value.index, classical, cmap)) & 1
    if isinstance(value, expr.Cast):
        # Uint 缩窄必须显式掩码；Python 整数自身没有固定宽度溢出语义。
        result = value_of(value.operand, classical, cmap)
        return bool(result) if type(value.type).__name__ == "Bool" else int(result) & ((1 << value.type.width)-1)
    if isinstance(value, expr.Unary):
        operand = value_of(value.operand, classical, cmap)
        if value.op.name == "LOGIC_NOT": return not operand
        if value.op.name == "BIT_NOT": return ~operand & ((1 << getattr(value.type, "width", 1)) - 1)
    if isinstance(value, expr.Binary):
        # DIV 对当前仅支持的整数表达式使用整除；不提供 Float 运算语义。
        # 两侧操作数先递归求值，再调用对应函数；逻辑运算没有惰性求值。
        import operator
        functions = {"BIT_AND":operator.and_, "BIT_OR":operator.or_, "BIT_XOR":operator.xor,
            "LOGIC_AND":lambda a,b:bool(a and b), "LOGIC_OR":lambda a,b:bool(a or b),
            "EQUAL":operator.eq, "NOT_EQUAL":operator.ne, "LESS":operator.lt,
            "LESS_EQUAL":operator.le, "GREATER":operator.gt, "GREATER_EQUAL":operator.ge,
            "SHIFT_LEFT":operator.lshift, "SHIFT_RIGHT":operator.rshift,
            "ADD":operator.add, "SUB":operator.sub, "MUL":operator.mul, "DIV":operator.floordiv}
        if value.op.name in functions:
            result = functions[value.op.name](value_of(value.left,classical,cmap),value_of(value.right,classical,cmap))
            return result & ((1 << value.type.width)-1) if hasattr(value.type,"width") else result
    # 类型结构可能已通过编译检查，但未列出的具体运算仍必须明确报错。
    raise QiskitError("Unsupported classical expression operation")


def condition_matches(condition, classical, cmap):
    """将旧式相等比较条件或新式表达式条件转换为执行分支所需的真值。"""
    if isinstance(condition, tuple):
        return value_of(condition[0],classical,cmap) == condition[1]
    return bool(value_of(condition,classical,cmap))
