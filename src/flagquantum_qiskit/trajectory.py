"""解释 Qiskit 经典流程并聚合结果，量子操作统一调用 FlagQuantum 数值入口。

每个 shot 独立创建量子态和经典内存，分支与循环按实际测量结果执行。
适配层负责作用域、随机生成器、噪声调用时机及保存聚合；门、测量坍缩、
reset 和 Kraus 通道的量子演化由 fq_ops 转交真实 FQ，不另写模拟器回退。
"""

from collections import Counter, defaultdict
import cmath
from importlib.metadata import version

import numpy as np
import torch
from qiskit.circuit.controlflow import CASE_DEFAULT
from qiskit.exceptions import QiskitError

from . import fq_ops
from .program import condition_matches, value_of


class LoopSignal(Exception):
    """将 break/continue 从嵌套分支传递给最近的循环执行层的内部信号。"""

    def __init__(self, kind):
        """保留信号种类，供循环决定终止循环还是开始下一次迭代。"""
        self.kind=kind


class Saves:
    """一个实验跨所有 shot 的保存结果聚合器，同时累计保留数据预算。

    values 按标签、conditional 经典键两层索引保存 [值或列表, 访问次数]。
    非 conditional 标签只使用 None 键。single 覆盖最近值，average/accum
    在线求和，只有 list 逐次保留，以免默认保存退化成 shots 倍状态存储。
    """

    def __init__(self, max_memory_bytes):
        """初始化标签/子类型登记表与本实验的累计保存预算。"""
        self.values=defaultdict(dict); self.specs={}
        self.max_memory_bytes=max_memory_bytes; self.retained_bytes=0

    def add(self, node, state, classical, n):
        """在一次实际保存访问处读取状态信息，并更新对应标签与经典分组。

        conditional 的键来自此刻的经典内存，不是 shot 结束后的经典值。
        访问次数按实际到达保存节点计算：循环中可多次增加，未走分支不增加。
        """
        op=node.operation
        # 状态向量转换回 Qiskit 位序并复制，避免后续状态变化影响已保存值。
        # 概率/期望由 fq_ops 读取或调用 FQ 计算，不能用 Qiskit 重新演化线路。
        if op.name=="save_statevector": value=fq_ops.vector_to_qiskit(state,n).detach().cpu().numpy().copy()
        elif op.name.startswith("save_probabilities"):
            value=fq_ops.probabilities(state,node.wires,n).detach().cpu().numpy().copy()
        else: value=fq_ops.expectation(state,op.params,node.wires,n)
        key=hex(sum(bit<<i for i,bit in enumerate(classical))) if op._subtype.startswith("c_") else None
        kind=op._subtype.removeprefix("c_")
        groups=self.values[op.label]
        size=int(getattr(value,"nbytes",8))+128  # 为数值之外的容器开销留保守余量。
        # 新分组首次保存要计费，list 每次追加也计费；替换 single 或在线求和
        # 不按访问次数重复计费。这是保存预算估计，不是进程峰值内存硬限制。
        increment=size if key not in groups or kind=="list" else 0
        if self.retained_bytes+increment>self.max_memory_bytes:
            raise QiskitError("Saved output exceeds cumulative memory budget")
        self.retained_bytes+=increment
        if key not in groups: groups[key]=[[] if kind=="list" else value,0]
        bucket=groups[key]
        if kind=="list": bucket[0].append(value)
        elif kind=="single": bucket[0]=value
        elif bucket[1]: bucket[0]+=value
        # 首次 average/accum 已用 value 初始化，不能在第一次访问时再加一次。
        bucket[1]+=1
        self.specs[op.label]=(op.name,op._subtype)

    def result(self):
        """按保存子类型生成 Result.data 所需的最终容器，不执行任何量子计算。"""
        outputs={}
        for label,groups in self.values.items():
            name,subtype=self.specs[label]; kind=subtype.removeprefix("c_")
            def aggregate(bucket):
                """完成单个分组的归一化与容器包装，保留逐次列表的嵌套层次。"""
                value,count=bucket
                # average 除以该分组的实际保存访问次数，不是请求的 shots。
                # accum 保留总和；single/list 无需再归一化。
                if kind=="average": value=value/count
                if name=="save_statevector":
                    # Statevector 仅包装 FQ 结果；list 中每一项也必须分别包装。
                    from qiskit.quantum_info import Statevector
                    return [Statevector(v) for v in value] if kind=="list" else Statevector(value)
                if name=="save_probabilities_dict":
                    # Aer 风格稀疏概率字典使用整数基态索引，只省略恰好为零项。
                    convert=lambda arr:{i:float(p) for i,p in enumerate(arr) if p!=0}
                    return [convert(v) for v in value] if kind=="list" else convert(value)
                return value
            # conditional 保留 hex 键到独立聚合结果的映射，普通标签去掉 None 层。
            outputs[label]={key:aggregate(values) for key,values in groups.items()} if subtype.startswith("c_") else aggregate(groups[None])
        return outputs


