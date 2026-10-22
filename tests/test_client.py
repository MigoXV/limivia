import asyncio
import threading

import pytest
from pydantic import ValidationError

from limivia import AsyncLimivia, DeviceConnectionError, Limivia, QueueFullError
from limivia.types import ADCSample, Snapshot

from .fakes import HELLO, SAMPLE, STATE, FakeBackend


def test_async_all_results_and_notifications_share_stream():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend) as client:
            assert (await client.devices.list())[0].id == "test"
            async with client.devices.connect(target="test") as connection:
                hello = await connection.recv()
                assert hello.type == "hello.completed"
                assert hello.result.name == "设备"
                request_id = await connection.adc.start(pin=0, interval_ms=200)
                assert isinstance(request_id, int)
                event = await connection.recv()
                assert event.type == "adc.start.completed"
                assert event.request_id == request_id
                assert isinstance(event.result, ADCSample)
                transport = backend.transports[-1]
                await transport.emit({"v": 1, "event": "adc", "data": SAMPLE})
                await transport.emit({"v": 1, "event": "changed", "revision": 3})
                assert (await connection.recv()).data.millivolts == 900
                assert (await connection.recv()).revision == 3
                transport.refuse = True
                failed_id = await connection.gpio.set(pin=13, mode="output", level=1)
                failed = await connection.recv()
                assert failed.type == "command.failed"
                assert failed.request_id == failed_id
                assert failed.error.code == "pin_busy"
                transport.refuse = False
                await connection.state.retrieve()
                assert isinstance((await connection.recv()).result, Snapshot)
            assert transport.closed
            assert (await connection.recv()).type == "connection.closed"
            with pytest.raises(StopAsyncIteration):
                await connection.recv()
        assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("limivia-")]

    asyncio.run(run())


OPERATIONS = [
    ("hello", {}, "hello.completed"),
    ("state.retrieve", {}, "state.completed"),
    ("gpio.set", {"pin": 13, "mode": "output", "level": 1}, "gpio.set.completed"),
    ("gpio.read", {"pin": 13}, "gpio.read.completed"),
    ("pwm.set", {"pin": 13, "frequency": 1000, "duty": 50}, "pwm.set.completed"),
    ("pwm.stop", {"pin": 13}, "pwm.stop.completed"),
    ("adc.read", {"pin": 0}, "adc.read.completed"),
    ("adc.start", {"pin": 0, "interval_ms": 200}, "adc.start.completed"),
    ("adc.stop", {"pin": 0}, "adc.stop.completed"),
    ("timer.start", {"pin": 13, "kind": "blink", "high_ms": 500}, "timer.start.completed"),
    ("timer.stop", {"pin": 13}, "timer.stop.completed"),
    ("pin.release", {"pin": 13}, "pin.release.completed"),
    ("outputs.stop", {}, "outputs.stop.completed"),
]


@pytest.mark.parametrize("method,params,event_type", OPERATIONS)
@pytest.mark.parametrize("sync", [False, True])
def test_resource_parity(method, params, event_type, sync):
    backend = FakeBackend()

    def resolve(connection):
        value = connection
        for part in method.split("."):
            value = getattr(value, part)
        return value

    if sync:
        with Limivia(backend=backend) as client:
            client.devices.list()
            with client.devices.connect(target="test") as connection:
                assert next(connection).type == "hello.completed"
                request_id = resolve(connection)(**params)
                event = next(connection)
                assert event.type == event_type
                assert event.request_id == request_id
    else:

        async def run():
            async with AsyncLimivia(backend=backend) as client:
                await client.devices.list()
                async with client.devices.connect(target="test") as connection:
                    await connection.recv()
                    request_id = await resolve(connection)(**params)
                    event = await connection.recv()
                    assert event.type == event_type
                    assert event.request_id == request_id

        asyncio.run(run())
    assert backend.transports[0].closed
    assert len(set(backend.loops + backend.transports[0].loops)) == 1


