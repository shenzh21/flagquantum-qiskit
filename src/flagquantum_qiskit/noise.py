"""把 Aer 噪声对象转换为适配器的数值计划，并处理经典读出抽样。

QuantumError 转 Kraus 是有限宽度的局部通道表示转换，不是执行用户线路。
量子态上的通道作用由执行层调用 FlagQuantum 完成；本模块只保存算子，
以及按读出误差矩阵修改测量后经典值。没有 Aer 模拟器计算回退。

NoiseModel 的私有字典布局按照已验证的 Aer 0.18.4 使用。依赖版本由包
配置固定，升级时必须重新核对这些结构；未使用噪声时不会导入可选 Aer。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import torch
from qiskit.circuit import Instruction
from qiskit.exceptions import QiskitError


# 这是单个局部噪声通道的宽度上限，不是整条线路的量子位上限。
# 通道表示转换可能需要比状态向量更大的矩阵，因此还要另查内存预算。
_MAX_CHANNEL_QUBITS = 5


def _check_width(width: int, max_memory_bytes: int, *, superoperator: bool) -> int:
    """检查局部宽度和转换预算，返回该子系统的维度 d = 2**width。

    superoperator=True 表示随后需要 SuperOp/Choi 等通道表示，估计 d**4
    规模；False 用于已知算子或读出矩阵，估计 d**2 规模。预算是保守
    接收检查，不是对 Python/第三方所有临时分配的操作系统级限制。
    """
    if not isinstance(width, int) or not 1 <= width <= _MAX_CHANNEL_QUBITS:
        raise QiskitError(f"Noise channels support 1 to {_MAX_CHANNEL_QUBITS} qubits")
    dimension = 1 << width
    # 1 << width 等于 2**width。普通矩阵为 d×d，超算符为 d²×d²。
    # Qiskit 的表示转换使用 complex128，每元素 16 字节，即使最终选择
    # single 也先如此估计。8 和 3 为多份矩阵/特征分解临时量的保守倍数。
    needed = 8 * 16 * dimension**4 if superoperator else 3 * 16 * dimension**2
    if needed > max_memory_bytes:
        raise QiskitError(f"Local noise conversion needs an estimated {needed} bytes, above memory budget")
    return dimension


def _validated_operators(
    values: Any, width: int, *, dtype: torch.dtype, max_memory_bytes: int
) -> tuple[torch.Tensor, ...]:
    """验证一组标准 Kraus 算子，并返回 FQ 位序、目标复数精度的 CPU 张量。

    values 必须是非空列表/元组，每个算子维度为 2**width 方阵且数值有限。
    标准 Kraus 和式表达完全正映射，再检查 Σ K†K≈I 以保证迹保持；这里
    不接受两组左右算子的广义表示。调用者随后才会让 FQ 作用这些算子。
    """
    dimension = _check_width(width, max_memory_bytes, superoperator=False)
    if dtype not in (torch.complex64, torch.complex128):
        raise QiskitError("Noise conversion requires complex64 or complex128")
    if not isinstance(values, (tuple, list)) or not values:
        raise QiskitError("A Kraus channel needs a nonempty operator list")
    if len(values) * dimension**2 * 16 * 3 > max_memory_bytes:
        raise QiskitError("Kraus operators exceed the noise conversion memory budget")
    operators = []
    # 统一用双精度检查，与最终 single/double 选择分开，避免用低精度掩盖
    # 输入问题。下表把每个 width 位二进制索引反转，随后同时重排行和列。
    # 例如 width=2 时索引顺序为 [0,2,1,3]，只是局部基顺序转换。
    indices = torch.tensor(
        [int(f"{index:0{width}b}"[::-1], 2) for index in range(dimension)],
        dtype=torch.int64,
    )
    for value in values:
        try:
            # detach/clone 切断输入张量的梯度与存储共享，防止原模型后续修改
            # 影响已经准备好的数值计划；这里不修改用户提供的矩阵。
            matrix = torch.as_tensor(value, dtype=torch.complex128, device="cpu").detach().clone()
        except (TypeError, ValueError, RuntimeError) as exc:
            raise QiskitError(f"Invalid Kraus operator: {exc}") from exc
        if tuple(matrix.shape) != (dimension, dimension) or not bool(torch.isfinite(matrix).all()):
            raise QiskitError("Kraus operators must be finite square matrices of the instruction width")
        operators.append(matrix.index_select(0, indices).index_select(1, indices))
    # mH 表示共轭转置。这个矩阵乘法只检查局部通道定义，不演化线路状态。
    completeness = sum(matrix.mH @ matrix for matrix in operators)
    if not torch.allclose(completeness, torch.eye(dimension, dtype=torch.complex128), atol=1e-7, rtol=1e-7):
        raise QiskitError("Kraus channel is not trace preserving (sum K†K differs from identity)")
    # 检查通过后才转换执行精度，并保证 FQ 接收到连续存储的算子。
    return tuple(matrix.to(dtype=dtype).contiguous() for matrix in operators)


def _error_operators(error: Any, *, dtype: torch.dtype, max_memory_bytes: int) -> tuple[torch.Tensor, ...]:
    """将一个 Aer BaseQuantumError 转成经过校验的局部 Kraus 算子元组。

    只在需要这类噪声对象时导入 Aer。先限制宽度及超算符转换内存，再让
    Qiskit 做局部表示转换；它不会接收或执行用户的整条 QuantumCircuit。
    """
    from qiskit.quantum_info import Kraus
    from qiskit_aer.noise.errors.base_quantum_error import BaseQuantumError

    if not isinstance(error, BaseQuantumError):
        raise QiskitError("NoiseModel quantum entries must be Aer BaseQuantumError objects")
    width = error.num_qubits
    _check_width(width, max_memory_bytes, superoperator=True)
    try:
        # 得到局部通道矩阵的另一种数学表示，不是模拟后的量子态。
        data = Kraus(error.to_quantumchannel()).data
    except Exception as exc:
        raise QiskitError(f"Aer local-channel representation conversion failed: {exc}") from exc
    # Qiskit 可能用二元组表示广义 Kraus 的两组算子；当前执行层仅接受
    # 完全正通道的单组标准 Kraus，所以明确拒绝该形式。
    if isinstance(data, tuple):
        raise QiskitError("Generalized non-CP Kraus representations are unsupported")
    return _validated_operators(data, width, dtype=dtype, max_memory_bytes=max_memory_bytes)


def channel_operators(operation: Any, *, dtype: torch.dtype, max_memory_bytes: int) -> tuple[torch.Tensor, ...]:
    """读取线路中显式的 Kraus/QuantumChannelInstruction，返回 FQ 算子。

    裸 kraus 必须是准确的 Qiskit Instruction 类型且无经典位；Aer 通道
    则要求真实 QuantumChannelInstruction 对象及一致的宽度。不能只凭
    自定义指令碰巧叫同一个名字，就把它当作已验证的通道执行。
    """
    if type(operation) is Instruction and operation.name == "kraus":
        if operation.num_clbits:
            raise QiskitError("Kraus instructions cannot contain classical bits")
        return _validated_operators(operation.params, operation.num_qubits, dtype=dtype,
                                    max_memory_bytes=max_memory_bytes)
    if operation.name == "quantum_channel":
        try:
            from qiskit_aer.noise.errors.base_quantum_error import QuantumChannelInstruction
        except ImportError as exc:
            raise QiskitError("Aer is required to interpret its QuantumChannelInstruction objects") from exc
        if isinstance(operation, QuantumChannelInstruction):
            # 访问已验证 Aer 版本的内部误差对象，再走统一表示转换流程。
            error = operation._quantum_error
            if operation.num_clbits or operation.num_qubits != error.num_qubits:
                raise QiskitError("Quantum channel instruction has inconsistent dimensions")
            return _error_operators(error, dtype=dtype, max_memory_bytes=max_memory_bytes)
    raise QiskitError("Expected a validated Kraus instruction or Aer QuantumChannelInstruction")


def _readout_matrix(error: Any, *, max_memory_bytes: int) -> torch.Tensor:
    """复制并验证 Aer ReadoutError，返回经典条件概率矩阵。

    第 i 行表示真实测量值为 i 时，各观测值出现的概率 P(observed|true)。
    各行必须有限、非负且和为 1。它不是量子门或 Kraus 算子，不转换量子
    振幅端序；readout 方法会按模型组内位顺序组装整数索引。
    """
    from qiskit_aer.noise import ReadoutError

    if not isinstance(error, ReadoutError):
        raise QiskitError("Readout noise entries must be Aer ReadoutError objects")
    width = error.number_of_qubits
    dimension = _check_width(width, max_memory_bytes, superoperator=False)
    probabilities = torch.as_tensor(error.probabilities, dtype=torch.float64).detach().clone()
    if (tuple(probabilities.shape) != (dimension, dimension)
            or not bool(torch.isfinite(probabilities).all())
            or bool((probabilities < 0).any())
            or not torch.allclose(probabilities.sum(dim=1), torch.ones(dimension, dtype=torch.float64),
                                  atol=1e-8, rtol=1e-8)):
        raise QiskitError("Readout rows must be finite, nonnegative conditional probabilities summing to one")
    return probabilities


@dataclass
class NoisePlan:
    """与用户原噪声对象分离的数值快照，供一个批次的各实验读取。

    本类保存匹配规则和算子，不决定线路中何时施加量子噪声。执行层负责
    普通门/reset 后、measure 前的量子噪声，以及真实坍缩后的读出误差。
    后者只改经典观测，再影响后续经典反馈，不重新改变已坍缩的量子态。
    相关读出只在一次传入的连续测量组中包含完整局部误差组时应用。
    """

    # 指令匹配键 → 对全部相应位置通用的量子通道。
    # default_factory 为每个计划创建独立字典，避免实例之间共享可变默认值。
    default_quantum: dict[str, tuple[torch.Tensor, ...]] = field(default_factory=dict)
    # 指令匹配键 → 有序量子位元组 → 局部通道；同一位置的局部规则优先。
    local_quantum: dict[str, dict[tuple[int, ...], tuple[torch.Tensor, ...]]] = field(default_factory=dict)
    # 全部未被局部读出组覆盖的量子位使用的单量子位 2×2 读出矩阵。
    default_readout: torch.Tensor | None = None
    # 有序量子位元组 → 联合读出矩阵；不同局部组在准备阶段要求互不重叠。
    local_readout: dict[tuple[int, ...], torch.Tensor] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        """是否存有任何噪声规则；供后端决定能否走无噪声末端采样路径。

        这里只检查计划是否非空，不预判这些规则是否实际匹配某条线路。
        """
        return bool(self.default_quantum or self.local_quantum or self.default_readout is not None or self.local_readout)

    def quantum_for(self, name: str, label: str | None, wires: tuple[int, ...]) -> tuple[torch.Tensor, ...] | None:
        """按指令名称/标签和有序 wires 查找通道；无匹配时返回 None。

        有 label 时以它作为唯一键，不再回退到 name。执行层只对普通门
        （含矩阵门）传入标签，测量/reset/initialize 等传 None 按名称匹配。
        同一键下先找精确量子位元组的局部规则，再找默认规则，并核对宽度。
        """
        key = label if label is not None else name
        operators = self.local_quantum.get(key, {}).get(tuple(wires))
        if operators is None:
            operators = self.default_quantum.get(key)
        if operators is not None and operators[0].shape[0] != 1 << len(wires):
            raise QiskitError(f"Noise attached to {key!r} does not match its instruction width")
        return operators

    def readout(self, bits: list[int], wires: tuple[int, ...], generator: torch.Generator) -> list[int]:
        """根据真实 bits 抽样读出后的经典位列表，结果顺序与输入 wires 相同。

        bits 是已经由 FQ 测量得到的二进制值；本方法不会再次坍缩量子态。
        局部组 group[0] 打包为最低位，用局部随机生成器抽样。输入列表不被
        原地修改，输出是独立列表；没有噪声规则时保留原位值。
        """
        if len(bits) != len(wires) or any(bit not in (0, 1) for bit in bits):
            raise QiskitError("Readout input must contain one binary value per measured wire")
        # 同一量子位的重复测量属于不同读出事件。每遇到重复位便切分为
        # 新的事件组，并递归处理，避免把两次测量复用为同一次噪声抽样。
        if len(set(wires)) != len(wires):
            result = []
            start = 0
            seen = set()
            for index, wire in enumerate(wires):
                if wire in seen:
                    result.extend(self.readout(bits[start:index], wires[start:index], generator))
                    start = index
                    seen.clear()
                seen.add(wire)
            result.extend(self.readout(bits[start:], wires[start:], generator))
            return result
        result = list(bits)
        # positions 把整条线路的量子位编号映射回当前测量列表的位置。
        positions = {wire: index for index, wire in enumerate(wires)}
        covered = set()
        for group, probabilities in self.local_readout.items():
            # 不完整的相关组不能按子集套用联合矩阵，此轮跳过该局部规则。
            if not all(wire in positions for wire in group):
                continue
            # 左移 offset 等于乘 2**offset：按 group 的顺序将真实位拼成
            # 条件矩阵的行索引，抽到的列索引再拆回该组各位。
            true_value = sum(bits[positions[wire]] << offset for offset, wire in enumerate(group))
            observed = int(torch.multinomial(probabilities[true_value], 1, generator=generator).item())
            for offset, wire in enumerate(group):
                result[positions[wire]] = (observed >> offset) & 1
            covered.update(group)
        # 只有未被实际应用的局部组覆盖的位置才使用默认单量子位误差；
        # 不会在局部联合误差之后再叠加一次默认误差。
        if self.default_readout is not None:
            for index, wire in enumerate(wires):
                if wire not in covered:
                    result[index] = int(torch.multinomial(self.default_readout[bits[index]], 1,
                                                        generator=generator).item())
        return result


def prepare_noise(model: Any, *, dtype: torch.dtype, max_memory_bytes: int) -> NoisePlan:
    """把支持的 Aer NoiseModel 转为独立 NoisePlan，不修改或保留原模型。

    model=None 返回空计划，无需安装/导入 Aer。非空模型必须是实际的
    Aer NoiseModel；自定义噪声 passes 和非局部量子误差不在当前范围。
    所有量子通道在此转换为给定 dtype 的 CPU 算子，读出矩阵为 float64。
    max_memory_bytes 用于逐个局部表示的转换预检，不是所有规则总和的配额。
    """
    if model is None:
        return NoisePlan()
    try:
        from qiskit_aer.noise import NoiseModel
    except ImportError as exc:
        raise QiskitError("Aer's object library is needed for noise_model=NoiseModel(...)") from exc
    if not isinstance(model, NoiseModel):
        raise QiskitError("noise_model must be an Aer NoiseModel or None")
    if getattr(model, "_custom_noise_passes", ()) or getattr(model, "_nonlocal_quantum_errors", {}):
        raise QiskitError("Custom noise passes and nonlocal quantum noise are unsupported")
    plan = NoisePlan()
    # 这些是已验证版本的私有映射，键保留 Aer 的指令名称/标签匹配语义。
    # 先保存默认规则，再保存局部规则；实际优先级由 quantum_for 决定。
    for key, error in model._default_quantum_errors.items():
        plan.default_quantum[key] = _error_operators(error, dtype=dtype, max_memory_bytes=max_memory_bytes)
    for key, entries in model._local_quantum_errors.items():
        plan.local_quantum[key] = {}
        for wires, error in entries.items():
            # 有序 wires 不能重复，长度也必须等于该局部通道的量子位数。
            if len(wires) != error.num_qubits or len(set(wires)) != len(wires):
                raise QiskitError("Local quantum noise has inconsistent qubit mapping")
            plan.local_quantum[key][tuple(wires)] = _error_operators(error, dtype=dtype,
                                                                   max_memory_bytes=max_memory_bytes)
    if model._default_readout_error is not None:
        plan.default_readout = _readout_matrix(model._default_readout_error, max_memory_bytes=max_memory_bytes)
        # 默认规则按每位独立使用，所以只能是单量子位的 2×2 矩阵；
        # 多位相关读出须进入下面带明确量子位组的局部规则。
        if tuple(plan.default_readout.shape) != (2, 2):
            raise QiskitError("Default readout noise must act on one qubit")
    covered = set()
    for wires, error in model._local_readout_errors.items():
        if len(wires) != error.number_of_qubits or len(set(wires)) != len(wires):
            raise QiskitError("Local readout noise has inconsistent qubit mapping")
        # 两个局部组若共享量子位，应用顺序及覆盖关系将变得不明确。
        # 当前要求组之间不相交，不能默默选一个或改变误差组合方式。
        if covered.intersection(wires):
            raise QiskitError("Overlapping local readout-error groups are unsupported; use disjoint groups")
        plan.local_readout[tuple(wires)] = _readout_matrix(error, max_memory_bytes=max_memory_bytes)
        covered.update(wires)
    return plan
