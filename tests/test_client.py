import asyncio
import threading

import pytest

from limivia import AsyncLimivia, DeviceConnectionError, Limivia, QueueFullError
from limivia.types import JobCompletedEvent
from tests.fakes import FakeBackend, result


def run(coro):
    return asyncio.run(coro)


async def connect_test(case, **kwargs):
    backend = FakeBackend()
    async with AsyncLimivia(backend=backend, job_poll_interval=0.01, **kwargs) as client:
        async with client.devices.connect(kind="usb", target="test") as connection:
            await case(connection.raw, backend.connection)
    assert backend.connection.closed


def test_handshake_and_all_common_typed_responses():
    async def case(c, t):
        assert (await c.recv()).type == "hello.completed"
        for request, kind in [
            (await c.state.retrieve(page=1), "state.completed"),
            (await c.capabilities.retrieve(page=0), "capabilities.completed"),
            (await c.diagnostics.retrieve(), "diagnostics.completed"),
        ]:
            event = await result(c, request)
            assert event.type == kind

    run(connect_test(case))


def test_job_accepted_and_terminal_are_distinct_and_internal_queries_hidden():
    async def case(c, t):
        await result(c, await c.control.acquire())
        request = await c.resource.open(kind="uart", pins={"tx": 20, "rx": 21}, config={})
        accepted = await result(c, request, accepted=True)
        assert accepted.type == "command.accepted"
        terminal = await result(c, request)
        assert isinstance(terminal, JobCompletedEvent)
        assert terminal.job.job_id == accepted.job.job_id and terminal.request_id == request
        assert any(x["op"] == "job.get" for x in t.commands)
        resource = await result(c, await c.resource.get(resource=terminal.job.resource))
        assert resource.type == "resource.get.completed" and resource.result.kind == "uart"

    run(connect_test(case))


@pytest.mark.parametrize("state,type_", [("failed", "job.failed"), ("cancelled", "job.cancelled")])
def test_device_job_failure_and_cancellation(state, type_):
    async def case(c, t):
        t.job_state = state
        event = await result(c, await c.system.time())
        assert event.type == type_ and event.op == "system.time"

    run(connect_test(case))


def test_expired_result_is_not_success():
    async def case(c, t):
        t.result_expired = True
        event = await result(c, await c.system.time())
        assert event.type == "command.failed" and event.error.reason == "result_expired"

    run(connect_test(case))


def test_job_timeout_preserves_id_without_replaying_command():
    async def case(c, t):
        t.hold_jobs = True
        event = await result(c, await c.system.time())
        assert (
            event.type == "command.failed"
            and event.error.reason == "result_unknown"
            and event.job_id
        )
        assert len([x for x in t.commands if x["op"] == "system.time"]) == 1

    run(connect_test(case, job_timeout=0.04))


def test_stop_bypasses_eight_jobs_and_revokes_control():
    async def case(c, t):
        await result(c, await c.control.acquire())
        t.hold_jobs = True
        ids = [await c.system.time() for _ in range(8)]
        with pytest.raises(QueueFullError):
            await c.system.time()
        stop = await c.outputs.stop()
        ack = await result(c, stop, accepted=True)
        assert ack.type == "command.accepted" and c._core._control is None
        t.hold_jobs = False
        assert (await result(c, stop)).type == "job.completed"
        assert ids

    run(connect_test(case))


def test_payload_is_owned_after_submit():
    async def case(c, t):
        params = {"resource": 1, "action": "write", "args": {"data": b"abc"}}
        request = await c.send({"type": "resource.call", "params": params})
        params["args"]["data"] = b"def"
        await result(c, request)
        assert (
            next(x for x in t.commands if x["op"] == "resource.call")["params"]["args"]["data"]
            == "YWJj"
        )

    run(connect_test(case))


def test_ordinary_timeout_is_not_retried_and_next_read_can_recover():
    async def case(c, t):
        t.silent_op = "state"
        event = await result(c, await c.state.retrieve())
        assert event.type == "command.failed" and event.error.may_have_executed
        assert sum(x["op"] == "state" for x in t.commands) == 1
        t.silent_op = None
        assert (await result(c, await c.state.retrieve())).type == "state.completed"

    run(connect_test(case, timeout=0.03))


