"""业务接口离线验证；不构成单板或外部服务互通证据。"""

import asyncio
import threading

import pytest

from limivia import (
    AsyncLimivia,
    ControlBusyError,
    DeviceConnectionError,
    DeviceRejectedError,
    DeviceSelectionError,
    JobCancelledError,
    JobFailedError,
    Limivia,
    ResourceCleanupError,
    ResultUnknownError,
    SubscriptionOverflowError,
)
from tests.fakes import FakeBackend, FakeTransport


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


def connected(backend, **kwargs):
    return AsyncLimivia.connect(
        kind="usb", backend=backend, job_poll_interval=0.01, timeout=0.15, job_timeout=0.3, **kwargs
    )


def test_sync_target_api_and_peripheral_return_types():
    backend = FakeBackend()
    threads = {t.ident for t in threading.enumerate()}
    with Limivia.connect(kind="usb", backend=backend, job_poll_interval=0.01) as board:
        with board.gpio.output(13, value=1) as led:
            assert led.read() == 1
            assert led.write(0).level == 0
            assert led.read() == 0
        with board.pwm.open(13, frequency=1000, duty=25) as pwm:
            assert pwm.set_duty(50).duty_percent == 50
            pwm.fade(0, duration_ms=100)
        with board.adc.open(0) as adc:
            assert adc.read().raw == 1234 and adc.read().millivolts is None
        with board.uart.open(tx=20, rx=21, loopback=True) as uart:
            assert uart.write(b"limivia") == 7
            uart.drain()
            assert uart.read(7) == b"limivia"
        assert board.state.snapshot().resources == []
        assert board.capabilities.retrieve(page=0).page == 0
    assert backend.discovered and backend.connection.closed
    assert not backend.connection.resources
    assert sum(c["op"] == "control.acquire" for c in backend.connection.commands) == 1
    assert len(set(backend.connection.loops)) == 1
    assert not any(
        t.ident not in threads and t.name == "limivia-sync" for t in threading.enumerate()
    )


def test_async_open_waits_for_execution_and_does_not_block_loop():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            backend.connection.hold_jobs = True
            led = board.gpio.output(13, value=1)
            opening = asyncio.create_task(led.open())
            await until(lambda: bool(backend.connection.jobs))
            for _ in range(5):
                await asyncio.sleep(0)
                assert not opening.done()
            backend.connection.hold_jobs = False
            assert await opening is led
            await led.write(0)
            await led.close()
            await led.close()
        assert sum(c["op"] == "resource.close" for c in backend.connection.commands) == 1

    asyncio.run(run())


def test_concurrent_resources_and_waiters_share_control_without_cross_talk():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            first, second = await asyncio.gather(
                board.gpio.output(13, value=1).open(),
                board.gpio.output(20, value=0).open(),
            )
            assert await asyncio.gather(first.read(), second.read()) == [1, 0]
            await asyncio.gather(first.write(0), second.write(1))
            assert await asyncio.gather(first.read(), second.read()) == [0, 1]
            job = await board.jobs.submit({"type": "system.time", "params": {}})
            results = await asyncio.gather(job.wait(), job.wait())
            assert results[0] == results[1]
        assert sum(c["op"] == "control.acquire" for c in backend.connection.commands) == 1
        assert not backend.connection.resources

    asyncio.run(run())


def test_job_timeout_cancel_wait_and_explicit_device_cancel_are_distinct():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            backend.connection.hold_jobs = True
            job = await board.jobs.submit({"type": "system.time", "params": {}})
            with pytest.raises(ResultUnknownError) as caught:
                await job.wait(timeout=0.005)
            assert caught.value.job_id == job.id and caught.value.may_have_executed
            waiter = asyncio.create_task(job.wait())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not any(c["op"] == "job.cancel" for c in backend.connection.commands)
            assert (await job.cancel()).cancel_requested
            backend.connection.hold_jobs = False
            with pytest.raises(JobCancelledError):
                await job.wait()
            assert sum(c["op"] == "system.time" for c in backend.connection.commands) == 1

    asyncio.run(run())


def test_cancelled_resource_operation_keeps_lock_until_confirmed_before_close():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            led = await board.gpio.output(13)
            backend.connection.hold_jobs = True
            writing = asyncio.create_task(led.write(1))
            await until(
                lambda: any(c["op"] == "resource.call" for c in backend.connection.commands)
            )
            writing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await writing
            closing = asyncio.create_task(led.close())
            await asyncio.sleep(0.02)
            assert not any(c["op"] == "resource.close" for c in backend.connection.commands)
            backend.connection.hold_jobs = False
            await closing
        assert not backend.connection.resources

    asyncio.run(run())


