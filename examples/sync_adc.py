"""读取一次 ADC；单次读取也占用引脚，需要显式释放。"""

import logging
import sys

import typer
from pydantic import ValidationError

from limivia import InvalidCommandError, Limivia, QueueFullError
from limivia.types import LinkKind

from ._common import (
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
    pin: int = 0,
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
                read_id = connection.adc.read(pin=pin)
            except (InvalidCommandError, QueueFullError, ValidationError):
                cleanup_needed = False
                raise
            for event in connection:
                if event.type == "adc.read.completed" and event.request_id == read_id:
                    sample = event.result
                    voltage = (
                        f"{sample.millivolts} mV"
                        if sample.millivolts is not None
                        else "未校准／无电压值"
                    )
                    logger.info(
                        "GPIO%s raw=%s，电压=%s，calibrated=%s，设备时间=%s ms",
                        sample.pin,
                        sample.raw,
                        voltage,
                        sample.calibrated,
                        sample.uptime_ms,
                    )
                    return
                if event.type == "command.failed" and event.request_id == read_id:
                    cleanup_needed = event.error.may_have_executed
                    raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
                if event.type == "connection.closed":
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
    pin: PinOption = 0,
) -> None:
    """读取一次 ADC 后释放引脚；本板 ADC 支持 GPIO0／1／3／4。"""
    with command_line(), Limivia() as client:
        run(client, kind=kind.link, target=target, pin=pin)


if __name__ == "__main__":
    typer.run(main)
