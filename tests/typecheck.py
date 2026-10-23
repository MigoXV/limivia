"""公开同步/异步门面与事件discriminator的静态检查。"""

from typing import assert_type

from limivia import AsyncLimivia, Limivia
from limivia.types import (
    DeviceDiscovery,
    DeviceEvent,
    DeviceIdentity,
    Hello,
    JobStatus,
    StatePage,
    StateSnapshot,
)


def consume(event: DeviceEvent) -> None:
    if event.type == "discovery.completed":
        assert_type(event.result, DeviceDiscovery)
    elif event.type == "state.snapshot.completed":
        assert_type(event.result, StateSnapshot)
    elif event.type == "hello.completed":
        assert_type(event.result, Hello)
    elif event.type == "state.completed":
        assert_type(event.result, StatePage)
    elif event.type == "command.accepted":
        assert_type(event.job, JobStatus)
    elif event.type == "job.completed":
        assert_type(event.job, JobStatus)
        assert_type(event.request_id, int)
    elif event.type == "job.failed":
        assert_type(event.error.reason, str)
        assert_type(event.error.code, int | None)


async def async_api():
    async with AsyncLimivia() as client, client.devices.connect(kind="usb", target="test") as c:
        assert_type(c.identity, DeviceIdentity | None)
        assert_type(await c.discover(), int)
        assert_type(await c.state.snapshot(), int)
        assert_type(await c.batch([{"type": "state", "params": {}}]), list[int])
        assert_type(await c.resource.open(kind="uart", pins={"tx": 20}, config={}), int)
        assert_type(await c.resource.call(resource=1, action="write", args={"data": b"hello"}), int)
        assert_type(await c.job.get(job_id=1), int)
        async for event in c:
            consume(event)


def sync_api():
    with Limivia() as client, client.devices.connect(kind="usb", target="test") as c:
        assert_type(c.resource.open(kind="gpio", pins={"pin": 13}, config={}), int)
        assert_type(c.buffer.write(buffer_id=1, offset=0, data=b"hello"), int)
        for event in c:
            consume(event)
