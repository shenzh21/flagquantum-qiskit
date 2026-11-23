# FlagQuantum 正确性和效率：公开 benchmark 方案选型

核查日期：2026-11-23。**当前已按用户“先用比较好实现的”选择轻量 QASMBench 路线：3 个固定公开输入 + 独立 FQ/Aer 子进程 + Qiskit Statevector 对照。** 不安装新的通用框架。已完成 CPU/CUDA double 同精度比较，以及 FQ CPU/CUDA single 对 Aer double 的高精度正确性验证。single 的性能仅比较同环境 FQ CPU/GPU，不能与 double 参照算公平加速比；原 Aer single 子进程退出仍未解决，见 [执行说明和结果](README.md)。下文保留通用框架调研，作为后续扩展参考。

## 当前路线与未来框架

当前轻量脚本只连接现有引擎并记录比较结果，电路本身采用 QASMBench 公开输入，不重新发明 benchmark 算法。**后续若扩展为通用模拟器跑分平台，可优先评估 NVIDIA `nv-quantum-benchmarks`，备选 qibojit-benchmarks。** 它们组织多模拟器运行与计时。MQT Bench 和 QASMBench 主要解决“跑哪些有出处的电路”。现成框架仍需要新增 FQ backend 和独立数值核对层，不能仅凭有计时结果就证明正确。

