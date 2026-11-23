"""通用执行路径与 FlagQuantum 0.3.1 数值内核之间的集中连接层。

trajectory.py 负责经典调度，本模块把量子门、测量、重置和噪声交给真实
FlagQuantum。涉及私有 API 的调用集中在这里，便于升级依赖时逐项复核。
另一些函数只读取状态或转换位序；它们不另外实现一套量子态演化器。

这里处理的是单个实验中的一条轨迹，FQ 状态通常形如 (1, 2**n)。
FQ 的量子位 0 对应张量第一个轴；Qiskit 振幅索引则把位 0 视为最低位。
因此输出向量与输入局部矩阵要转换索引顺序，但不改变线路的量子位身份。
"""

import torch
import flagquantum as fq
from importlib.metadata import version

# 私有函数的行为不属于稳定的跨版本接口，导入本模块时便核对已验证版本。
# 失败时直接停止，不能偷偷改用另一个模拟器或未经验证的 FQ 版本。
if version("flagquantum") != "0.3.1":
    raise ImportError("This adapter's private numerical boundary requires FlagQuantum 0.3.1")
from flagquantum.core.ir import Instruction
from flagquantum.runtime.dynamic.execution import (
    _apply_instruction, _measure_wire, _reset_instruction,
)
from flagquantum.simulation.statevector.noisy import apply_kraus_batched


def zero(n, dtype, device="cpu"):
    """由 FQ 在指定 device 上创建 n 位全零初态，dtype 决定复数精度。

    初态由 FQ 创建，再复制为独立张量，避免不同 shot 共用可修改状态。
    """
    return fq.Circuit(n, dtype=dtype, device=device).initial_state().clone()


def gate(state, instruction, n):
    """在 n 位 FQ 状态上执行一条已转换的 FQ Instruction，返回更新后的状态。

    指令与量子位映射由上游准备；这里直接委托 FQ，不重新分解或转译。
    """
    return _apply_instruction(state, instruction, n_wires=n)


def measure(state, wire, n, generator):
    """测量指定 wire，返回 (归一化的坍缩后状态, 观测到的 0 或 1)。

    FQ 使用调用方的局部随机生成器抽样；读出误差由外层随后处理。
    """
    return _measure_wire(state, wire, n, generator=generator)


def reset(state, wire, n, generator):
    """由 FQ 将指定量子位重置到零，返回重置后的整个系统状态。

    FQ 内部先测量，再视结果施加 X。reset 的测量结果不自动写入用户的
    经典寄存器，所以这里只取返回元组的状态部分；动态标记随指令传入。
    """
    return _reset_instruction(state, Instruction("reset", (wire,), metadata={"is_dynamic": True}), n, generator)[0]


def channel(state, operators, wires, n, generator):
    """让 FQ 在 wires 上抽取并归一化一个 Kraus 分支，返回轨迹纯态。

    operators 已由 noise.py 检查并转换到 FQ 局部基顺序。临时增加批次和
    轨迹轴以符合 FQ 批处理函数形状，计算后恢复 (1, 2**n)。这不是密度
    矩阵演化；多个 shot 的统计共同表达噪声通道的效果。
    """
    return apply_kraus_batched(state.reshape(1, 1, -1), operators, wires, n,
                               [generator]).reshape(1, -1)


def vector_to_qiskit(state, n):
    """将 FQ 状态转为 Qiskit 振幅索引顺序的一维张量，不改变物理状态。

    将长度 2**n 拆成 n 个二值轴，反转轴顺序后再展平；全局相位保留。
    本函数不负责 detach 或复制，保存层需要时会另行取得独立数据。
    """
    return state.reshape([2] * n).permute(tuple(reversed(range(n)))).reshape(-1)


def matrix_from_qiskit(matrix, width, dtype, device="cpu"):
    """将 width 位局部门矩阵从 Qiskit 基顺序转换为 FQ 基顺序。

    前 width 个二值轴代表矩阵行，后 width 个代表列，两个轴组分别反转。
    这相当于同时重排输入与输出基索引，不是矩阵转置或交换控制/目标。
    本函数只做表示转换，合法性由上游指令构造与程序编译层检查。
    """
    value = torch.as_tensor(matrix, dtype=dtype, device=device)
    axes = tuple(reversed(range(width))) + tuple(reversed(range(width, 2 * width)))
    return value.reshape([2] * (2 * width)).permute(axes).reshape(2**width, 2**width)


def probabilities(state, wires, n):
    """从 n 位状态读取 wires 子集的边缘概率，返回长度 2**len(wires) 的向量。

    这是状态读取操作，不进行抽样或坍缩。输出索引最低位对应 wires[0]，
    与 Qiskit 保存指令的 qargs 顺序一致；其余量子位的概率需要求和消去。
    """
    # 把被读取的轴移到前面，并按 Qiskit 从高位到低位的排列顺序展开。
    ordered = tuple(reversed(wires))
    rest = tuple(i for i in range(n) if i not in wires)
    # 振幅模平方得到联合概率；每行固定子集取值，对其余位组合求和。
    return state.abs().square().reshape([2] * n).permute(ordered + rest).reshape(
        2**len(wires), -1).sum(dim=1)


def expectation(state, terms, wires, n):
    """调用 FQ 计算当前状态上的实系数 Pauli 组合期望值，返回 Python 浮点数。

    terms 来自已校验的保存指令，每项包含 Pauli 标签及系数数据；此处
    使用 coefficients[0] 的线性系数，未实现方差保存。wires 将局部
    Pauli 位置映射到整条已提交线路的量子位编号。
    """
    # 用现有状态构造 FQ 的期望值读取对象，不重新执行输入 Qiskit 线路。
    circuit = fq.Circuit(n, inputs=state, dtype=state.dtype, device=state.device)
    value = 0.0
    for pauli, coefficients in terms:
        # Qiskit 标签最右字符对应局部位 0，因此先反向读取标签。
        # I 不需传入操作位置；X/Y/Z 的位置集合交给 FQ expectation_ps。
        selected = {axis: tuple(wires[i] for i, char in enumerate(reversed(pauli))
                                if char == axis) for axis in "XYZ"}
        value += float(coefficients[0]) * float(circuit.expectation_ps(
            x=selected["X"], y=selected["Y"], z=selected["Z"]).item())
    return value
