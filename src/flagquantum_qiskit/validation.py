"""在转换和量子执行之前校验请求，并选择适合的执行路径。

本模块处理选项、线路批次、参数绑定、经典寄存器布局与基础资源预算。
它不会运行量子线路，也不代替 Qiskit transpile。一般路径中各条指令及
嵌套控制流的详细检查由 program.py 完成，噪声对象由 noise.py 检查。
不支持的输入要明确报错，避免“能够运行”却悄悄丢失用户语义。
"""

import math
# operator.index 只接受支持整数索引协议的对象，不像 int() 那样截断浮点数。
import operator

from qiskit import QuantumCircuit
from qiskit.circuit import Barrier, Measure
from qiskit.exceptions import QiskitError

from .contracts import RunRequest
from .target import GATES, is_standard_gate


def integer(value: object, name: str, minimum: int, maximum: int) -> int:
    """验证整数参数并返回其整数值；范围端点均包含在允许范围内。

    四个参数依次是待检查值、用于错误提示的名称、允许最小值、允许最大值。
    例如 integer(value, "num_qubits", 1, 24) 允许 1 到 24，包含 1 和 24。
    允许实现 __index__ 的整数类型，例如 NumPy 整数；
    明确拒绝 bool，因为 Python 的 bool 虽然属于 int 子类，却不是这里的
    次数或容量参数。类型或范围不符合要求时抛出 QiskitError。
    """
    try:
        if isinstance(value, bool):
            raise TypeError
        result = operator.index(value)
    except TypeError as exc:
        raise QiskitError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise QiskitError(f"{name} must be between {minimum} and {maximum}")
    return result


def make_request(options: dict, max_memory_mb: int) -> RunRequest:
    """把已合并默认值的 options 转成内部字段不可重赋值的 RunRequest。

    调用者应先把本次覆盖项与后端默认选项合并，提供必需字段。本函数检查
    字段名称、设备、精度、shots、seed、memory 与循环上限；noise_model
    暂时保留原对象，由 run 稍后转换。frozen 数据类不等于递归冻结它引用
    的对象；此处不会深复制噪声模型。容量参数以 1024**2 换算为字节。
    """
    # 拼错的参数不能被静默忽略；只接受当前真正实现的选项。
    known = {"shots", "seed_simulator", "precision", "device", "memory", "noise_model", "max_loop_iterations"}
    if unknown := set(options) - known:
        raise QiskitError(f"Unknown run option(s): {sorted(unknown)}")
    if options["device"] != "cpu":
        raise QiskitError("Only device='cpu' is supported")
    if options["precision"] not in ("single", "double"):
        raise QiskitError("precision must be 'single' or 'double'")
    if not isinstance(options["memory"], bool):
        raise QiskitError("memory must be bool")
    # shots 是每个展开后实验的重复次数，允许 1 到 1,000,000 次。
    # seed=None 表示不指定固定种子；指定时允许 0 到 2**63-1（含端点）。
    shots = integer(options["shots"], "shots", 1, 1_000_000)
    seed = options["seed_simulator"]
    if seed is not None:
        seed = integer(seed, "seed_simulator", 0, 2**63 - 1)
    # 循环上限允许 1 到 1,000,000，默认 10,000；同时供循环运行与 for
    # 预编译展开使用，防止无限执行或展开。
    loops = integer(options.get("max_loop_iterations",10000), "max_loop_iterations", 1, 1_000_000)
    # 参数名称虽写 mb，实际换算按 1 MiB = 1024**2 字节，而非十进制 MB。
    return RunRequest(shots, seed, options["precision"], max_memory_mb * 1024**2,
                      options["memory"], options.get("noise_model"), loops)


