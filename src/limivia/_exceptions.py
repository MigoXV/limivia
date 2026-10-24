from typing import TYPE_CHECKING

from .constants import ErrorReason

if TYPE_CHECKING:
    from .types import DeviceError, DeviceEvent, JobStatus, ResourceInfo


class LimiviaError(Exception):
    """SDK 错误基类。"""


class DeviceConnectionError(LimiviaError, ConnectionError):
    """连接、握手或传输不可用。"""


class ProtocolError(LimiviaError, ValueError):
    """协议帧无效。"""


class InvalidCommandError(LimiviaError, ValueError):
    """命令尚未发送：参数或操作无效。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = ErrorReason.INVALID_ARGUMENT,
        request_id: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class QueueFullError(LimiviaError):
    """命令尚未入队；等待队列已满。"""


class DeviceSelectionError(DeviceConnectionError):
    """未发现设备，或有多个候选需要明确选择。"""


class OperationError(LimiviaError):
    """设备操作失败；完整诊断不依赖异常文本解析。"""

    def __init__(
        self,
        message: str,
        *,
        request_id: int | None = None,
        op: str = "",
        error: "DeviceError | None" = None,
        job: "JobStatus | None" = None,
        job_id: int | None = None,
        event: "DeviceEvent | None" = None,
        may_have_executed: bool = False,
    ):
        super().__init__(message)
        self.request_id = request_id
        self.op = op
        self.error = error
        self.job = job
        self.job_id = job.job_id if job else job_id
        self.resource_id = job.resource if job else None
        self.driver_error = job.driver_error if job else None
        self.event = event
        self.may_have_executed = may_have_executed or bool(error and error.may_have_executed)
        self.external_effect_possible = bool(
            (job and job.external_effect_possible) or (error and error.external_effect_possible)
        )
        self.resource_info: ResourceInfo | None = None
        self.cleanup_errors: list[BaseException] = []


class DeviceRejectedError(OperationError):
    """设备拒绝操作。"""


class ControlBusyError(DeviceRejectedError):
    """其他端持有控制权；SDK 不抢占。"""


class ResourceConflictError(DeviceRejectedError):
    """引脚、控制器或资源正在使用。"""


class JobFailedError(OperationError):
    """设备作业执行失败。"""


class JobCancelledError(OperationError):
    """设备作业已确认取消，外部副作用仍可能存在。"""


class ResultUnknownError(OperationError, TimeoutError):
    """等待期限已到或连接丢失，不能据此认定设备未执行。"""


class ResourceCleanupError(OperationError):
    """资源释放未确认；保留原始原因和资源诊断。"""


class SubscriptionOverflowError(LimiviaError):
    """该订阅的消费者过慢；其他订阅和业务等待继续工作。"""
