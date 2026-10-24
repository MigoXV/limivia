"""高级用户显式读取 raw 事件；普通业务调用无需此循环。"""

from limivia import EventType, Limivia, TransportKind
from limivia.constants import OperationName

from .._common import run


def main():
    """高级示例：显式订阅 raw 事件并关联两个只读请求。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.raw.subscribe() as events:
            pending = set(
                board.raw.batch(
                    [
                        {"type": OperationName.STATE, "params": {"page": 0}},
                        {"type": OperationName.DIAGNOSTICS, "params": {}},
                    ]
                )
            )
            for event in events:
                if (
                    event.type == EventType.STATE_COMPLETED
                    or event.type == EventType.DIAGNOSTICS_COMPLETED
                ):
                    print(event.result.to_json())
                    pending.discard(event.request_id)
                elif event.type == EventType.COMMAND_FAILED:
                    raise RuntimeError(f"{event.op}: {event.error.reason}")
                elif event.type == EventType.CONNECTION_CLOSED:
                    raise RuntimeError("请求结果确认前连接已关闭")
                if not pending:
                    break


if __name__ == "__main__":
    run(main)
