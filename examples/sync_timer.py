"""设备端闪烁／脉冲定时；宿主控制观察时长，不承担电平计时。"""

import logging
import sys
import time
from enum import Enum
from typing import Annotated, Literal

import typer
from pydantic import ValidationError

from limivia import InvalidCommandError, Limivia, QueueFullError
from limivia.types import LinkKind

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


class Pattern(str, Enum):
    blink = "blink"
    pulse = "pulse"


def run(
    client: Limivia,
    *,
    kind: LinkKind = "ble",
    target: str | None = None,
    pin: int = 13,
    pattern: Literal["blink", "pulse"] = "blink",
    high_ms: int = 500,
    low_ms: int = 500,
    count: int = 0,
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
                start_id = connection.timer.start(
                    pin=pin,
                    kind=pattern,
                    high_ms=high_ms,
                    low_ms=low_ms,
                    count=count,
                )
            except (InvalidCommandError, QueueFullError, ValidationError):
                cleanup_needed = False
                raise
            state_id: int | None = None
            for event in connection:
                if event.type == "timer.start.completed" and event.request_id == start_id:
                    # 此事件确认启动，不表示有限闪烁或脉冲已经完成。
                    logger.info("定时器已启动：%s", event.result.to_json())
                    time.sleep(duration)
                    state_id = connection.state.retrieve()
                elif event.type == "state.completed" and event.request_id == state_id:
                    logger.info("观察结束时状态：%s", event.result.to_json())
                    return
                elif event.type == "command.failed":
                    if event.request_id == start_id:
                        cleanup_needed = event.error.may_have_executed
                    raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
                elif event.type == "connection.closed":
                    raise RuntimeError(f"连接已关闭：{event.error}")
            raise RuntimeError("事件流提前结束。")
        finally:
            if cleanup_needed:
                original_error = sys.exception()
                try:
                    # 有限任务可能在查询后自然结束并变为 output；timer.stop 会被拒绝。
                    # pin.release 同时适用于仍在计时和已经结束的引脚，不依赖查询时序。
                    if pattern == "pulse" or count > 0:
                        stop_id = connection.pin.release(pin=pin)
                    else:
                        stop_id = connection.timer.stop(pin=pin)
                    for event in connection:
                        if (
                            event.type in ("timer.stop.completed", "pin.release.completed")
                            and event.request_id == stop_id
                        ):
                            logger.info("定时器已确认停止，GPIO%s 已释放", pin)
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
    pattern: Annotated[Pattern, typer.Option(help="blink 闪烁或 pulse 单脉冲")] = Pattern.blink,
    high_ms: int = typer.Option(500, min=10, max=3600000, help="高电平时间 ms"),
    low_ms: int = typer.Option(500, min=10, max=3600000, help="低电平时间 ms，pulse 忽略"),
    count: int = typer.Option(0, min=0, max=100000, help="闪烁次数，0 为持续；pulse 忽略"),
    duration: DurationOption = 5,
) -> None:
    """观察设备端定时器，到达 duration 后停止，可能提前截断有限任务。"""
    with command_line(), Limivia() as client:
        run(
            client,
            kind=kind.link,
            target=target,
            pin=pin,
            pattern=pattern.value,
            high_ms=high_ms,
            low_ms=low_ms,
            count=count,
            duration=duration,
        )


if __name__ == "__main__":
    typer.run(main)
