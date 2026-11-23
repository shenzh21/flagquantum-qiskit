# FlagQuantum Qiskit 适配器实现约束

本文件约束独立 `flagquantum-qiskit` 仓库。[官方研究快照](https://github.com/flagos-ai/FlagQuantum/tree/f0e74cf92f1784c5839c647a0781ad5db8cb6b85) 仅为研究参考；本仓库不依赖兄弟目录。若本地另有上游检出，默认只读，不能偷偷修改或用 sys.path 注入作为运行依赖。用户明确指令优先。

## 当前范围

0.2.0 已接通基础 Aer 功能，见 README / COMPATIBILITY / ARCHITECTURE / ADR-002。2026-11-19用户已授权 batch、memory、参数绑定、保存状态/概率/期望、初始化/矩阵、V2 wrappers、动态测量/reset/经典控制与常见噪声；首版拒绝这些功能的规则已被覆盖。GPU、多算法选择、分布式与性能调优仍不在本轮。历史首版草稿/测试保留，不覆盖历史证据。

## 必须保持

- Qiskit BackendV2 API，用户标准 `transpile(circuit, backend); backend.run(...).result()` 流程。
- validation / normalization+sidecar / strict import或显式转换 / FQ execution / measurement mapping / Job-Result责任边界。
- 真实FQ为唯一量子计算引擎。禁止Aer、BasicSimulator、Qiskit Statevector演化或自写NumPy演化器fallback；Statevector仅可包装结果，Kraus仅可转换局部通道表示。
- 固定官方FQ0.3.1，私有数值函数集中fq_ops并运行时检查版本。升级依赖/换fq.plan-run路线须记录ADR并独立数值验证。研究快照0.4.0不是实际运行证据。
- 不默认重复两套完整passes；Circuit内部fusion不冒充完整编译pipeline。Target只声明实际支持能力，未知custom不按name接受。
- strict importer禁止allow_lossy=True；专用控制/保存/噪声转换不得默默丢语义。unsupported选项/表达式提前明确拒绝。
- 以提交线路bit为准，不反转layout；Qiskit/FQ端序只在明确表示边界转换，不交换CX控制/目标。经典位初始0，按执行顺序后写覆盖前写。
- sidecar保留名称、metadata、cregs、phase/layout、标签/屏障和嵌套词法映射；不将任意metadata交给FQ。动态词法记录不能伪装逐shot轨迹。
- 私有kernel执行门/坍缩/reset/Kraus；适配器仅解释经典控制、状态输入表示、保存聚合。partial initialize先真实reset；canonical全幅initialize和set_statevector的相位契约见ARCHITECTURE。
- 噪声按门/reset之后、measure之前、readout在真实坍缩之后；local覆盖default。不同Kraus unraveling与Aer纯态逐shot差异必须说明，不弱化理想相位测试。
- seed使用局部RNG；run选项覆盖不改默认，Job重复result不重算，状态不跨实验污染。
- 保存single只保留最后值、avg/accum在线累计，list才逐次存储；预算包含跨标签/conditional分组，循环执行/编译展开都受限。

## 验证与交付

使用本目录隔离环境，不改系统Python/驱动，不安装大型CUDA。生产与测试文件若并行分工先声明所有权，避免覆盖他人修改。

修改后执行相关有意义测试；全套通过后只在新改动/失败/未解决风险时补测，不反复做无必要全量。保留测试依据与真实版本，不能拿ZIP附带报告或metadata代替执行来源证据。统计测试预先设阈值，精确态/相位另测；与Aer已确认差异必须给可复现证据和范围。

构建wheel前更新README版本和限制；wheel仅包含src包和metadata，不带upstream/venv/cache/tests。安装wheel后在包目录外验证导入site-packages与用户流程。最终记录命令、测试结果、仍存限制及产物路径；不宣称未验证平台、任意版本或性能。