def validate_circuit(circuit: QuantumCircuit, num_qubits: int, request: RunRequest) -> None:
    """校验单条线路的基础契约；成功返回 None，失败抛出 QiskitError。

    num_qubits 是后端接收的最大宽度，不为较小线路补充量子位。调用此函数
    时外部运行参数应已绑定；控制流局部参数由后续编译层处理。这里检查
    顶层结构和保守内存估计，不保证后续不会遇到保存/循环等运行时预算错误。
    """
    if not isinstance(circuit, QuantumCircuit):
        raise QiskitError("Expected a QuantumCircuit")
    if not 1 <= circuit.num_qubits <= num_qubits:
        raise QiskitError(f"Circuit qubit count must be between 1 and {num_qubits}")
    if circuit.num_parameters:
        raise QiskitError("Unbound parameters are not supported; assign_parameters first")
    if getattr(circuit, "num_vars", 0) or getattr(circuit, "num_stretches", 0):
        raise QiskitError("Classical variables and stretches are not supported")
    if not math.isfinite(float(circuit.global_phase)):
        raise QiskitError("global_phase must be finite")
    # 当前结果封装依赖 creg_sizes：寄存器按声明顺序占据互不重叠的连续区间。
    # expected 表示下一个寄存器应从哪个经典位开始；拒绝别名与不连续排列，
    # 避免 Qiskit 格式化 counts/memory 时给位串标错位置或寄存器分组。
    expected = 0
    for register in circuit.cregs:
        indices = [circuit.find_bit(bit).index for bit in register]
        if indices != list(range(expected, expected + len(register))):
            raise QiskitError("Aliased or noncontiguous classical register layout is unsupported")
        expected += len(register)
    # 所有经典位都必须属于上述寄存器；没有任何经典位时 0 == 0，允许通过。
    if expected != circuit.num_clbits:
        raise QiskitError("Loose classical bits without a register are unsupported")
    # 使用保守估计作为接收门槛，不是操作系统强制执行的峰值内存限制。
    # complex128 每个振幅占 16 字节，complex64 占 8 字节；额外倍数覆盖
    # 多份状态及计算临时量，而不是只按一份状态向量计费。n 个量子位有
    # 2**n 个计算基振幅，所以状态空间随量子位数呈指数增长。
    complex_bytes = 16 if request.precision == "double" else 8
    estimated = 8 * complex_bytes * 2**circuit.num_qubits
    # 另估计样本张量、位提取临时量和 Python 结果行；8、32、128 都是
    # 保守估算系数，并非逐项精确测量的字节数；批次总内存仍可能更大。
    estimated += request.shots * (32 * circuit.num_qubits + circuit.num_clbits + 128)
    if estimated > request.max_memory_bytes:
        raise QiskitError(f"Estimated memory budget {estimated} bytes exceeds max_memory_mb")


def expand_inputs(run_input, parameter_binds):
    """统一单线路/非空批次，并按 Aer 风格参数绑定生成实验列表。

    parameter_binds 为 None 时只新建外层列表，不复制或修改线路对象。
    否则每条输入线路对应一个字典，其各参数的值序列必须等长且非空，
    同一索引处的值组合为一个实验；不会计算各参数的笛卡尔积。
    输出顺序是先按输入线路，再按该线路的参数值索引。
    """
    circuits = [run_input] if isinstance(run_input, QuantumCircuit) else run_input
    if not isinstance(circuits, (list, tuple)) or not circuits or not all(isinstance(c, QuantumCircuit) for c in circuits):
        raise QiskitError("Expected a QuantumCircuit or a nonempty list of circuits")
    if parameter_binds is None:
        return list(circuits)
    if not isinstance(parameter_binds, list) or len(parameter_binds) != len(circuits):
        raise QiskitError("parameter_binds must contain one dictionary per circuit")
    expanded=[]
    for circuit, binds in zip(circuits,parameter_binds):
        if not isinstance(binds, dict):
            raise QiskitError("parameter_binds entries must be dictionaries")
        # 先检查各参数值序列长度；实际是否能按整数索引和绑定给该参数，
        # 由后面的取值与 assign_parameters 检查。空字典表示一个不额外绑定的实验。
        lengths=[]
        for values in binds.values():
            try:
                lengths.append(len(values))
            except TypeError as exc:
                raise QiskitError("Parameter bind values must be lists") from exc
        if lengths and (min(lengths)<1 or len(set(lengths))!=1):
            raise QiskitError("Parameter bind lists must have equal nonzero lengths")
        for i in range(lengths[0] if lengths else 1):
            # 默认的 assign_parameters 返回副本，保留用户原线路；它只绑定
            # 参数，不调用 transpile，也不在此执行量子计算。
            try:
                expanded.append(circuit.assign_parameters({p: values[i] for p,values in binds.items()}))
            except Exception as exc:
                raise QiskitError(f"Invalid parameter_binds: {exc}") from exc
    return expanded


def is_fast(circuit, noise_active):
    """判断能否使用 FQ 整体末端采样路径，返回布尔值。

    要求无活动 NoiseModel、仅含已认可的标准门/barrier/末端测量，且至少
    有一次测量。一旦开始测量，后面不能再出现量子门。返回 False 不等于
    拒绝该线路，而是交给通用程序编译与轨迹执行路径继续检查和处理。
    """
    if noise_active:
        return False
    measured=False
    for item in circuit.data:
        op=item.operation
        # 接受已知类型，不让任意同名自定义指令伪装成 barrier/measure。
        # 这里兼容 Measure 及其实例使用的标准类型。
        if type(op) is Barrier:
            continue
        if type(op) in (Measure,type(Measure())):
            measured=True
            continue
        if measured or not is_standard_gate(op) or getattr(op,"condition",None) is not None:
            return False
        # 标准门身份还不够：开放控制等非默认控制态不走此快速导入路径。
        if getattr(op,"ctrl_state",None)!=getattr(GATES[op.name],"ctrl_state",None):
            return False
        if any(not math.isfinite(float(p)) for p in op.params):
            return False
    # 无测量的有效线路也走通用路径，可按保存指令输出或成功返回空数据。
    return measured