def test_cancel_during_open_waits_for_late_open_and_releases_resource():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            backend.connection.hold_jobs = True
            opening = asyncio.create_task(board.gpio.output(13).open())
            await until(lambda: bool(backend.connection.jobs))
            opening.cancel()
            await asyncio.sleep(0.01)
            backend.connection.hold_jobs = False
            with pytest.raises(asyncio.CancelledError):
                await opening
            assert not backend.connection.resources

    asyncio.run(run())


def test_cancellation_during_context_exit_still_waits_for_release():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:

            async def use():
                async with board.gpio.output(13):
                    backend.connection.hold_jobs = True

            task = asyncio.create_task(use())
            await until(
                lambda: any(c["op"] == "resource.close" for c in backend.connection.commands)
            )
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
            backend.connection.hold_jobs = False
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not backend.connection.resources

    asyncio.run(run())


def test_cleanup_failure_preserves_original_and_does_not_replay_close():
    backend = FakeBackend()
    original = ValueError("用户异常")
    with pytest.raises(ValueError) as caught:
        with Limivia.connect(kind="usb", backend=backend, job_poll_interval=0.01) as board:
            with board.gpio.output(13):
                backend.connection.reject_op = "resource.close"
                raise original
    assert caught.value is original
    assert original.cleanup_errors and isinstance(original.cleanup_errors[0], ResourceCleanupError)
    assert backend.connection.closed and backend.connection.resources
    assert sum(c["op"] == "resource.close" for c in backend.connection.commands) == 1


def test_cleanup_failure_without_original_is_reported_and_recover_is_explicit():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            led = await board.gpio.output(13)
            backend.connection.refuse = True
            with pytest.raises(ResourceCleanupError) as caught:
                await led.close()
            assert caught.value.resource_info.id == led.info.id
            backend.connection.refuse = False
            await led.recover()
            assert not backend.connection.resources

    asyncio.run(run())


def test_device_failure_keeps_job_driver_and_side_effect_diagnostics():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            backend.connection.hold_jobs = True
            job = await board.jobs.submit({"type": "system.time", "params": {}})
            backend.connection.jobs[job.id].update(
                driver_error=263,
                error_code="timeout",
                external_effect_possible=True,
            )
            backend.connection.job_state = "failed"
            backend.connection.hold_jobs = False
            with pytest.raises(JobFailedError) as caught:
                await job.wait()
            error = caught.value
            assert error.job_id == job.id and error.driver_error == 263
            assert error.external_effect_possible and error.request_id == job.request_id
            assert error.error.reason == "timeout"

    asyncio.run(run())


@pytest.mark.parametrize("boot_change", [False, True])
def test_disconnect_or_boot_change_invalidates_resource_and_preserves_job(boot_change):
    async def run():
        backend = FakeBackend()
        with pytest.raises(ResourceCleanupError):
            async with connected(backend) as board:
                led = await board.gpio.output(13)
                backend.connection.hold_jobs = True
                job = await board.jobs.submit({"type": "system.time", "params": {}})
                if boot_change:
                    backend.connection.hello["boot_id"] = "b" * 16
                else:
                    await backend.connection.queue.put(ConnectionError("disconnected"))
                await until(lambda: board._core._closed)
                with pytest.raises(ResultUnknownError) as caught:
                    await job.wait()
                assert caught.value.job_id == job.id
                with pytest.raises(DeviceConnectionError):
                    await led.write(0)

    asyncio.run(run())


@pytest.mark.parametrize("count", [0, 2])
def test_automatic_selection_requires_one_candidate_and_failure_stops_thread(count):
    class Backend(FakeBackend):
        async def discover(self, kind):
            return [{"id": str(i), "name": "test"} for i in range(count)]

    backend = Backend()
    with pytest.raises(DeviceSelectionError):
        with Limivia.connect(kind="usb", backend=backend):
            pytest.fail("cannot connect")
    assert not backend.connection.commands


def test_control_busy_does_not_steal_stop_or_send_resource_command():
    class Busy(FakeTransport):
        async def handle(self, wire):
            if wire["method"] == "control.acquire":
                self.commands.append({"op": "control.acquire"})
                await self.emit(
                    {"id": wire["id"], "ok": False, "error": {"reason": "control_busy"}}
                )
            else:
                await super().handle(wire)

    backend = FakeBackend(Busy())
    with Limivia.connect(kind="usb", backend=backend) as board:
        with pytest.raises(ControlBusyError):
            with board.gpio.output(13):
                pytest.fail("cannot acquire")
    assert [c["op"] for c in backend.connection.commands] == ["hello", "control.acquire"]