class Execution:
    """一个编译后实验的逐 shot 执行上下文，负责经典调度与结果收集。

    程序、sidecar、选项和噪声计划在实验内共享；量子态、经典值和循环计数
    在每个 shot 重置。局部随机生成器在同一实验中持续推进，不修改全局 RNG。
    """

    def __init__(self, program, sidecar, request, noise):
        """建立实验上下文、精度、局部随机源和跨 shot 的保存聚合器。"""
        self.program=program; self.sidecar=sidecar; self.request=request; self.noise=noise
        self.n=sidecar.num_qubits
        self.dtype=torch.complex128 if request.precision=="double" else torch.complex64
        self.generator=torch.Generator(device=request.device)
        self.generator.seed() if request.seed_simulator is None else self.generator.manual_seed(request.seed_simulator)
        self.saves=Saves(request.max_memory_bytes)
        # 初始化的内部准备态门不应逐门套用用户 NoiseModel；计数器支持嵌套屏蔽。
        self.suppress_noise=0

    def apply_noise(self, node):
        """查找并施加该节点的量子噪声，具体前后顺序由 run_block 决定。

        普通门与矩阵门使用原操作 label（存在时）匹配；测量、reset、初始化
        按操作名匹配。局部优先于默认的选择逻辑在 NoisePlan 中完成。
        """
        if self.suppress_noise: return
        label=node.operation.label if node.kind=="gate" else None
        operators=self.noise.quantum_for(node.operation.name,label,node.wires)
        if operators is not None:
            self.state=fq_ops.channel(self.state,operators,node.wires,self.n,self.generator)

    def loop_tick(self):
        """累计当前 shot 中所有嵌套循环的迭代次数，并在超预算时中止。"""
        self.iterations+=1
        if self.iterations>self.request.max_loop_iterations:
            raise QiskitError("Execution exceeded max_loop_iterations")

    def run_block(self, program):
        """按节点顺序执行一个作用域块，将量子更新委托给 FQ。

        进入块就应用块相位；嵌套调用可能抛出 LoopSignal，让最近的 for/while
        捕获。经典条件通过此块的 cmap 解释，量子与经典索引已在编译时映射。
        """
        # 每次进入都计相位，包括循环体的重复进入；不是仅在顶层应用一次。
        self.state=self.state*cmath.exp(1j*program.phase)
        i=0
        while i<len(program.nodes):
            node=program.nodes[i]; op=node.operation; kind=node.kind
            if kind=="measure":
                # 连续测量节点组成一个读出组：每次先施加测量量子噪声，再由
                # FQ 坍缩得到真实位；联合读出误差在整组真实位得到后统一采样。
                group=[]
                while i<len(program.nodes) and program.nodes[i].kind=="measure":
                    current=program.nodes[i]
                    self.apply_noise(current)
                    self.state,bit=fq_ops.measure(self.state,current.wires[0],self.n,self.generator)
                    group.append((current,bit)); i+=1
                observed=self.noise.readout([bit for _,bit in group],tuple(x.wires[0] for x,_ in group),self.generator)
                # 写回的是含读出噪声的观测值，后续条件也读取这些值。
                # 按节点顺序写入，重复写同一经典位时后一次覆盖前一次。
                for (current,_),bit in zip(group,observed): self.classical[current.bits[0]]=int(bit)
                self.measured=True
                continue
            if kind=="if_else":
                # 若只有 true 分支且条件为假，不执行任何子块。
                chosen=0 if condition_matches(op.condition,self.classical,program.cmap) else 1
                if chosen<len(node.payload): self.run_block(node.payload[chosen])
            elif kind=="while_loop":
                # while 条件在每轮入口重新读取经典内存；循环体可测量并改写它。
                while condition_matches(op.condition,self.classical,program.cmap):
                    self.loop_tick()
                    try: self.run_block(node.payload[0])
                    except LoopSignal as signal:
                        # continue 信号不终止循环，自然返回下一轮条件检查。
                        if signal.kind=="break_loop": break
            elif kind=="for_loop":
                # 编译期已按取值顺序绑定局部参数，payload 中每项对应一次循环体。
                for body in node.payload:
                    self.loop_tick()
                    try: self.run_block(body)
                    except LoopSignal as signal:
                        # continue 跳过当前体余下节点，然后执行下一个已绑定的体。
                        if signal.kind=="break_loop": break
            elif kind=="switch_case":
                # 优先查找显式匹配；循环正常结束（没有 break）时才进入默认块。
                target=value_of(op.target,self.classical,program.cmap)
                fallback=None
                for values,body in node.payload:
                    if CASE_DEFAULT in values: fallback=body
                    elif target in values: self.run_block(body); break
                else:
                    if fallback is not None: self.run_block(fallback)
            elif kind in ("break_loop","continue_loop"):
                # 信号穿过 if/switch 等递归层，交给最近一层循环捕获。
                raise LoopSignal(kind)
            elif kind.startswith("save_"):
                # 保存位置决定读取的态和经典键，不把保存延迟到 shot 末尾。
                self.saves.add(node,self.state,self.classical,self.n)
            elif kind=="reset":
                # reset 的量子噪声作用于理想 reset 之后，与 measure 前置噪声不同。
                self.state=fq_ops.reset(self.state,node.wires[0],self.n,self.generator)
                self.apply_noise(node)
            elif kind=="initialize":
                if node.wires==tuple(range(self.n)):
                    # 按标准顺序覆盖全寄存器时，遵循 Aer 的替态相位契约：清除
                    # 此前状态和累计相位，再乘顶层 self.program.phase；此处不是
                    # 当前局部块的 phase。准备态块自身的相位随后由 run_block 计入。
                    self.state=fq_ops.zero(self.n,self.dtype,self.request.device)*cmath.exp(1j*self.program.phase)
                else:
                    # 子集或逆序全幅初始化先真实 reset，再准备局部态，不能直接
                    # 替换纠缠子系统振幅。该路径不复制 Aer 特定版本额外重复顶层
                    # 相位的现象；相关保存振幅差异见兼容矩阵，不能推为普遍等价。
                    for wire in node.wires: self.state=fq_ops.reset(self.state,wire,self.n,self.generator)
                # 初始化作为一个整体匹配噪声：其合成出的准备态门暂不套用模型。
                # finally 保证即使准备态执行失败，也恢复噪声屏蔽计数。
                self.suppress_noise+=1
                try: self.run_block(node.payload)
                finally: self.suppress_noise-=1
                self.apply_noise(node)
            elif kind=="channel":
                # 显式通道直接作用一次；Kraus 表示已由编译器验证并转换位序。
                self.state=fq_ops.channel(self.state,node.payload,node.wires,self.n,self.generator)
            elif kind=="set_statevector":
                # 完整替态同时清除旧态携带的相位，不重新乘顶层相位。
                # 克隆输入避免各 shot 共享同一可变状态张量。
                self.state=node.payload.clone()
            elif kind=="gate":
                # 只在经典条件成立时执行门及其后置噪声；条件为假时两者都跳过。
                condition=getattr(op,"condition",None)
                if condition is None or condition_matches(condition,self.classical,program.cmap):
                    self.state=fq_ops.gate(self.state,node.payload,self.n); self.apply_noise(node)
            i+=1

    def execute(self):
        """执行请求的 shots，返回原始数据字典和真实引擎版本元数据。

        counts/memory 内部使用 hex 经典值，由 Qiskit Result 负责寄存器格式化。
        保存聚合器跨 shot 累积；没有输出请求的线路不自动添加测量。
        """
        counts=Counter(); memory=[]; any_measure=False
        def has_output(program):
            """递归判断编译后 Program 中是否存在测量或保存，不判断分支是否到达。

            这里只检查可包含用户输出的控制流子块；初始化的准备态载荷没有
            用户测量/保存请求。零次 for 的体虽经预检，但不保留在执行载荷中。
            这个结果用于处理有经典内存但某 shot 未测量的情况。
            """
            for node in program.nodes:
                if node.kind=="measure" or node.kind.startswith("save_"): return True
                if node.kind in ("if_else","while_loop","for_loop") and any(has_output(p) for p in node.payload): return True
                if node.kind=="switch_case" and any(has_output(p) for _,p in node.payload): return True
            return False
        output_requested=has_output(self.program)
        # 不构建自动微分图；每个 shot 重新建立全零量子态和全零经典内存。
        # 随机源不逐 shot 重播 seed，避免每次得到同一个随机轨迹。
        with torch.no_grad():
            for _ in range(self.request.shots):
                self.state=fq_ops.zero(self.n,self.dtype,self.request.device)
                self.classical=[0]*self.sidecar.memory_slots
                self.measured=False; self.iterations=0
                self.run_block(self.program)
                if self.measured:
                    # 以经典槽位零为最低有效位编码，保留未写位的零值。
                    key=hex(sum(bit<<i for i,bit in enumerate(self.classical)))
                    counts[key]+=1
                    if self.request.memory: memory.append(key)
                    any_measure=True
                elif self.sidecar.memory_slots and output_requested:
                    # 语法上有输出且有经典槽位时，即使本次未进入任何测量分支，
                    # 也保留初始化的全零经典结果；仅有 save 的线路也符合此条件。
                    counts["0x0"]+=1
                    if self.request.memory: memory.append("0x0")
                    any_measure=True
        # 先取保存结果，再按是否有经典记录附加 counts/memory。
        # 编译期已禁止保存标签占用这两个保留键，避免静默覆盖保存内容。
        data=self.saves.result()
        if any_measure:
            data["counts"]=dict(counts)
            if self.request.memory: data["memory"]=memory
        # 版本字段描述本次执行环境；真实引擎来源还由独立调用拦截测试验证。
        return data, {"engine":"flagquantum", "method":"FQ statevector trajectories",
            "flagquantum_version":version("flagquantum"), "torch_version":torch.__version__,
            "qiskit_version":version("qiskit"), "adapter_version":"0.2.0",
            "device":str(self.state.device), "precision":str(self.dtype), "seed_simulator":self.request.seed_simulator}
