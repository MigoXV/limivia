import logging

import typer

from limivia import Limivia
from limivia.types import LinkKind

from ..constants import TransportKind

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)
app = typer.Typer(help="LIMIVIA Python SDK", no_args_is_help=True)


@app.callback()
def main() -> None:
    """LIMIVIA SDK 诊断命令。"""


@app.command()
def scan(
    kind: str = typer.Option(TransportKind.BLE, envvar="LIMIVIA_TRANSPORT", help="ble 或 usb"),
) -> None:
    """扫描本机设备；不连接、不改变板卡输出。"""
    if kind not in (TransportKind.BLE, TransportKind.USB):
        raise typer.BadParameter("kind 必须为 ble 或 usb。")
    transport: LinkKind = TransportKind.BLE if kind == TransportKind.BLE else TransportKind.USB
    with Limivia() as client:
        for device in client.devices.list(kind=transport):
            logger.info("%s  %s", device.id, device.name)


if __name__ == "__main__":
    app()
