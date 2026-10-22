"""同步入门：扫描、连接、握手和状态查询。与 async_state 对照阅读。"""

import logging

import typer

from limivia import Limivia
from limivia.types import LinkKind

from ._common import Kind, KindOption, TargetOption, command_line, select_device

logger = logging.getLogger(__name__)


def run(client: Limivia, *, kind: LinkKind = "ble", target: str | None = None) -> None:
    devices = client.devices.list(kind=kind)
    target = select_device(devices, target)
    with client.devices.connect(kind=kind, target=target) as connection:
        # 进入连接上下文已完成握手；其结果仍由同一事件流交付。
        hello_id = connection.handshake_request_id
        refreshed = False
        state_id: int | None = None
        for event in connection:
            if event.type == "hello.completed" and event.request_id == hello_id:
                logger.info(
                    "%s：%s，固件=%s，协议=%s，能力=%s",
                    "显式 hello" if refreshed else "自动握手",
                    event.result.name,
                    event.result.firmware,
                    event.result.protocol,
                    event.result.capabilities.to_json(),
                )
                if not refreshed:
                    hello_id = connection.hello()
                    refreshed = True
                else:
                    state_id = connection.state.retrieve()
            elif event.type == "state.completed" and event.request_id == state_id:
                logger.info("完整状态：%s", event.result.to_json())
                return
            elif event.type == "command.failed":
                raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
            elif event.type == "connection.closed":
                raise RuntimeError(f"查询完成前连接已关闭：{event.error}")
        raise RuntimeError("事件流提前结束。")


def main(kind: KindOption = Kind.ble, target: TargetOption = None) -> None:
    """读取设备信息和状态，不改变引脚。"""
    with command_line(), Limivia() as client:
        run(client, kind=kind.link, target=target)


if __name__ == "__main__":
    typer.run(main)
