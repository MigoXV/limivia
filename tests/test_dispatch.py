import asyncio

import pytest

from limivia import AsyncLimivia
from limivia._exceptions import ResultUnknownError, SubscriptionOverflowError
from tests.fakes import FakeBackend


def test_concurrent_tickets_and_independent_bounded_streams():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend, job_poll_interval=0.01) as client:
            async with client.devices.connect(kind="usb", target="test") as c:
                hub = c._hub
                first, slow = hub.stream(raw=True), hub.stream(size=1, raw=True)
                tickets = [hub.submit({"type": "state", "params": {"page": p}}) for p in range(4)]
                replies = await asyncio.gather(*(ticket.wait() for ticket in tickets))
                assert [reply.result.page for reply in replies] == [0, 1, 2, 3]
                assert (await anext(first)).type == "hello.completed"
                with pytest.raises(SubscriptionOverflowError):
                    await anext(slow)
                assert not c._core._closed and not hub.tickets

    asyncio.run(run())


def test_wait_timeout_and_cancellation_do_not_cancel_device_job():
    async def run():
        backend = FakeBackend()
        backend.connection.hold_jobs = True
        async with AsyncLimivia(backend=backend, job_poll_interval=0.01) as client:
            async with client.devices.connect(kind="usb", target="test") as c:
                hub = c._hub
                ticket = hub.submit({"type": "system.time", "params": {}})
                accepted = await ticket.wait(accepted=True)
                assert accepted.type == "command.accepted" and not ticket.terminal.done()
                with pytest.raises(ResultUnknownError) as caught:
                    await ticket.wait(timeout=0.01)
                assert caught.value.job_id == accepted.job.job_id
                task = asyncio.create_task(ticket.wait())
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not ticket.terminal.cancelled()
                backend.connection.hold_jobs = False
                assert (await ticket.wait()).type == "job.completed"
                assert not any(
                    command["op"] == "job.cancel" for command in backend.connection.commands
                )
                assert (
                    sum(command["op"] == "system.time" for command in backend.connection.commands)
                    == 1
                )

    asyncio.run(run())


def test_disconnect_finishes_waiters_with_known_job():
    async def run():
        backend = FakeBackend()
        backend.connection.hold_jobs = True
        async with AsyncLimivia(backend=backend) as client:
            async with client.devices.connect(kind="usb", target="test") as c:
                hub = c._hub
                ticket = hub.submit({"type": "system.time", "params": {}})
                await ticket.wait(accepted=True)
                await c.close()
                with pytest.raises(ResultUnknownError) as caught:
                    await ticket.wait()
                assert caught.value.job_id == ticket.job.job_id
                assert not hub.tickets

    asyncio.run(run())