def test_notification_subscriptions_broadcast_and_slow_reader_does_not_break_waits():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            async with board.notifications.subscribe(topics=["data"]) as first:
                async with board.notifications.subscribe(topics=["data"], queue_size=1) as slow:
                    async with board.raw.subscribe() as raw:
                        for seq in range(1, 3):
                            await backend.connection.emit(
                                {
                                    "event": "data.available",
                                    "event_sequence": seq,
                                    "revision": 1,
                                    "resource": 1,
                                    "instance": 1,
                                    "job_id": 0,
                                    "sequence": seq,
                                    "dropped": 0,
                                }
                            )
                        assert (await board.state.retrieve()).page == 0
                        assert (await anext(first)).sequence == 1
                        assert (await anext(first)).sequence == 2
                        with pytest.raises(SubscriptionOverflowError):
                            await anext(slow)
                        assert (await anext(raw)).type == "hello.completed"
                        assert (await anext(raw)).type == "data.available"
                assert not any(c["op"] == "event.unsubscribe" for c in backend.connection.commands)
            assert sum(c["op"] == "event.unsubscribe" for c in backend.connection.commands) == 1

    asyncio.run(run())


def test_consuming_read_is_bound_to_old_control_and_stop_prevents_sending_it():
    async def run():
        backend = FakeBackend()
        async with connected(backend) as board:
            await board.control.acquire()
            read = board._hub.submit(
                {
                    "type": "resource.call",
                    "params": {
                        "resource": 1,
                        "instance": 1,
                        "action": "read",
                        "args": {"length": 1},
                    },
                },
                control=True,
            )
            stop = board._hub.submit({"type": "outputs.stop", "params": {}})
            with pytest.raises(DeviceRejectedError) as caught:
                await read.wait()
            assert caught.value.error.reason == "control_revoked"
            assert not caught.value.may_have_executed
            await stop.wait()
            assert not any(c["op"] == "resource.call" for c in backend.connection.commands)

    asyncio.run(run())


def test_cascade_waits_for_original_children_after_parent_disappears():
    class Cascade(FakeTransport):
        async def handle(self, wire):
            if wire["method"] == "resource.close" and wire["params"]["args"].get("cascade"):
                args = wire["params"]["args"]
                self.commands.append({"op": "resource.close", "params": args})
                self.resources.pop(args["resource"])
                for child in self.resources.values():
                    child["state"] = "closing"
                await self.emit({"id": wire["id"], "result": {"state": "closing"}})
            else:
                await super().handle(wire)

    async def run():
        backend = FakeBackend(Cascade())
        async with connected(backend) as board:
            bus = await board.resources.open("i2c.master", pins={"sda": 6, "scl": 7}, config={})
            child = await board.resources.open(
                "i2c.device", pins={}, config={"address": 72}, parent=bus
            )
            closing = asyncio.create_task(bus.close(cascade=True))
            await until(lambda: bus.info.id not in backend.connection.resources)
            await asyncio.sleep(0.01)
            assert not closing.done() and child.info.id in backend.connection.resources
            backend.connection.resources.pop(child.info.id)
            await closing
            await child.close()
            with pytest.raises(DeviceConnectionError):
                await child.call("read", length=1)
        assert sum(c["op"] == "resource.close" for c in backend.connection.commands) == 1

    asyncio.run(run())


def test_lost_open_response_keeps_unknown_resource_and_does_not_claim_release():
    class LostOpen(FakeTransport):
        async def handle(self, wire):
            if wire["method"] == "resource.open":
                self.capture = []
                await super().handle(wire)
                self.capture = None
            else:
                await super().handle(wire)

    async def run():
        backend = FakeBackend(LostOpen())
        with pytest.raises(ResultUnknownError) as caught:
            async with connected(backend) as board:
                await board.gpio.output(13)
        assert caught.value.may_have_executed
        assert caught.value.cleanup_errors
        assert backend.connection.resources and backend.connection.closed
        assert sum(c["op"] == "resource.open" for c in backend.connection.commands) == 1
        assert not any(c["op"] == "resource.close" for c in backend.connection.commands)

    asyncio.run(run())


@pytest.mark.parametrize("original_error", [False, True])
def test_transport_cleanup_failure_is_reported_without_masking_user_error(original_error):
    class CloseFails(FakeTransport):
        async def close(self):
            await super().close()
            raise OSError("host handle close failure")

    backend = FakeBackend(CloseFails())
    expected = ValueError if original_error else ResourceCleanupError
    with pytest.raises(expected) as caught:
        with Limivia.connect(kind="usb", backend=backend):
            if original_error:
                raise ValueError("user error")
    if original_error:
        assert str(caught.value) == "user error" and caught.value.cleanup_errors
    assert backend.connection.closed


def test_failed_handshake_keeps_original_when_transport_close_also_fails():
    class CloseFails(FakeTransport):
        async def close(self):
            await super().close()
            raise OSError("host handle close failure")

    backend = FakeBackend(CloseFails())
    with pytest.raises(DeviceConnectionError, match="v3握手失败") as caught:
        with Limivia.connect(kind="usb", backend=backend, expected_device_id="00:00:00:00:00:00"):
            pytest.fail("cannot connect")
    assert caught.value.cleanup_errors