@pytest.mark.parametrize(
    "field,value", [("protocol", 2), ("board", "other"), ("build_id", "short")]
)
def test_incompatible_handshake_closes_without_output(field, value):
    async def case():
        backend = FakeBackend()
        backend.connection.hello[field] = value
        async with AsyncLimivia(backend=backend, connect_timeout=0.5) as client:
            with pytest.raises(DeviceConnectionError):
                async with client.devices.connect(kind="usb", target="test"):
                    pass
        assert backend.connection.closed
        assert [x["op"] for x in backend.connection.commands] == ["hello"]

    run(case())


def test_wrong_expected_mac_never_sends_mutation():
    async def case():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend) as client:
            with pytest.raises(DeviceConnectionError):
                async with client.devices.connect(
                    kind="usb", target="test", expected_device_id="wrong"
                ):
                    pass
        assert len(backend.connection.commands) == 1

    run(case())


def test_changed_boot_terminates_known_requests():
    async def case(c, t):
        t.bad_response = lambda p: {**p, "boot_id": "new"}
        event = await result(c, await c.state.retrieve())
        assert event.type == "command.failed" and event.error.reason == "boot_changed"

    run(connect_test(case))


def test_old_session_notifications_and_duplicate_responses_are_ignored():
    async def case(c, t):
        await c.recv()
        notice = {"event": "data.available", "boot_id": t.hello["boot_id"], "session": "old"}
        await t.emit(notice)
        request = await c.state.retrieve()
        assert (await result(c, request)).type == "state.completed"
        await t.emit({"id": t.commands[-1]["id"], "ok": True, "result": {}})
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.03):
                await c.recv()

    run(connect_test(case))


def test_raw_overflow_is_explicit_and_does_not_close_business_connection():
    from limivia import SubscriptionOverflowError
    async def case():
        backend = FakeBackend()
        async with AsyncLimivia(backend=backend, event_queue_size=1) as client:
            async with client.devices.connect(kind="usb", target="test") as board:
                raw = board.raw
                await raw.state.retrieve()
                await asyncio.sleep(0.03)
                with pytest.raises(SubscriptionOverflowError):
                    await raw.recv()
                assert (await board.state.retrieve()).page == 0
                assert not board._core._closed
    run(case())


def test_receive_has_one_consumer_and_cancellation_does_not_lose_future_events():
    async def case(c, t):
        await c.recv()
        task = asyncio.create_task(c.recv())
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            await c.recv()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await result(c, await c.state.retrieve())).type == "state.completed"

    run(connect_test(case))


def test_partial_write_closes_instead_of_reusing_stream():
    async def case(c, t):
        t.partial = True
        event = await result(c, await c.state.retrieve())
        assert event.type == "command.failed"
        await asyncio.sleep(0.01)
        assert t.closed

    run(connect_test(case))


def test_close_does_not_claim_to_cancel_device_jobs():
    async def case(c, t):
        t.hold_jobs = True
        request = await c.system.time()
        await result(c, request, accepted=True)
        await c.close()
        events = [e async for e in c]
        event = next(e for e in events if getattr(e, "request_id", None) == request)
        assert (
            event.type == "command.failed"
            and event.error.reason == "result_unknown"
            and event.job_id
        )
        assert not any(x["op"] == "outputs.stop" for x in t.commands)

    run(connect_test(case))


def test_sync_facade_uses_one_continuous_loop_and_thread_exits():
    backend = FakeBackend()
    before = {t.ident for t in threading.enumerate()}
    with Limivia(backend=backend, job_poll_interval=0.01) as client:
        with client.devices.connect(kind="usb", target="test") as c:
            c = c.raw
            rid = c.system.time()
            for event in c:
                if getattr(event, "request_id", None) == rid and event.type == "job.completed":
                    break
    assert backend.connection.closed and len({id(loop) for loop in backend.connection.loops}) == 1
    assert not any(
        t.name == "limivia-sync" and t.ident not in before for t in threading.enumerate()
    )