def test_timeout_late_reply_and_serial_order():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend, timeout=0.03) as client:
            async with client.devices.connect(target="test") as connection:
                await connection.recv()
                transport = backend.transports[-1]
                transport.silent_op = "state"
                first = await connection.state.retrieve()
                second = await connection.gpio.read(pin=13)
                await asyncio.sleep(0.005)
                assert [c["id"] for c in transport.commands] == [1, first]
                event = await connection.recv()
                assert event.request_id == first and event.type == "command.failed"
                assert event.error.code == "timeout" and event.error.may_have_executed
                # 迟到响应不能覆盖第二个请求，也不能发出第二个终态。
                await transport.emit({"v": 1, "id": first, "ok": True, "result": STATE})
                event = await connection.recv()
                assert event.request_id == second and event.type == "gpio.read.completed"
                await connection.close()
                remaining = [event async for event in connection]
                assert [e.type for e in remaining] == ["connection.closed"]

    asyncio.run(run())


def test_queue_capacity_and_local_validation_never_write():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend) as client:
            async with client.devices.connect(target="test") as connection:
                await connection.recv()
                with pytest.raises(ValidationError):
                    await connection.pwm.set(pin=13, frequency=0, duty=50)
                ids = [await connection.state.retrieve() for _ in range(8)]
                with pytest.raises(QueueFullError):
                    await connection.state.retrieve()
                assert len(backend.transports[0].commands) == 1
                await connection.close()
                events = [event async for event in connection]
                assert [e.request_id for e in events if e.type == "command.failed"] == ids
                assert all(
                    not e.error.may_have_executed for e in events if e.type == "command.failed"
                )

    asyncio.run(run())


def test_overflow_preserves_results_and_terminal_event():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend, event_queue_size=1) as client:
            async with client.devices.connect(target="test") as connection:
                # hello 留在队列中，让命令结果触发溢出。
                request_id = await connection.state.retrieve()
                await asyncio.wait_for(connection._wake.wait(), 1)
                for _ in range(100):
                    if connection._closed:
                        break
                    await asyncio.sleep(0.001)
                events = [event async for event in connection]
                assert [e.type for e in events] == [
                    "hello.completed",
                    "state.completed",
                    "connection.closed",
                ]
                assert events[1].request_id == request_id
                assert events[-1].error.code == "event_buffer_overflow"
            assert backend.transports[-1].closed

    asyncio.run(run())


def test_consumer_cancellation_and_single_consumer():
    async def run():
        async with AsyncLimivia(backend=FakeBackend()) as client:
            async with client.devices.connect(target="test") as connection:
                await connection.recv()
                waiting = asyncio.create_task(connection.recv())
                await asyncio.sleep(0)
                with pytest.raises(RuntimeError, match="消费者"):
                    await connection.recv()
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting
                request_id = await connection.state.retrieve()
                assert (await connection.recv()).request_id == request_id

    asyncio.run(run())


def test_disconnect_fails_inflight_and_queued_once():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend) as client:
            async with client.devices.connect(target="test") as connection:
                await connection.recv()
                backend.transports[-1].disconnect_op = "gpio.read"
                first = await connection.gpio.read(pin=13)
                second = await connection.outputs.stop()
                events = [event async for event in connection]
                assert [e.type for e in events] == [
                    "command.failed",
                    "command.failed",
                    "connection.closed",
                ]
                assert [e.request_id for e in events[:2]] == [first, second]
                assert events[0].error.may_have_executed
                assert not events[1].error.may_have_executed
            assert backend.transports[-1].closed
            async with client.devices.connect(target="test") as other:
                assert (await other.recv()).type == "hello.completed"

    asyncio.run(run())


@pytest.mark.parametrize("override", [{"protocol": 2}, {"board": "other"}, {"state": None}])
def test_bad_handshake_releases_device(override):
    async def run():
        backend = FakeBackend()
        backend.configure = lambda transport: transport.hello.update(override)
        async with AsyncLimivia(backend=backend) as client:
            with pytest.raises(DeviceConnectionError):
                async with client.devices.connect(target="test"):
                    pytest.fail("不应握手成功")
            assert backend.transports[-1].closed
            backend.configure = lambda transport: None
            async with client.devices.connect(target="test") as connection:
                assert (await connection.recv()).result.protocol == 1

    asyncio.run(run())


