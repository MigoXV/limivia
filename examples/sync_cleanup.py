"""显式恢复设备：单引脚释放，或停止全部实验输出和采集。"""

import logging

import typer

from limivia import Limivia
from limivia.types import LinkKind

from ._common import Kind, KindOption, TargetOption, command_line, select_device

logger = logging.getLogger(__name__)


def run(
    client: Limivia,
    *,
    kind: LinkKind = "ble",
    target: str | None = None,
    pin: int | None = None,
    all_outputs: bool = False,
) -> None:
    if (pin is not None) == all_outputs:
        raise ValueError("必须且只能选择 --pin 或 --all。")
    devices = client.devices.list(kind=kind)
    target = select_device(devices, target)
    with client.devices.connect(kind=kind, target=target) as connection:
        if pin is not None:
            request_id = connection.pin.release(pin=pin)
        else:
            request_id = connection.outputs.stop()
        for event in connection:
            if (
                event.type in ("pin.release.completed", "outputs.stop.completed")
                and event.request_id == request_id
            ):
                logger.info("已确认清理：%s", event.result.to_json())
                return
            if event.type == "command.failed" and event.request_id == request_id:
                raise RuntimeError(f"停止状态未确认：{event.error.to_json()}")
            if event.type == "connection.closed":
                raise RuntimeError(f"停止状态未确认，连接已关闭：{event.error}")
        raise RuntimeError("停止状态未确认，事件流提前结束。")


def main(
    kind: KindOption = Kind.ble,
    target: TargetOption = None,
    pin: int | None = typer.Option(None, min=0, help="释放这个 GPIO 的资源"),
    all_outputs: bool = typer.Option(False, "--all", help="停止全部实验输出及 ADC 流"),
) -> None:
    """清理指定引脚或全部实验资源；会影响其他程序留在设备上的任务。"""
    if (pin is not None) == all_outputs:
        raise typer.BadParameter("必须且只能选择 --pin 或 --all")
    with command_line(), Limivia() as client:
        run(client, kind=kind.link, target=target, pin=pin, all_outputs=all_outputs)


if __name__ == "__main__":
    typer.run(main)
