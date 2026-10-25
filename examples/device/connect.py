"""专门的多传输连接示例；普通示例直接调用 Limivia.connect。"""

import os
from enum import Enum
from typing import Annotated

import typer

from limivia import Limivia, TransportKind
from limivia.types import ConnectionOptions, MQTTOptions, WebSocketOptions


class Kind(str, Enum):
    usb = TransportKind.USB
    ble = TransportKind.BLE
    ws = TransportKind.WS
    mqtt = TransportKind.MQTT


def options(kind: Kind) -> ConnectionOptions | None:
    if kind not in (Kind.ws, Kind.mqtt):
        return None
    tls = {
        "ca_file": os.getenv("LIMIVIA_CA_FILE"),
        "certificate_file": os.getenv("LIMIVIA_CERT_FILE"),
        "private_key_file": os.getenv("LIMIVIA_KEY_FILE"),
    }
    if kind == Kind.ws:
        return WebSocketOptions(**tls)
    device_id = os.getenv("LIMIVIA_DEVICE_ID")
    if not device_id:
        raise typer.BadParameter("MQTT 需要设置 LIMIVIA_DEVICE_ID")
    return MQTTOptions.model_validate(
        {
            **tls,
            "device_id": device_id,
            "username": os.getenv("LIMIVIA_MQTT_USERNAME"),
            "password": os.getenv("LIMIVIA_MQTT_PASSWORD"),
        }
    )


def main(
    kind: Annotated[
        Kind, typer.Option(envvar="LIMIVIA_TRANSPORT", help="usb/ble/ws/mqtt")
    ] = Kind.usb,
    target: Annotated[
        str | None, typer.Option(envvar="LIMIVIA_TARGET", help="设备目标或网络 URL")
    ] = None,
):
    """选择传输、目标和 TLS 配置，连接后读取状态快照。"""
    with Limivia.connect(
        kind=kind.value,
        target=target,
        options=options(kind),
        expected_device_id=os.getenv("LIMIVIA_DEVICE_ID"),
    ) as board:
        print(board.state.snapshot().to_json())


if __name__ == "__main__":
    typer.run(main)