def test_connection_open_cancellation_releases_device():
    async def run():
        backend = FakeBackend()
        opening = asyncio.Event()

        def configure(transport):
            async def open_slow():
                opening.set()
                await asyncio.Event().wait()

            transport.open = open_slow
            transport.close_delay = 0.01

        backend.configure = configure
        async with AsyncLimivia(backend=backend) as client:
            manager = client.devices.connect(target="test")
            task = asyncio.create_task(manager.__aenter__())
            await opening.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert backend.transports[-1].closed
            assert client._active is None

    asyncio.run(run())


def test_malformed_and_future_events_are_observable():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend) as client:
            async with client.devices.connect(target="test") as connection:
                await connection.recv()
                transport = backend.transports[-1]
                await transport.queue.put(b"startup banner\n{bad json}\n")
                assert (await connection.recv()).type == "protocol.error"
                await transport.emit({"v": 1, "event": "future", "value": 42})
                event = await connection.recv()
                assert event.type == "unknown" and event.raw["value"] == 42
                await connection.state.retrieve()
                assert (await connection.recv()).type == "state.completed"

    asyncio.run(run())


def test_sync_thread_stops_after_exit():
    before = {t.ident for t in threading.enumerate() if t.name == "limivia-sync"}
    backend = FakeBackend()
    with Limivia(backend=backend) as client:
        with client.devices.connect(target="test") as connection:
            assert next(connection).result.name == HELLO["name"]
            connection.close()
            assert next(connection).type == "connection.closed"
            with pytest.raises(StopIteration):
                next(connection)
    assert {t.ident for t in threading.enumerate() if t.name == "limivia-sync"} == before


def test_client_cannot_cross_asyncio_loops():
    client = AsyncLimivia(backend=FakeBackend())
    asyncio.run(client.devices.list())
    with pytest.raises(DeviceConnectionError, match="事件循环"):
        asyncio.run(client.devices.list())


def test_client_close_cancels_opening_and_waits_for_cleanup():
    async def run():
        backend = FakeBackend()
        opening = asyncio.Event()

        def configure(transport):
            async def slow_open():
                opening.set()
                await asyncio.Event().wait()

            transport.open = slow_open
            transport.close_delay = 0.01

        backend.configure = configure
        client = AsyncLimivia(backend=backend)
        task = asyncio.create_task(client.devices.connect(target="test").__aenter__())
        await opening.wait()
        await client.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert backend.transports[-1].closed
        assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("limivia-")]

    asyncio.run(run())


def test_partial_write_timeout_closes_instead_of_writing_next_frame():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend, timeout=0.03) as client:
            async with client.devices.connect(target="test") as connection:
                await connection.recv()
                transport = backend.transports[-1]
                fragments = []

                async def stalled_write(data):
                    fragments.append(data[:5])
                    await asyncio.Event().wait()

                transport.write = stalled_write
                await connection.state.retrieve()
                await connection.outputs.stop()
                events = [event async for event in connection]
                assert [e.type for e in events] == [
                    "command.failed",
                    "command.failed",
                    "connection.closed",
                ]
                assert events[0].error.code == "write_timeout"
                assert events[0].error.may_have_executed
                assert not events[1].error.may_have_executed
                assert len(fragments) == 1
            assert transport.closed

    asyncio.run(run())


def test_scan_and_connection_ownership_and_recovery():
    async def run():
        backend = FakeBackend()
        started = asyncio.Event()
        release = asyncio.Event()
        original = backend.discover

        async def discover(kind):
            started.set()
            await release.wait()
            return await original(kind)

        backend.discover = discover
        async with AsyncLimivia(backend=backend) as client:
            scan = asyncio.create_task(client.devices.list())
            await started.wait()
            with pytest.raises(DeviceConnectionError):
                await client.devices.list()
            with pytest.raises(DeviceConnectionError):
                async with client.devices.connect(target="test"):
                    pass
            release.set()
            await scan
            async with client.devices.connect(target="test") as connection:
                with pytest.raises(DeviceConnectionError):
                    await client.devices.list()
                with pytest.raises(DeviceConnectionError):
                    async with client.devices.connect(target="test"):
                        pass
                assert (await connection.recv()).type == "hello.completed"
            assert (await client.devices.list())[0].id == "test"

    asyncio.run(run())
