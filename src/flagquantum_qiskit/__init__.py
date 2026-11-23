"""包的公开入口：用 Qiskit 描述线路，由 FlagQuantum 的 CPU/CUDA 引擎执行。

用户可直接 ``from flagquantum_qiskit import FlagQuantumBackend``。
本模块只导出后端类和包版本；创建后端、转译和运行由调用者明确发起。
"""

# 把内部 backend 模块中的类暴露在包顶层，保持用户导入路径简洁。
from .backend import FlagQuantumBackend

# 这是适配器版本，不是外部 FlagQuantum 或 Qiskit 的版本。
__version__ = "0.2.0"
# 限定 ``from flagquantum_qiskit import *`` 的公开名称。
__all__ = ["FlagQuantumBackend"]
