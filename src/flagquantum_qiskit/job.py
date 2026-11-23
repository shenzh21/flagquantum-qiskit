"""把已完成的同步计算包装成 Qiskit JobV1 接口。

backend.run 在返回 Job 之前已完成执行；读取 result 不会再次采样，
这里也没有线程、后台任务或远程队列。
"""

# 防止调用者通过持有或读取 sidecar 修改 Job 内保存的元信息。
from copy import deepcopy

# JobV1 是 Qiskit 作业接口；它与后端采用 BackendV2 并不冲突。
from qiskit.providers import JobStatus, JobV1


class FlagQuantumJob(JobV1):
    """保存一个聚合 Result 以及对应 sidecar 的已完成作业。

    输入 result 已由后端构造成功；sidecar 可以是单个对象或批次列表。
    Result 本身按引用缓存，sidecar 则在存入和读出时都深拷贝。
    """

    # 告知 JobV1 基类这是同步作业，不需要等待异步执行完成。
    _async = False

    def __init__(self, backend, job_id, result, sidecar):
        """关联所属 backend/job_id，保存结果与独立的 sidecar 副本。"""

        super().__init__(backend, job_id)
        self._result = result
        self._sidecar = deepcopy(sidecar)

    @property
    def circuit_sidecar(self):
        """返回 sidecar 的防御性副本，保留结构化 layout 和用户 metadata。

        property 让调用者以属性形式读取；修改读出的字典/列表不会污染 Job。
        这里只保存来源信息，不保留 FQ IR、状态向量或重新执行所需的状态。
        """

        return deepcopy(self._sidecar)

    def submit(self):
        """兼容提交接口；作业构造前已经完成，故不做操作并隐式返回 None。"""

    def result(self, timeout=None):
        """返回同一个缓存 Result；timeout 仅用于兼容接口，无需实际等待。"""

        return self._result

    def status(self):
        """返回 DONE；失败在 backend.run 中抛出，不包装成已创建的失败 Job。"""

        return JobStatus.DONE

    def cancel(self):
        """返回 False，因为已完成的同步计算不能再取消。"""

        return False
