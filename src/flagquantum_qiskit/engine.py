"""标准门终端测量快路径的真实 FlagQuantum 执行边界。

本模块调用官方 Circuit.from_ir 与 Circuit.sample，返回量子位采样列；
经典位映射由 results 负责。动态控制/噪声等通用路径的 FQ 内核调用另在
fq_ops 中集中封装，因此本模块不是整个包唯一的执行入口。
这里既不回退到其他模拟器，也不重复一套完整的 FQ plan/run 编译流程。
"""

# 从已安装发行包读取版本，记录实际执行环境，而不是研究源码目录的版本。
from importlib.metadata import version

from qiskit.exceptions import QiskitError

# 输入分别是准备好的 FQ IR 与运行选项，输出保留采样和来源信息。
from .contracts import EngineSamples, PreparedCircuit, RunRequest


def execute(prepared: PreparedCircuit, request: RunRequest) -> EngineSamples:
    """以 CPU 状态向量执行一个快路径实验，返回 EngineSamples。

    输入需已完成线路、依赖版本和资源预检；本函数不接受原始 QuantumCircuit。
    每次调用创建新的 FQ Circuit 与局部随机数生成器，状态不跨实验复用。
    返回张量为 (shots, num_qubits)，列序由官方 bits 输出契约确定。
    """

    # 延迟导入真实数值依赖；失败时报告安装问题，不换用另一种计算实现。
    try:
        import torch
        import flagquantum as fq
    except ImportError as exc:
        raise QiskitError(f"FlagQuantum CPU dependencies could not be imported: {exc}") from exc

    # precision 已由 validation 限定；这里仅映射到 Torch 的复数存储类型。
    dtype = torch.complex128 if request.precision == "double" else torch.complex64
    # 独立 Generator 不修改 Torch 全局 RNG；批次的种子派生已由 backend 完成。
    generator = torch.Generator(device="cpu")
    if request.seed_simulator is None:
        generator.seed()
    else:
        generator.manual_seed(request.seed_simulator)
    # 本 API 返回经典采样，不提供自动微分图；关闭梯度记录以免保留计算历史。
    # from_ir 构造全零初态线路，内部优化不等于完整的 fq.plan/fq.run 路线。
    with torch.no_grad():
        circuit = fq.Circuit.from_ir(prepared.ir, device="cpu", dtype=dtype)
        sampled = circuit.sample(request.shots, generator=generator, format="bits")
    # 上游带一个线路批次维度，此处每次只执行一个准备好的实验，故必须为 1。
    # 先验证形状/设备/二值整数内容，避免错误上游输出悄悄形成貌似正确的 counts。
    expected = (1, request.shots, prepared.sidecar.num_qubits)
    if tuple(sampled.shape) != expected or sampled.device.type != "cpu":
        raise QiskitError(f"Unexpected FlagQuantum sample contract: {sampled.shape}, {sampled.device}")
    if sampled.dtype != torch.int64 or not bool(torch.all((sampled == 0) | (sampled == 1))):
        raise QiskitError("FlagQuantum returned non-binary samples")
    # 去掉线路批次维度；第 q 列已对应量子位 q，不在此反转列或交换门的实参。
    # 执行信息用于追溯，不能仅靠这些声明替代真实引擎调用的独立验证。
    return EngineSamples(sampled[0], {
        "engine": "flagquantum", "flagquantum_version": version("flagquantum"),
        "torch_version": torch.__version__, "qiskit_version": version("qiskit"),
        "adapter_version": "0.2.0", "method": "Circuit.sample/statevector",
        "device": str(circuit.device), "precision": str(circuit.dtype),
        "seed_simulator": request.seed_simulator,
    })