| 候选 | 原本解决什么问题 | 对本项目的价值 | 限制与接入工作 | 建议 |
| --- | --- | --- | --- | --- |
| [nv-quantum-benchmarks](https://github.com/NVIDIA/cuQuantum/blob/main/benchmarks/README.md) | NVIDIA 维护的多模拟器 CPU/GPU 性能框架，分 circuit 和 API 层 | 统一 frontend/backend、精度、输出任务、预热、重复与线程设置；已有 Aer/Qsim/Qulacs 等 | 需要 FQ backend；依赖 CUDA/CuPy/cuQuantum 生态，Windows 原生适用性未验证；还需增加跨引擎数值核对 | **GPU 模拟器横评框架首选** |
| [MQT Bench](https://github.com/munich-quantum-toolkit/bench) | 多算法、多规模、多抽象层的线路生成 | 用官方生成器固定种子和参数，做规模扫描；直接接 Qiskit 线路 | 它主要是电路来源，并非 FQ/Aer 正确性 oracle 或完整计时器；需接入执行和误差比较 | **主线路来源** |
| [QASMBench](https://github.com/pnnl/QASMBench) | 固定 OpenQASM 输入，覆盖不同算法 | 文件可固定 commit 和哈希，复现、回归、论文引用方便 | 尺寸离散；旧 QASM 门声明需兼容解析；不能随意移除中途测量；需保留许可证 | **本次采用** |
| [qibojit-benchmarks](https://github.com/qiboteam/qibojit-benchmarks) | 跨 CPU/GPU 模拟器的运行效率比较 | 区分首次执行、重复运行、状态传输和采样；已有 Qiskit、Qulacs、Qsim 等接口 | 当前 Qiskit 桥接仍导入旧 `qiskit.providers.aer`，不能直接宣称兼容本项目 Qiskit 2.6.2；还需 FQ bridge | **通用模拟器框架备选** |
| [QED-C 应用 benchmark](https://github.com/SRI-International/QC-App-Oriented-Benchmarks) | 跨平台的应用级正确率和用户体验 | 以后演示完整 Qiskit 用户工作流、应用解的质量与时间 | 含硬件、采样、应用质量等因素，不能把它的应用分数直接称为状态向量内核效率 | 后续应用层补充 |
| [Qiskit Benchpress](https://github.com/Qiskit/benchpress) | 电路创建、操作、编译的 SDK 比较 | 以后定位 Qiskit 转译和本工具转换开销 | 研究对象主要是软件前端/编译，不是模拟器的数值演化速度 | 不作为本次主 benchmark |

官方依据：MQT 的 [四层抽象说明](https://mqt.readthedocs.io/projects/bench/en/stable/abstraction_levels.html) 区分算法、目标无关、原生门、物理映射。模拟器对比优先算法或目标无关层，再生成共享门集；避免无必要物理芯片路由改变宽度和 SWAP 数。Qibo 的 [README](https://github.com/qiboteam/qibojit-benchmarks) 列出首次执行、重复执行、传输和抽样字段；它的 [Qiskit 适配源码](https://github.com/qiboteam/qibojit-benchmarks/blob/main/benchmarks/libraries/qiskit.py) 仍是旧导入路径。Benchpress 自述和论文题目明确关注 circuit creation/manipulation/compilation。

维护与复现：本次 GitHub API 查询 MQT 最新 release 为 `v2.4.0`（2026-11-13），可固定 tag，MIT；QASMBench README 标版本 1.4，本次固定 commit `357b942396d5c2b7cbc1c229c585a6ef5ccaebac`，使用仓库原 LICENSE/NOTICE，不把 GitHub 的 `NOASSERTION` 误称为没有许可。Qibo benchmark 最后 push 查询值为 2026-04-22，Apache-2.0；QED-C 为 2026-11-19，Apache-2.0；Benchpress 为 2026-11-05，Apache-2.0。仓库 push 时间只作调查快照，不等于每个桥接器均已更新或兼容。正式运行应记录实际源码 commit 和依赖锁定文件。

## 为什么更倾向 NVIDIA 的通用框架

官方 [CLI 源码](https://github.com/NVIDIA/cuQuantum/blob/main/benchmarks/nv_quantum_benchmarks/run.py) 同时提供 Aer CPU、Aer 原生 CUDA、Aer cuStateVec 以及其他模拟器，不只测 NVIDIA 自己的内核；`circuit` 模式可选 statevector、sampling 等输出任务。它符合本项目“同一批线路，用不同引擎运行”的目标。这里应使用 circuit 层，API 层主要测 cuQuantum 专用函数，不能直接拿来替代 FQ 电路执行。

接入路线：保留 Qiskit frontend，新增 FQ backend。在 preprocessing 中完成严格转换，在 run 中实际执行并输出结果；注册到 backend/config，同时更新 frontend 兼容检查和 CPU backend 分类。接口见 [Backend 基类](https://github.com/NVIDIA/cuQuantum/blob/main/benchmarks/nv_quantum_benchmarks/backends/backend.py)。另做适配器用户流程实验，避免混入原生引擎成绩。

安装成本需要单独评估：[setup.py](https://github.com/NVIDIA/cuQuantum/blob/main/benchmarks/setup.py) 默认拉入 cuQuantum Python；[runner](https://github.com/NVIDIA/cuQuantum/blob/main/benchmarks/nv_quantum_benchmarks/run_interface.py) 无条件导入 CuPy。因此选择 CPU backend 也不意味着整个框架不需要 CUDA 生态依赖。不能把它当成只装 Qiskit 就可跑的纯 Python 脚本。[NVIDIA 官方依赖表](https://docs.nvidia.com/cuda/cuquantum/latest/getting-started/index.html#dependencies) 为 cuStateVec/cuTensorNet 列出的操作系统是 Linux。本次尚未安装，Windows 原生可运行性未验证；正式 GPU 比较优先考虑独立 Linux/WSL 环境，这是部署建议而非已验证结果。某些后端的 GPU 包还可能需要编译或使用官方容器。

该套件是公开可扩展的性能框架，不是保证所有模拟器数学正确的认证标准。还需在计时前对同一线路做振幅/概率核对、在计时后记录实际设备和输出完整性，并核查 GPU 同步与状态缓存边界。也不能因为框架有 `--compute-mode` 就默认每个 backend 都支持所有模式。

## 首轮选哪些电路

以下为选型建议，不是已执行的 MQT 套件成绩。MQT 官方 [算法目录](https://mqt.readthedocs.io/projects/bench/en/stable/benchmark_selection.html) 有相应工厂。

| 线路族 | 首选来源 | 为什么选 |
| --- | --- | --- |
| GHZ / graphstate | MQT `ghz`、`graphstate` | 易解释的基础纠缠正确性和低深度开销；不能单独代表一般算法性能 |
| QFT / QFT entangled | MQT `qft`、`qftentangled`；QASMBench `qft_n4` | 受控相位和长距离门，容易暴露相位、端序与分解问题 |
| QAOA / SU2 ansatz | MQT `qaoa`、`vqe_su2`；QASMBench `qaoa_n6` | 参数化旋转与纠缠层，适合按宽度和层数扫描；此轮比较固定参数前向执行，不比较训练收敛 |
| 随机通用电路 | MQT `randomcircuit` | 跨随机种子测更普遍的门组合与纠缠；种子、门分布、深度都要固定 |
| Hamiltonian / Ising 演化 | QASMBench `ising_n10`；后续 QED-C Hamiltonian simulation | 与物理模拟相关，有重复旋转与纠缠结构，观察 fusion 与大状态向量的影响 |

小规模正确性可先 4–12 比特；性能从 12、16、20、24 比特逐级试，不预先承诺能跑到多少。双精度裸状态向量约 `16 * 2**n` 字节，24 比特约 256 MiB；实际还需要临时空间、拷贝、保存结果，不能用裸向量大小估算显存上限。8 GB 显卡不应直接选择 29 比特 double（裸向量已约 8 GiB）。当前适配器自身还有 24 比特限制；原生 FQ 扫描与适配器扫描必须分开标注。

## 如何交叉验证而不混淆测试对象

1. 固定公开电路、输入态、参数、seed、精度和共享门集。保留原文件哈希，任何只为获取最终状态而移除的终端测量都写入记录；中途测量不允许这样删除。
2. **小规模理想线路**：原生 FQ 与 Aer 的最终复振幅比较，再用 Qiskit `Statevector.from_instruction` 作第三方实现对照。FQ 的 q0 是 MSB，Qiskit 的 q0 是 LSB，显式调整输出索引；不能反转 CX 控制/目标。报告原始振幅误差、归一化误差、概率误差和保真度。相位对齐误差仅用于诊断，不能掩盖 API 承诺的全局相位丢失。
3. 先检查同一个逻辑电路经共享分解是否仍等价于原电路；如果只比较两个模拟器执行同一个错误转换结果，会漏掉转换问题。必要时再以人工解析的小门例和非零初态逆线路定位到 importer 或数值 kernel。
4. **采样线路**：用精确概率或解析解作参照，在预先规定的 shots、统计阈值、多种 seed 下验分布。不同库相同 seed 不等于逐 shot 相同，不用 counts 完全相等作一般判据。
5. **噪声和动态控制**另建功能组：小规模密度矩阵/解析分支作参照，记录 reset、测量映射、条件、噪声的语义。前述标准静态电路库不能替代这组验证。

比较对象分三层：**原生 FQ vs 原生 Aer**回答数值引擎问题；**同一 FQ 的 CPU vs GPU**回答设备收益；**FlagQuantumBackend vs AerSimulator 的用户流程**回答适配器体验。不能把适配器的逐 shot 通用轨迹路径耗时全部归咎于 FQ。当前 `save_statevector` 会走适配器通用路径，也不能用它代表普通终端测量的 `Circuit.sample` 快路径。

## 公平效率测量的要求

分别保存电路生成、转译、FQ 导入、首次运行、预热后运行、输出传输、测量抽样时间。CPU 固定线程并增加合理多线程配置；GPU 在计时边界同步，记录设备型号、驱动、CUDA、精度、峰值显存。原生 FQ 禁止重复读缓存状态当执行；Aer 固定 `method='statevector'`，防止自动挑 stabilizer 等算法造成比较对象变化。双方用相同输出任务；GPU 留在显存的态不能直接对比另一个已经传到 CPU 的完整态。

先验证正确再报告速度。预热至少 2 次，重复至少 5 次，保留每次值与中位数/离散度；较长正式测试再增加重复和独立进程轮次。首次运行应区分真正冷进程和同一进程的首个案例。引擎各自独立子进程/环境，既控制初始化边界，也降低动态库交互影响。Aer 是否可用 GPU 必须实测 `available_devices()`；FQ GPU 对 Aer CPU 的比值只能称“该机器下设备与框架组合比较”，不能称“同硬件 FQ 胜过 Aer”。

这些计时与对照规则是本项目评估设计，参考公开方案后制定；并不是 MQT 或 QASMBench 自动提供的质量认证。
