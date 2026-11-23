"""分离 Qiskit 的展示/经典信息与快路径的纯量子程序。

标准门终端测量线路被规范化后严格导入 FQ；标签、测量映射、寄存器、
metadata、相位及 layout 留在 sidecar。通用路径只复用 sidecar 收集函数，
其控制流/初始化/保存指令由 program 模块显式转换，不走这里的剥离流程。
"""

# 复制可变元信息，避免结果或用户后续修改反过来影响另一方。
from copy import deepcopy

# QuantumCircuit 用于建立独立的规范化线路；异常统一采用 Qiskit API 类型。
from qiskit import QuantumCircuit
from qiskit.exceptions import QiskitError

# sidecar 与 IR 使用分离的数据契约，避免把任意用户元信息传入 FQ。
from .contracts import CircuitSidecar, PreparedCircuit


def capture_sidecar(circuit):
    """收集已校验线路的元信息，返回独立的 CircuitSidecar。

    输入的顶层相位应已绑定为数值。嵌套块用外层指令的实参映射位索引；
    测量记录为深度优先的词法顺序，包含未必执行的分支，且不展开循环次数。
    本函数只记录程序结构，不运行控制流、不修改输入线路。
    """

    writes=[]; annotations=[]

    def walk(body,qmap,cmap,path=()):
        """递归遍历一个块，把其局部位映射到提交线路的全局位索引。

        qmap/cmap 的键是当前块的位对象，值是外层最终索引；path 交替记录
        指令位置和分支编号，使相同局部 index 的嵌套注释仍能区分来源。
        结果写入外层 writes/annotations，不返回量子计算结果。
        """

        for index,item in enumerate(body.data):
            location=path+(index,)
            # 保留量子位到经典位的写入关系，不按寄存器名称猜测索引。
            if item.operation.name=="measure":
                writes.append((qmap[item.qubits[0]],cmap[item.clbits[0]]))
            # 包括测量和屏障的 label；它们也是应保留的用户注释。
            if item.operation.label is not None:
                annotations.append({"index":index,"path":location,"kind":"label","label":item.operation.label})
            if item.operation.name=="barrier":
                annotations.append({"index":index,"path":location,"kind":"barrier","qubits":[qmap[q] for q in item.qubits]})
            # 控制流块的位对象通常不同于顶层位对象，必须逐层沿实参映射。
            for branch,block in enumerate(getattr(item.operation,"blocks",())):
                annotations.append({"path":location+(branch,),"kind":"block",
                    "global_phase":deepcopy(block.global_phase),"metadata":deepcopy(block.metadata)})
                walk(block,{q:qmap[outer] for q,outer in zip(block.qubits,item.qubits)},
                     {c:cmap[outer] for c,outer in zip(block.clbits,item.clbits)},location+(branch,))

    # 从提交线路的实际顺序建立根映射，绝不根据 layout 做第二次反转。
    walk(circuit,{q:i for i,q in enumerate(circuit.qubits)},
         {c:i for i,c in enumerate(circuit.clbits)})
    # metadata/layout 深拷贝；名称、尺寸及已绑定相位转换为契约中的形式。
    return CircuitSidecar(circuit.name,circuit.num_qubits,circuit.num_clbits,
        tuple((r.name,len(r)) for r in circuit.cregs),tuple(writes),deepcopy(circuit.metadata),
        float(circuit.global_phase),deepcopy(circuit.layout),tuple(annotations))


def prepare_circuit(circuit: QuantumCircuit) -> PreparedCircuit:
    """将已通过快路径校验的线路转换为 PreparedCircuit，不修改原线路。

    前提是受支持标准门、屏障以及末端 Z 测量，且参数已绑定；不能用此函数
    处理动态测量或带执行语义的标签噪声。返回严格导入的 FQ IR、sidecar 和
    官方导入报告。依赖不可用或严格导入失败时抛出 QiskitError。
    """

    # 延迟加载官方 importer，让缺失/不兼容依赖带上清楚的诊断信息。
    try:
        from flagquantum.ecosystem.qiskit import import_qiskit
    except ImportError as exc:
        raise QiskitError(
            "FlagQuantum importer is unavailable. Install this package's pinned "
            f"dependencies (FlagQuantum 0.3.1); original error: {exc}"
        ) from exc

    # 新建仅含量子位的 body：不复制经典寄存器、metadata、layout 或全局相位。
    # 快路径只返回测量统计，全局相位不影响概率；相位仍完整记入 sidecar。
    body = QuantumCircuit(circuit.num_qubits)
    writes = []
    annotations = []
    for index, item in enumerate(circuit.data):
        op = item.operation
        # find_bit 读取提交线路的索引；控制位/目标位相对顺序保持原样。
        qubits = [circuit.find_bit(bit).index for bit in item.qubits]
        if op.label is not None:
            annotations.append({"index": index, "kind": "label", "label": op.label})
        if op.name == "measure":
            # 先保留写入顺序，等 FQ 完成全量量子位采样后由 results 映射。
            writes.append((qubits[0], circuit.find_bit(item.clbits[0]).index))
        elif op.name == "barrier":
            # 只在已确认的理想终端测量快路径移除屏障，仍保留其位置与位列表。
            annotations.append({"index": index, "kind": "barrier", "qubits": qubits})
        else:
            # 操作可变副本避免改动输入或 Qiskit 的共享单例门；标签已另存。
            copied = op.to_mutable()
            if copied.label is not None:
                copied.label = None
            body.append(copied, qubits)
    # 展示信息与经典位映射单独保存，不要求上游 importer 理解它们。
    sidecar = CircuitSidecar(
        name=circuit.name, num_qubits=circuit.num_qubits,
        memory_slots=circuit.num_clbits,
        creg_sizes=tuple((reg.name, len(reg)) for reg in circuit.cregs),
        measurement_writes=tuple(writes), metadata=deepcopy(circuit.metadata),
        global_phase=float(circuit.global_phase), layout=deepcopy(circuit.layout),
        annotations=tuple(annotations),
    )
    # 严格模式不允许 importer 静默丢弃它不认识的内容；这里没有有损兜底。
    # 此导入是表示转换，不是再次调用 Qiskit transpile 或完整 FQ 编译流水线。
    try:
        imported = import_qiskit(body, allow_lossy=False)
    except Exception as exc:
        raise QiskitError(f"Strict FlagQuantum circuit import failed: {exc}") from exc
    return PreparedCircuit(imported.ir, sidecar, imported.report.to_dict())
