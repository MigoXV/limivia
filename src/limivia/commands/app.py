import logging

import typer

from limivia import Limivia
from limivia.types import LinkKind

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)
app = typer.Typer(help="LIMIVIA Python SDK", no_args_is_help=True)


@app.callback()
def main() -> None:
    """LIMIVIA SDK 诊断命令。"""


@app.command()
def scan(kind: str = typer.Option("ble", envvar="LIMIVIA_TRANSPORT", help="ble 或 usb")) -> None:
    """扫描本机设备；不连接、不改变板卡输出。"""
    if kind not in ("ble", "usb"):
        raise typer.BadParameter("kind 必须为 ble 或 usb。")
    transport: LinkKind = "ble" if kind == "ble" else "usb"
    with Limivia() as client:
        for device in client.devices.list(kind=transport):
            logger.info("%s  %s", device.id, device.name)


if __name__ == "__main__":
    app()
