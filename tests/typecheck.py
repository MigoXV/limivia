"""由 mypy 校验公开 API 的参数、返回类型与事件收窄；不访问硬件。"""

from typing import assert_type

from limivia import AsyncLimivia, Limivia
from limivia.types import ADCSample, DeviceEvent, GPIOReading, Snapshot


def consume(event: DeviceEvent) -> None:
    if event.type == "gpio.set.completed":
        assert_type(event.result, Snapshot)
        assert_type(event.request_id, int)
    elif event.type == "gpio.read.completed":
        assert_type(event.result, GPIOReading)
    elif event.type == "adc.sample":
        assert_type(event.data, ADCSample)
    elif event.type == "command.failed":
        assert_type(event.error.code, str)


async def async_api() -> None:
    async with AsyncLimivia() as client, client.devices.connect(target="test") as connection:
        assert_type(await connection.gpio.read(pin=13), int)
        assert_type(await connection.adc.start(pin=0, interval_ms=200), int)
        assert_type(await connection.send({"type": "state", "params": {}}), int)
        async for event in connection:
            consume(event)


def sync_api() -> None:
    with Limivia() as client, client.devices.connect(target="test") as connection:
        assert_type(connection.gpio.read(pin=13), int)
        assert_type(connection.send({"type": "state", "params": {}}), int)
        for event in connection:
            consume(event)
