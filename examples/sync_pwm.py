"""固定 PWM 或呼吸输出；duty 是百分比，breath_ms 是完整呼吸周期。"""

import logging
import sys
import time

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


def run(
    client: Limivia,
    *,
    kind: LinkKind = "ble",
    target: str | None = None,
    pin: int = 13,
    frequency: int = 1000,
    duty: float = 50,
    breath_ms: int = 0,
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
                start_id = connection.pwm.set(
                    pin=pin,
                    frequency=frequency,
                    duty=duty,
                    breath_ms=breath_ms,
                )
            except (InvalidCommandError, QueueFullError, ValidationError):
                cleanup_needed = False
                raise
            for event in connection:
                if event.type == "pwm.set.completed" and event.request_id == start_id:
                    logger.info("PWM 已启动：%s", event.result.to_json())
                    time.sleep(duration)
                    return
                if event.type == "command.failed" and event.request_id == start_id:
                    cleanup_needed = event.error.may_have_executed
                    raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
                if event.type == "connection.closed":
                    raise RuntimeError(f"连接已关闭：{event.error}")
            raise RuntimeError("事件流提前结束。")
        finally:
            if cleanup_needed:
                original_error = sys.exception()
                try:
                    stop_id = connection.pwm.stop(pin=pin)
                    for event in connection:
                        if event.type == "pwm.stop.completed" and event.request_id == stop_id:
                            logger.info("PWM 已确认停止，GPIO%s 已释放", pin)
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
    frequency: int = typer.Option(1000, min=5, max=40000, help="PWM 频率 Hz"),
    duty: float = typer.Option(50, min=0, max=100, help="占空比百分数；呼吸模式为峰值"),
    breath_ms: int = typer.Option(0, min=0, max=60000, help="0 为固定 PWM，否则为 200–60000 ms"),
    duration: DurationOption = 5,
) -> None:
    """运行 PWM，结束或中断时停止并释放引脚。"""
    if 0 < breath_ms < 200:
        raise typer.BadParameter("--breath-ms 必须为 0 或 200–60000")
    with command_line(), Limivia() as client:
        run(
            client,
            kind=kind.link,
            target=target,
            pin=pin,
            frequency=frequency,
            duty=duty,
            breath_ms=breath_ms,
            duration=duration,
        )


if __name__ == "__main__":
    typer.run(main)
