"""示例共享CLI与单消费者等待；不提供模拟运行模式。"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from typing import Annotated, Any

import typer

from limivia import AsyncLimivia, Limivia
from limivia.types import ConnectionOptions, DeviceEvent, DeviceInfo, MQTTOptions, WebSocketOptions

logger = logging.getLogger(__name__)


class Kind(str, Enum):
    usb = "usb"
    ble = "ble"
    ws = "ws"
    mqtt = "mqtt"


KindOption = Annotated[
    Kind, typer.Option("--kind", envvar="LIMIVIA_TRANSPORT", help="usb/ble/ws/mqtt")
]
TargetOption = Annotated[
    str | None,
    typer.Option("--target", envvar="LIMIVIA_TARGET", help="USB/BLE扫描ID，或明确网络URL"),
]
PinOption = Annotated[int, typer.Option("--pin", min=0, help="芯片GPIO编号")]
DurationOption = Annotated[float, typer.Option("--duration", min=0.1, help="运行秒数")]


class ExampleError(RuntimeError):
    def __init__(self, event: DeviceEvent):
        self.event = event
        super().__init__(event.to_json())


def select_device(devices: list[DeviceInfo], target: str | None) -> str:
    if target is not None:
        if any(d.id == target for d in devices):
            return target
        # Backend accepts only by-id aliases that resolve to a scanned USB port.
        if target.startswith("/dev/serial/by-id/"):
            return target
        raise ValueError("目标不在本次扫描结果中")
    if len(devices) != 1:
        raise ValueError("需要恰好一台设备，或通过--target明确选择")
    return devices[0].id


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
    device = os.getenv("LIMIVIA_DEVICE_ID")
    if not device:
        raise ValueError("MQTT需要LIMIVIA_DEVICE_ID")
    data: dict[str, Any] = {
        **tls,
        "device_id": device,
        "username": os.getenv("LIMIVIA_MQTT_USERNAME"),
        "password": os.getenv("LIMIVIA_MQTT_PASSWORD"),
    }
    return MQTTOptions.model_validate(data)


def is_terminal(event: DeviceEvent, rid: int) -> bool:
    return getattr(event, "request_id", None) == rid and event.type != "command.accepted"


def check(event: DeviceEvent):
    if event.type in ("command.failed", "job.failed", "job.cancelled"):
        raise ExampleError(event)
    if event.type == "job.completed":
        return event.job.result or {}
    if event.type in (
        "hello.completed",
        "discovery.completed",
        "state.snapshot.completed",
        "state.completed",
        "capabilities.completed",
        "diagnostics.completed",
        "resource.get.completed",
        "command.completed",
    ):
        return event.result
    raise RuntimeError("非请求结果")


def wait(connection, rid: int):
    for event in connection:
        if is_terminal(event, rid):
            return check(event)
    raise RuntimeError("结果确认前连接关闭")


async def await_result(connection, rid: int):
    async with asyncio.timeout(40):
        async for event in connection:
            if is_terminal(event, rid):
                return check(event)
    raise RuntimeError("结果确认前连接关闭")


@contextmanager
def connect_sync(kind: Kind, target: str | None, *, control=False):
    with Limivia() as client:
        chosen = (
            select_device(client.devices.list(kind=kind.value), target)
            if kind in (Kind.usb, Kind.ble)
            else target
        )
        if not chosen:
            raise ValueError("网络连接需要--target URL")
        with client.devices.connect(
            kind=kind.value,
            target=chosen,
            options=options(kind),
            expected_device_id=os.getenv("LIMIVIA_DEVICE_ID"),
        ) as connection:
            if control:
                wait(connection, connection.control.acquire())
            yield connection


@asynccontextmanager
async def connect_async(kind: Kind, target: str | None, *, control=False):
    async with AsyncLimivia() as client:
        chosen = (
            select_device(await client.devices.list(kind=kind.value), target)
            if kind in (Kind.usb, Kind.ble)
            else target
        )
        if not chosen:
            raise ValueError("网络连接需要--target URL")
        async with client.devices.connect(
            kind=kind.value,
            target=chosen,
            options=options(kind),
            expected_device_id=os.getenv("LIMIVIA_DEVICE_ID"),
        ) as connection:
            if control:
                await await_result(connection, await connection.control.acquire())
            yield connection


def opened_resource(event: DeviceEvent) -> int:
    if event.type in ("job.completed", "job.failed", "job.cancelled", "command.accepted"):
        return event.job.resource
    return 0


@contextmanager
def resource_sync(c, kind, pins, config):
    resource = 0
    try:
        rid = c.resource.open(kind=kind, pins=pins, config=config)
        for event in c:
            if not is_terminal(event, rid):
                continue
            resource = opened_resource(event)
            check(event)
            break
        if not resource:
            raise RuntimeError("没有得到已创建资源ID")
        yield resource
    finally:
        original = sys.exception()
        if resource:
            try:
                wait(c, c.resource.close(resource=resource))
            except Exception:
                if original is None:
                    raise
                logger.exception("原始错误之外，资源关闭也失败；清理状态未知")


@asynccontextmanager
async def resource_async(c, kind, pins, config):
    resource = 0
    try:
        rid = await c.resource.open(kind=kind, pins=pins, config=config)
        async for event in c:
            if not is_terminal(event, rid):
                continue
            resource = opened_resource(event)
            check(event)
            break
        if not resource:
            raise RuntimeError("没有得到已创建资源ID")
        yield resource
    finally:
        original = sys.exception()
        if resource:
            try:
                await await_result(c, await c.resource.close(resource=resource))
            except Exception:
                if original is None:
                    raise
                logger.exception("原始错误之外，资源关闭也失败；清理状态未知")


def execute(fn):
    def main():
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        try:
            typer.run(fn)
        except KeyboardInterrupt:
            raise SystemExit(130) from None
        except (RuntimeError, ValueError, OSError) as exc:
            logger.error("%s", exc)
            raise SystemExit(1) from None

    return main