def test_stop_does_not_rebind_queued_old_control_to_a_new_token():
    async def case(c, t):
        await result(c, await c.control.acquire())
        t.silent_op = "state"
        first = await c.state.retrieve()
        await asyncio.sleep(0.01)
        old = await c.resource.call(resource=1, action="write", args={"data": b"a"})
        stop = await c.outputs.stop()
        observed = {}
        while old not in observed or stop not in observed:
            event = await c.recv()
            rid = getattr(event, "request_id", None)
            if rid in (old, stop):
                observed[rid] = event
        failure = observed[old]
        assert failure.type == "command.failed" and failure.error.reason == "control_revoked"
        assert not failure.error.may_have_executed
        assert not any(x["op"] == "resource.call" for x in t.commands)
        assert first

    run(connect_test(case, timeout=0.05))


def test_close_during_handshake_releases_transport():
    async def case():
        backend = FakeBackend()
        backend.connection.silent_op = "hello"
        client = AsyncLimivia(backend=backend, connect_timeout=0.1)
        task = asyncio.create_task(client.devices.connect(kind="usb", target="test").__aenter__())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.close()
        assert backend.connection.closed

    run(case())


def test_device_control_required_clears_stale_local_token():
    async def case(c, t):
        await result(c, await c.control.acquire())
        t.bad_response = lambda p: {
            "id": p["id"],
            "ok": False,
            "error": {"code": "control_required"},
        }
        event = await result(
            c, await c.resource.call(resource=1, action="write", args={"data": b"a"})
        )
        assert event.type == "command.failed" and c._core._control is None

    run(connect_test(case))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout": float("nan")},
        {"job_timeout": float("inf")},
        {"job_poll_interval": float("nan")},
        {"event_queue_size": True},
    ],
)
def test_client_rejects_unbounded_or_mistyped_limits(kwargs):
    with pytest.raises(ValueError):
        AsyncLimivia(**kwargs)


def test_internal_heartbeat_renews_without_public_ping_results():
    async def case(c, t):
        await c.recv()
        c._core._heartbeat_interval = 0.01
        await asyncio.sleep(0.05)
        assert any(x["op"] == "session.ping" for x in t.commands)
        assert not c._core._events
        ids = [x["id"] for x in t.commands]
        assert ids == sorted(set(ids))

    run(connect_test(case))


def test_heartbeat_failure_terminates_without_retry_or_public_ping_result():
    async def case(c, t):
        await c.recv()
        c._core._heartbeat_interval = 0.01
        t.silent_op = "session.ping"
        await asyncio.sleep(0.06)
        events = [e async for e in c]
        assert len(events) == 1 and events[0].type == "connection.closed"
        assert events[0].error.reason == "heartbeat_failed"
        assert sum(x["op"] == "session.ping" for x in t.commands) == 1

    run(connect_test(case, timeout=0.02))


def test_public_job_get_describes_existing_job_without_recursive_tracking():
    async def case(c, t):
        t.jobs[99] = {"job_id": 99, "resource": 0, "state": "accepted", "action": "time"}
        t.hold_jobs = True
        event = await result(c, await c.job.get(job_id=99))
        assert event.type == "command.completed" and event.result["state"] == "accepted"
        await asyncio.sleep(0.02)
        assert not c._core._jobs and sum(x["op"] == "job.get" for x in t.commands) == 1

    run(connect_test(case))


def test_job_deadline_does_not_wait_for_or_cancel_a_longer_query_rpc():
    async def case(c, t):
        t.silent_op = "job.get"
        started = asyncio.get_running_loop().time()
        rid = await c.system.time()
        unknown = await result(c, rid)
        assert unknown.type == "command.failed" and unknown.error.reason == "result_unknown"
        assert asyncio.get_running_loop().time() - started < 0.15
        query = next(x for x in t.commands if x["op"] == "job.get")
        t.silent_op = None
        status = {**t.jobs[unknown.job_id], "state": "completed"}
        await t.emit({"id": query["id"], "ok": True, "result": status})
        explicit = await result(c, await c.job.get(job_id=unknown.job_id))
        assert explicit.type == "command.completed" and explicit.result["state"] == "completed"
        assert sum(x["op"] == "system.time" for x in t.commands) == 1

    run(connect_test(case, timeout=0.5, job_timeout=0.03))
