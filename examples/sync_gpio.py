"""配置并读取 GPIO，退出前释放引脚；默认 GPIO13 为本板 D5。"""

import logging
import sys
import time
from enum import Enum
from typing import Annotated, Literal

import typer
from pydantic import ValidationError

from limivia import InvalidCommandError, Limivia, QueueFullError
from limivia.types import LinkKind, Pull

from ._common import (
    DurationOption,
    Kind,
    KindOption,
    PinOption,
    TargetOption,
    command_line,
    select_device,
)

logger = logging.getLogger(__name__)


class Mode(str, Enum):
    input = "input"
    output = "output"


class InputPull(str, Enum):
    none = "none"
    up = "up"
    down = "down"


def run(
    client: Limivia,
    *,
    kind: LinkKind = "ble",
    target: str | None = None,
    pin: int = 13,
    mode: Literal["input", "output"] = "output",
    pull: Pull = "none",
    level: Literal[0, 1] = 1,
    duration: float = 5,
) -> None:
    devices = client.devices.list(kind=kind)
    target = select_device(devices, target)
    with client.devices.connect(kind=kind, target=target) as connection:
        for event in connection:
            if (
                event.type == "hello.completed"
                and event.request_id == connection.handshake_request_id
            ):
                selected = next((p for p in event.result.state.pins if p.pin == pin), None)
                if selected is None or selected.mode != "idle":
                    raise RuntimeError(f"GPIO{pin} 不可用或已被占用，请检查状态并显式清理。")
                break
            if event.type == "connection.closed":
                raise RuntimeError(f"连接已关闭：{event.error}")
        else:
            raise RuntimeError("未收到握手结果。")

        # 调用被 Ctrl+C 打断时，命令也可能已提交；本地拒绝则无需清理。
        cleanup_needed = True
        try:
            try:
                set_id = connection.gpio.set(pin=pin, mode=mode, pull=pull, level=level)
            except (InvalidCommandError, QueueFullError, ValidationError):
                cleanup_needed = False
                raise
            read_id: int | None = None
            for event in connection:
                if event.type == "gpio.set.completed" and event.request_id == set_id:
                    logger.info("GPIO%s 已配置为 %s", pin, mode)
                    read_id = connection.gpio.read(pin=pin)
                elif event.type == "gpio.read.completed" and event.request_id == read_id:
                    logger.info(
                        "GPIO%s 实际电平=%s，保持 %.1f 秒", pin, event.result.level, duration
                    )
                    time.sleep(duration)
                    return
                elif event.type == "command.failed":
                    if event.request_id == set_id:
                        cleanup_needed = event.error.may_have_executed
                    raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
                elif event.type == "connection.closed":
                    raise RuntimeError(f"连接已关闭：{event.error}")
            raise RuntimeError("事件流提前结束。")
        finally:
            if cleanup_needed:
                original_error = sys.exception()
                try:
                    stop_id = connection.pin.release(pin=pin)
                    for event in connection:
                        if event.type == "pin.release.completed" and event.request_id == stop_id:
                            logger.info("GPIO%s 已确认释放为 idle", pin)
                            break
                        if event.type == "command.failed" and event.request_id == stop_id:
                            raise RuntimeError(event.error.to_json())
                        if event.type == "connection.closed":
                            raise RuntimeError(f"连接已关闭：{event.error}")
                    else:
                        raise RuntimeError("未收到停止或释放确认。")
                except Exception as exc:
                    logger.error("GPIO%s 停止状态未确认：%s", pin, exc)
                    if original_error is None:
                        raise


def main(
    kind: KindOption = Kind.ble,
    target: TargetOption = None,
    pin: PinOption = 13,
    mode: Annotated[Mode, typer.Option(help="输入或输出模式")] = Mode.output,
    pull: Annotated[InputPull, typer.Option(help="输入上下拉；输出必须为 none")] = InputPull.none,
    level: int = typer.Option(1, min=0, max=1, help="输出电平，输入模式忽略"),
    duration: DurationOption = 5,
) -> None:
    """配置 GPIO 并读取电平，结束或中断时释放引脚。"""
    if mode is Mode.output and pull is not InputPull.none:
        raise typer.BadParameter("输出模式必须使用 --pull none")
    with command_line(), Limivia() as client:
        run(
            client,
            kind=kind.link,
            target=target,
            pin=pin,
            mode=mode.value,
            pull=pull.value,
            level=1 if level else 0,
            duration=duration,
        )


if __name__ == "__main__":
    typer.run(main)
