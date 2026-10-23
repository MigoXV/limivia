import asyncio

from examples import _common
from examples._common import Kind
from limivia import AsyncLimivia
from tests.fakes import FakeBackend


def test_async_resource_cleanup_and_single_event_consumer(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(
        _common, "AsyncLimivia", lambda: AsyncLimivia(backend=backend, job_poll_interval=0.01)
    )

    async def run():
        async with _common.connect_async(Kind.usb, None, control=True) as c:
            async with _common.resource_async(c, "adc", {"pin": 0}, {}) as resource:
                assert resource

    asyncio.run(run())
    assert not backend.connection.resources and backend.connection.closed
