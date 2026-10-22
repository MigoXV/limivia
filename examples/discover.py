"""第一步：扫描设备，记录 ID；此示例不建立连接。"""

import logging

import typer

from limivia import Limivia
from limivia.types import LinkKind

from ._common import Kind, KindOption, command_line

logger = logging.getLogger(__name__)


def run(client: Limivia, *, kind: LinkKind = "ble") -> None:
    devices = client.devices.list(kind=kind)
    if not devices:
        logger.info("未发现设备，请检查固件、连接方式及系统权限。")
    for device in devices:
        logger.info("设备 ID=%s，名称=%s", device.id, device.name)


def main(kind: KindOption = Kind.ble) -> None:
    """扫描 USB／BLE 设备，供其他示例的 --target 使用。"""
    with command_line(), Limivia() as client:
        run(client, kind=kind.link)


if __name__ == "__main__":
    typer.run(main)
