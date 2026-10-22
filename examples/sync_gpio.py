"""点亮合宙 CORE ESP32-C3 简约版的 GPIO13 / D5。"""

import logging

import typer

from limivia import Limivia
from limivia.types import LinkKind

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main(kind: str = typer.Option("ble", envvar="LIMIVIA_TRANSPORT")) -> None:
    if kind not in ("ble", "usb"):
        raise typer.BadParameter("kind 必须为 ble 或 usb")
    transport: LinkKind = "ble" if kind == "ble" else "usb"
    with Limivia() as client:
        devices = client.devices.list(kind=transport)
        if not devices:
            raise RuntimeError("未发现设备")
        with client.devices.connect(kind=transport, target=devices[0].id) as connection:
            request_id = connection.gpio.set(pin=13, mode="output", level=1)
            for event in connection:
                if event.type == "gpio.set.completed" and event.request_id == request_id:
                    logger.info("设备确认 GPIO13 输出高电平：%s", event.result.to_json())
                    return
                if event.type == "command.failed" and event.request_id == request_id:
                    raise RuntimeError(event.error.message)
                if event.type == "connection.closed":
                    raise RuntimeError("设备连接已关闭")


if __name__ == "__main__":
    typer.run(main)
