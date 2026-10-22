"""示例的命令行约定；不封装 SDK 连接、命令或事件消费。"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from enum import Enum
from typing import Annotated

import typer

from limivia import LimiviaError
from limivia.types import DeviceInfo, LinkKind


class Kind(str, Enum):
    ble = "ble"
    usb = "usb"

    @property
    def link(self) -> LinkKind:
        return "ble" if self is Kind.ble else "usb"


KindOption = Annotated[
    Kind, typer.Option("--kind", envvar="LIMIVIA_TRANSPORT", help="设备连接方式")
]
TargetOption = Annotated[
    str | None,
    typer.Option("--target", envvar="LIMIVIA_TARGET", help="本次扫描中的设备 ID"),
]
PinOption = Annotated[int, typer.Option("--pin", min=0, help="芯片 GPIO 编号，不是排针序号")]
DurationOption = Annotated[
    float, typer.Option("--duration", min=0.1, help="演示持续秒数，结束后停止并释放引脚")
]


def select_device(devices: Sequence[DeviceInfo], target: str | None) -> str:
    if not devices:
        raise RuntimeError("未发现设备，请检查固件、连接方式及系统权限。")
    if target is not None:
        if any(device.id == target for device in devices):
            return target
        reason = f"目标 {target!r} 不在本次扫描结果中"
    elif len(devices) == 1:
        return devices[0].id
    else:
        reason = "发现多台设备，请通过 --target 指定设备 ID"
    candidates = "\n".join(f"  {device.id}  {device.name}" for device in devices)
    raise RuntimeError(f"{reason}。可用设备：\n{candidates}")


@contextmanager
def command_line() -> Iterator[None]:
    """只在执行 CLI 时配置日志，并把预期错误转为可读诊断。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        yield
    except KeyboardInterrupt:
        typer.echo("已中断；设备清理结果见上方日志。", err=True)
        raise typer.Exit(130) from None
    except (LimiviaError, RuntimeError, ValueError, OSError) as exc:
        typer.echo(f"示例失败：{exc}", err=True)
        raise typer.Exit(1) from None
