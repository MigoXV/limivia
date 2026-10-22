class LimiviaError(Exception):
    """SDK 错误基类。"""


class DeviceConnectionError(LimiviaError, ConnectionError):
    """连接、握手或传输不可用。"""


class ProtocolError(LimiviaError, ValueError):
    """协议帧无效。"""


class InvalidCommandError(LimiviaError, ValueError):
    """命令尚未发送：参数或操作无效。"""

    def __init__(
        self, message: str, *, code: str = "invalid_argument", request_id: int | None = None
    ):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class QueueFullError(LimiviaError):
    """命令尚未入队；等待队列已满。"""
