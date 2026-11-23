"""模块之间传递的内部数据契约。

这些对象把运行选项、Qiskit 展示信息、FQ 中间表示和采样结果分开，
避免量子引擎承担经典寄存器排版等职责。采样列始终对应提交线路的量子位。
``frozen=True`` 禁止重新赋值字段，但不会递归冻结字段内的字典或张量；
需要隔离调用者可变对象时，转换层与 Job 会显式制作防御性副本。
"""

# dataclass 自动生成初始化等方法；Any 表示此处不绑定上游 IR/张量具体类型。
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunRequest:
    """一份已校验的实验运行请求，由校验层构造，供两条执行路径读取。

    不可变字段便于 backend 为批次中每个实验派生 seed，且不改后端默认选项。
    noise_model 保留输入对象；可执行噪声表示在后续转换阶段单独准备。
    """

    # 每个实验的采样次数；不是整个批次平分的总次数。
    shots: int
    # None 表示使用局部生成器自行初始化，否则使用显式种子。
    seed_simulator: int | None
    # 校验后为 double 或 single，对应复数张量的两种精度。
    precision: str
    # 字节单位的资源预算，供预检和运行保护使用，不是操作系统内存硬上限。
    max_memory_bytes: int
    # 是否在 counts 之外返回逐 shot 的经典位记录。
    memory: bool = False
    noise_model: Any = None
    # 通用程序路径的循环/展开保护参数。
    max_loop_iterations: int = 10000


@dataclass(frozen=True)
class CircuitSidecar:
    """随量子程序保留的 Qiskit 信息，不直接交给 FQ 解释。

    索引均以用户提交的线路为准，不根据 layout 再次重排。
    快路径的 measurement_writes 是实际终端测量写入顺序；通用控制流中
    capture_sidecar 收集的是词法遍历记录，不能当作某个 shot 的动态轨迹。
    """

    # 原线路名称、量子位总数、经典位槽总数（包括未写入的经典位）。
    name: str
    num_qubits: int
    memory_slots: int
    # 按线路寄存器顺序保存 (寄存器名, 位数)，供 Qiskit 格式化 counts。
    creg_sizes: tuple[tuple[str, int], ...]
    # (量子位索引, 经典位索引)；允许同一个经典位出现多次，后写覆盖前写。
    measurement_writes: tuple[tuple[int, int], ...]
    # 用户元数据可能含非 JSON 对象；不可不加区分地传进 FQ importer。
    metadata: dict[str, Any]
    # 顶层全局相位。快路径 counts 不依赖它，保存状态的路径另负责相位语义。
    global_phase: float
    # 保留结构化布局对象作为来源信息，不是一次额外的位序转换指令。
    layout: Any
    # 标签、屏障与嵌套块的词法位置/元信息。
    annotations: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PreparedCircuit:
    """标准门快路径的准备结果：严格导入得到的 IR、sidecar 和转换报告。

    这里只保存程序表示，不包含已经演化的状态或采样结果。
    """

    ir: Any
    sidecar: CircuitSidecar
    conversion_report: dict[str, Any]


@dataclass(frozen=True)
class EngineSamples:
    """快路径的真实 FQ 输出及其执行信息，供结果层映射经典位。

    bits 是形状为 (shots, num_qubits) 的 CPU 二值整数张量；第 q 列代表
    提交线路的量子位 q，不是待反转的 Qiskit 格式化字符串。
    execution_info 记录版本、设备、精度和种子等信息，本身不能替代执行验证。
    """

    bits: Any
    execution_info: dict[str, Any]
