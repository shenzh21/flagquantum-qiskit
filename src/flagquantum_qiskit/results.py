"""把快路径的量子位采样列映射成 Qiskit 经典结果。

本模块只处理标准门终端测量快路径；通用路径在 trajectory 中随执行更新
经典位和保存数据。这里不重新演化状态、不重采样，也不按 layout 再排一次位。
"""

# Counter 按经典位最终整数值累计 shots，生成直方图。
from collections import Counter

# 使用官方结果容器，交由其 get_counts/get_memory 等接口格式化数据。
from qiskit.result import Result

from .contracts import EngineSamples, PreparedCircuit, RunRequest


def make_result(prepared: PreparedCircuit, samples: EngineSamples, request: RunRequest,
                *, backend_name: str, backend_version: str, job_id: str) -> Result:
    """将一个实验的采样与 sidecar 封装成含单条实验记录的 Result。

    samples.bits 已经由 engine 验证为 (shots, num_qubits) 的二值张量。
    measurement_writes 应为快路径末端测量的真实顺序；按顺序写经典位，
    因此重复写入同一个经典位时后者覆盖前者。backend 再聚合各实验 Result。
    """

    sidecar = prepared.sidecar
    counts = Counter()
    memory=[]
    # tolist 把张量转成 Python 行列表，便于逐位映射；会产生额外内存副本，
    # 所以预检预算只能作为估算，不能理解为整个 Python 进程的精确峰值上限。
    for row in samples.bits.tolist():
        # 每个 shot 的经典位从全零开始：没有测量写入的位保持 0。
        classical = 0
        for qubit, clbit in sidecar.measurement_writes:
            # Qiskit 的经典位 0 是最低有效位：先清掉目标位，再写入量子采样值。
            # 使用明确的 qubit->clbit 关系，不能直接把所有量子位拼成结果字符串。
            classical = (classical & ~(1 << clbit)) | (row[qubit] << clbit)
        # Result 的底层 counts/memory 使用十六进制整数表示；寄存器空格及
        # 左侧补零由 header 提供的结构和 Qiskit 结果接口负责。
        counts[hex(classical)] += 1
        if request.memory: memory.append(hex(classical))
    # 顶层描述作业，results 中每一项描述一个实验。本函数只有一个实验项。
    # header.metadata 是用户线路元数据；实验 metadata 中的专用命名空间
    # 则存放引擎来源与转换信息，两者用途不同，不相互覆盖。
    return Result.from_dict({
        "backend_name": backend_name, "backend_version": backend_version,
        "job_id": job_id, "success": True,
        "results": [{
            "shots": request.shots, "success": True,
            "header": {"name": sidecar.name, "memory_slots": sidecar.memory_slots,
                       "creg_sizes": [list(item) for item in sidecar.creg_sizes],
                       "metadata": sidecar.metadata},
            "data": {"counts": dict(counts), **({"memory":memory} if request.memory else {})},
            "metadata": {"flagquantum_qiskit": {
                **samples.execution_info, "global_phase": sidecar.global_phase,
                "measurement_writes": [list(pair) for pair in sidecar.measurement_writes],
                # layout 在此仅作可读摘要；完整对象由 Job.circuit_sidecar 暴露。
                "layout": repr(sidecar.layout), "annotations": list(sidecar.annotations),
                "conversion_report": prepared.conversion_report,
            }},
        }],
    })
