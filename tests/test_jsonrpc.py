"""JSON-RPC契约、并发与只读聚合回归；真实报文另由捕获向量逐条覆盖。"""

import asyncio
import json
from pathlib import Path

import pytest

from limivia import AsyncLimivia, InvalidCommandError, Limivia, ProtocolError
from limivia.protocol import (
    MISSING_ID,
    LineReader,
    decode_message,
    encode_command,
    load_json,
    parse_command,
    parse_wire_command,
)
from tests.fakes import FakeBackend, FakeTransport, result
from tests.test_client import connect_test


@pytest.mark.parametrize("wire_id", ['中文-"', 9007199254740993, 1.25, 0, -1, None, MISSING_ID])
@pytest.mark.parametrize("positional", [False, True])
def test_ids_and_position_parameters(wire_id, positional):
    command = parse_command({"type": "state", "params": {"page": 0}})
    wire = encode_command(command, wire_id, session="s", seq=17, positional=positional)
    expected_params = (
        [{"session": "s", "seq": 17}, {"page": 0}]
        if positional
        else {
            "context": {"session": "s", "seq": 17},
            "args": {"page": 0},
        }
    )
    assert json.loads(wire)["params"] == expected_params
    decoded_id, decoded = parse_wire_command(wire.decode())
    assert decoded == command
    assert decoded_id is MISSING_ID if wire_id is MISSING_ID else decoded_id == wire_id
    assert ("id" in json.loads(wire)) == (wire_id is not MISSING_ID)


REQUESTS = json.loads((Path(__file__).parent / "vectors/jsonrpc.json").read_text())


@pytest.mark.parametrize("case", REQUESTS, ids=lambda c: c["name"])
def test_independent_firmware_request_vectors(case):
    text = case["wire"].replace('"$SEQ"', "7").replace("$SESSION", "session")
    if case["name"] in {"large_numeric_id", "null_id", "utf8_string_id"}:
        wire_id, command = parse_wire_command(text)
        assert wire_id == case["ids"][0]
        assert command.type in {"state", "session.ping"}
    else:
        with pytest.raises(ProtocolError):
            parse_wire_command(text)


@pytest.mark.parametrize(
    "text",
    [
        '{"x":1,"x":2}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":01}',
        '{"x":"\\u0000"}',
        '{"x":"\\ud800"}',
        "[" * 17 + "0" + "]" * 17,
    ],
)
def test_strict_json(text):
    with pytest.raises(ValueError):
        load_json(text)


def test_line_timeout_discards_until_next_boundary():
    reader = LineReader()
    reader.feed(b'{"partial":')
    assert reader.started is not None
    assert reader.expire(reader.started + 3.01)
    assert not reader.buffer
    assert reader.feed(b"1}\n{}\n") == ["{}"]


async def collect(connection, ids):
    remaining = set(ids)
    events = {}
    async with asyncio.timeout(2):
        while remaining:
            event = await connection.recv()
            rid = getattr(event, "request_id", None)
            if rid in remaining and event.type != "command.accepted":
                events[rid] = event
                remaining.remove(rid)
    return events


def test_batch_out_of_order_and_three_independent_counters():
    async def case(c, t):
        await result(c, await c.control.acquire())
        # Internal queries consume wire IDs and seq but never public request IDs.
        await c._core._rpc("session.ping", {})
        ids = await c.batch(
            [{"type": "state", "params": {}}, {"type": "system.time", "params": {}}]
        )
        events = await collect(c, ids)
        assert events[ids[0]].type == "state.completed"
        assert events[ids[1]].type == "job.completed"
        raw_batch = next(frame for frame in t.frames if isinstance(frame, list))
        assert ids[0] != raw_batch[0]["id"]
        assert raw_batch[0]["id"] != raw_batch[0]["params"][0]["seq"]
        seqs = [x["context"]["seq"] for x in t.commands if x["op"] != "hello"]
        assert seqs == sorted(set(seqs))
        assert sum(x["op"] == "system.time" for x in t.commands) == 1

    asyncio.run(connect_test(case))


def test_batch_limits_are_checked_before_io():
    async def case(c, t):
        before = len(t.frames)
        for commands in [
            [],
            [{"type": "state", "params": {}}] * 9,
            [{"type": "hello", "params": {}}],
            [{"type": "storage.record", "params": {"name": "a", "value": "x" * 1000}}],
        ]:
            with pytest.raises(InvalidCommandError):
                await c.batch(commands)
        assert len(t.frames) == before

    asyncio.run(connect_test(case))


@pytest.mark.parametrize("wire_id", [None, "unrelated", 9007199254740993])
def test_uncorrelated_error_is_not_assigned_to_a_pending_request(wire_id):
    async def case(c, t):
        await c.recv()
        t.silent_op = "state"
        rid = await c.state.retrieve()
        await asyncio.sleep(0.01)
        await t.emit_wire(
            {
                "jsonrpc": "2.0",
                "id": wire_id,
                "error": {
                    "code": -32700,
                    "message": "Parse error",
                    "data": {"reason": "parse_error"},
                },
            }
        )
        event = await c.recv()
        assert event.type == "rpc.error" and event.error.code == -32700
        assert not hasattr(event, "request_id")
        assert rid in c._core._pending

    asyncio.run(connect_test(case))


def test_same_nonce_preserves_control_and_new_nonce_revokes_it():
    async def case(c, t):
        await result(c, await c.control.acquire())
        token = c._core._control
        await result(c, await c.hello())
        assert c._core._control == token
        await result(c, await c.hello(client_nonce="b" * 32))
        assert c._core._control is None
        assert [x["context"]["client_nonce"] for x in t.commands if x["op"] == "hello"][
            -1
        ] == "b" * 32
        await result(c, await c.state.retrieve())
        assert t.commands[-1]["context"]["seq"] == 1

    asyncio.run(connect_test(case))


def test_seq_exhaustion_rotates_without_replaying_or_reacquiring():
    async def case(c, t):
        await result(c, await c.control.acquire())
        before = t.nonce
        c._core._send_sequence = 2147483647
        event = await result(c, await c.state.retrieve())
        assert event.type == "state.completed"
        assert t.nonce != before and c._core._control is None
        assert t.commands[-1]["context"]["seq"] == 1
        assert sum(x["op"] == "state" for x in t.commands) == 1
        assert sum(x["op"] == "control.acquire" for x in t.commands) == 1

    asyncio.run(connect_test(case))


def test_heartbeat_has_reserved_slot_while_query_is_delayed():
    async def case(c, t):
        t.silent_op = "job.get"
        c._core._heartbeat_interval = 0.01
        rid = await c.system.time()
        await result(c, rid, accepted=True)
        await asyncio.sleep(0.06)
        assert any(x["op"] == "session.ping" for x in t.commands)
        assert not c._core._closed

    asyncio.run(connect_test(case, timeout=0.2))


def test_late_batch_acquire_cannot_rebind_after_stop():
    class DelayedBatch(FakeTransport):
        async def emit_wire(self, wire):
            if isinstance(wire, list):
                self.delayed = wire
            else:
                await super().emit_wire(wire)

    async def run():
        t = DelayedBatch()
        async with AsyncLimivia(backend=FakeBackend(t), job_poll_interval=0.01) as client:
            async with client.devices.connect(kind="usb", target="test") as c:
                c = c.raw
                ids = await c.batch(
                    [{"type": "control.acquire", "params": {}}, {"type": "state", "params": {}}]
                )
                await asyncio.sleep(0.01)
                stopped = await result(c, await c.outputs.stop())
                assert stopped.type == "job.completed"
                await FakeTransport.emit_wire(t, t.delayed)
                events = await collect(c, ids)
                assert events[ids[0]].type == "command.completed"
                assert c._core._control is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value", [("cleanup_faults", 1), ("persist_error", 1), ("autostart_inhibited", False)]
)
def test_stop_requires_cleanup_and_persistence_confirmation(field, value):
    async def case(c, t):
        t.hold_jobs = True
        rid = await c.outputs.stop()
        accepted = await result(c, rid, accepted=True)
        t.jobs[accepted.job.job_id]["result"][field] = value
        t.hold_jobs = False
        terminal = await result(c, rid)
        assert terminal.type == "command.failed" and terminal.error.reason == "stop_unconfirmed"

    asyncio.run(connect_test(case))


def test_discovery_reuses_session_and_keeps_unknown_profile():
    async def run():
        backend = FakeBackend()
        t = backend.connection
        t.hello["profile"] = "future-profile"
        t.hello["capability_pages"] = 2
        captured = json.loads((Path(__file__).parent / "vectors/jsonrpc-captured.json").read_text())
        real_pages = {
            c["message"]["result"]["value"]["page"]: c["message"]["result"]["value"]
            for c in captured["cases"]
            if c["profile"] == "bus" and c["method"] == "capabilities" and "result" in c["message"]
        }

        def pages(response):
            command = t.commands[-1]
            if command["op"] == "capabilities":
                index = command["params"]["page"]
                response["result"] = {**real_pages[index], "pages": 2}
            return response

        t.bad_response = pages
        async with AsyncLimivia(backend=backend) as client:
            async with client.devices.connect(kind="usb", target="test") as c:
                c = c.raw
                first = await result(c, await c.discover())
                assert first.type == "discovery.completed"
                assert first.result.identity.profile == "future-profile"
                assert all(p.digital and p.adc1 for p in first.result.pins if p.pin in (0, 1, 3, 4))
                assert any(r.kind == "uart" and r.available for r in first.result.resources)
                assert len(first.result.raw_pages) == 2
                first.result.pins.clear()
                second = await result(c, await c.discover())
                assert second.result.pins
                assert sum(x["op"] == "capabilities" for x in t.commands) == 2
                assert not any(x["op"] in ("outputs.stop", "control.acquire") for x in t.commands)
                assert sum(x["op"] == "hello" for x in t.commands) == 1
                await result(c, await c.hello(client_nonce="c" * 32))
                await result(c, await c.discover())
                assert sum(x["op"] == "capabilities" for x in t.commands) == 4

    asyncio.run(run())


def test_state_snapshot_revision_zero_must_still_be_consistent_and_retries_bounded():
    async def case(c, t):
        attempts = 0

        def changing(response):
            nonlocal attempts
            if t.commands[-1]["op"] == "state":
                page = t.commands[-1]["params"].get("page", 0)
                if page == 0:
                    attempts += 1
                response["result"]["revision"] = 0 if page == 0 else 1
            return response

        t.bad_response = changing
        event = await result(c, await c.state.snapshot())
        assert event.type == "command.failed" and event.error.reason == "snapshot_expired"
        assert attempts == 3
        t.bad_response = None
        event = await result(c, await c.state.snapshot())
        assert event.type == "state.snapshot.completed" and len(event.result.pages) == 6

    asyncio.run(connect_test(case))


def test_notification_gap_preserves_notice_and_state_recovers():
    async def case(c, t):
        await c.recv()
        await t.emit_wire(
            {
                "jsonrpc": "2.0",
                "method": "state.changed",
                "params": {
                    "context": {"boot_id": c.identity.boot_id, "session": c._core._session},
                    "args": {
                        "event_sequence": 4,
                        "dropped": 2,
                        "revision": 3,
                        "resource": 1,
                        "instance": 1,
                        "job_id": 0,
                        "sequence": 0,
                    },
                },
            }
        )
        gap, notice = await c.recv(), await c.recv()
        assert gap.type == "notifications.gap" and gap.expected == 1 and gap.received == 4
        assert gap.dropped == 3
        assert notice.type == "state.changed" and notice.dropped == 2
        assert (await result(c, await c.state.snapshot())).type == "state.snapshot.completed"

    asyncio.run(connect_test(case))


def test_sync_batch_discovery_snapshot_and_identity():
    backend = FakeBackend()
    with Limivia(backend=backend) as client:
        with client.devices.connect(kind="usb", target="test") as c:
            c = c.raw
            assert c.identity.contract == "limivia-v3-jsonrpc2-r2"
            for submit, kind in [
                (c.discover, "discovery.completed"),
                (c.state.snapshot, "state.snapshot.completed"),
            ]:
                rid = submit()
                event = next(e for e in c if getattr(e, "request_id", None) == rid)
                assert event.type == kind
            ids = c.batch([{"type": "state", "params": {}}, {"type": "diagnostics", "params": {}}])
            got = set()
            for event in c:
                if getattr(event, "request_id", None) in ids:
                    got.add(event.request_id)
                if got == set(ids):
                    break
            assert got == set(ids)


def test_window_reserves_stop_without_sending_an_over_window_batch():
    async def case(c, t):
        t.silent_op = "diagnostics"
        await c.diagnostics.retrieve()
        await asyncio.sleep(0.01)
        t.silent_op = None
        # Higher-priority replies do not prove an older ordinary frame was admitted.
        for _ in range(59):
            await c._core._rpc("session.ping", {})
        before = len(t.frames)
        ids = await c.batch([{"type": "state", "params": {}}] * 8)
        rejected = await collect(c, ids)
        assert all(
            e.type == "command.failed"
            and e.error.reason == "sequence_window_blocked"
            and not e.error.may_have_executed
            for e in rejected.values()
        )
        assert len(t.frames) == before
        assert (await result(c, await c.outputs.stop())).type == "job.completed"
        assert not c._core._closed
        seqs = [x["context"]["seq"] for x in t.commands if x["op"] != "hello"]
        assert max(seqs) - min(seqs) < 64

    asyncio.run(connect_test(case, timeout=1))


def test_response_capacity_preserves_numeric_error_and_unknown_effect():
    frame = {
        "jsonrpc": "2.0",
        "id": "capacity",
        "error": {
            "code": 1001,
            "message": "Capacity exceeded",
            "data": {
                "reason": "response_capacity",
                "context": {"boot_id": "b", "session": "s"},
                "external_effect_possible": True,
                "job_id": 71,
                "detail": {"driver": 4},
            },
        },
    }
    event = decode_message(frame, "resource.open", request_id=5)
    assert event.type == "command.failed" and event.request_id == 5
    assert event.error.code == 1001 and event.error.reason == "response_capacity"
    assert event.error.external_effect_possible and event.error.may_have_executed
    assert event.job_id == 71 and event.error.data["detail"] == {"driver": 4}


def test_network_messages_allow_json_whitespace_without_using_lf_framing():
    from limivia.network_transports import _frame

    assert load_json(_frame('{\n"jsonrpc":"2.0"\n}').decode()) == {"jsonrpc": "2.0"}
    with pytest.raises(ValueError):
        load_json(_frame("{}\n{}").decode())


def test_stop_job_poll_is_not_blocked_by_an_unrelated_slow_job_query():
    async def case(c, t):
        original = t.handle

        async def selectively_silent(wire):
            if wire["method"] == "job.get" and wire["params"][1]["job_id"] == 1:
                return
            await original(wire)

        t.handle = selectively_silent
        rid = await c.system.time()
        await result(c, rid, accepted=True)
        await asyncio.sleep(0.01)
        started = asyncio.get_running_loop().time()
        event = await result(c, await c.outputs.stop())
        assert event.type == "job.completed"
        assert asyncio.get_running_loop().time() - started < 0.15

    asyncio.run(connect_test(case, timeout=0.5))


def test_gpio_group_read_facade_encodes_real_firmware_resource_objects():
    from limivia.resources import Resources

    captured = []
    Resources(lambda command: captured.append(command) or 1).gpio.group_read(
        resources=[{"resource": 13, "instance": 13}, {"resource": 21, "instance": 21}]
    )
    assert captured == [
        {
            "type": "gpio.group.read",
            "params": {
                "resources": [{"resource": 13, "instance": 13}, {"resource": 21, "instance": 21}],
            },
        }
    ]
    parse_command(captured[0])
    with pytest.raises(InvalidCommandError):
        parse_command({"type": "gpio.group.read", "params": {"resources": [13, 21]}})


def test_resource_read_preserves_current_control_for_firmware_kind_policy():
    async def case(c, t):
        await result(c, await c.control.acquire())
        original = t.handle

        async def require_control_for_read(wire):
            if wire["method"] == "resource.call" and wire["params"]["args"]["action"] == "read":
                assert wire["params"]["context"]["control"] == "control-test"
            await original(wire)

        t.handle = require_control_for_read
        event = await result(
            c, await c.resource.call(resource=1, instance=1, action="read", args={})
        )
        assert event.type == "job.completed"

    asyncio.run(connect_test(case))


def test_discovery_cache_key_checks_build_and_profile_independently_of_session():
    async def case(c, t):
        first = await result(c, await c.discover())
        assert first.type == "discovery.completed"
        count = sum(x["op"] == "capabilities" for x in t.commands)
        c._core.identity = c.identity.model_copy(
            update={"profile": "new-profile", "build_id": "b" * 64}
        )
        second = await result(c, await c.discover())
        assert second.result.identity.profile == "new-profile"
        assert sum(x["op"] == "capabilities" for x in t.commands) == count * 2

    asyncio.run(connect_test(case))


def test_stop_query_and_heartbeat_keep_reserved_slots_with_saturated_queries():
    async def case(c, t):
        t.silent_op = "state"
        c._core._heartbeat_interval = 0.01
        for _ in range(3):
            await c.state.retrieve()
        await asyncio.sleep(0.02)
        started = asyncio.get_running_loop().time()
        event = await result(c, await c.outputs.stop())
        assert event.type == "job.completed"
        assert asyncio.get_running_loop().time() - started < 0.15
        await asyncio.sleep(0.02)
        assert any(x["op"] == "session.ping" for x in t.commands)

    asyncio.run(connect_test(case, timeout=0.5))


def test_lost_ping_reply_does_not_pin_window_during_confirmed_job_traffic():
    async def case(c, t):
        c._core._heartbeat_interval = 0.01
        original = t.emit_wire
        lost = []

        async def drop_one_ping(wire):
            if isinstance(wire, dict) and "id" in wire:
                command = next((r for r in t.commands if r["id"] == wire["id"]), None)
                if command and command["op"] == "session.ping" and not lost:
                    lost.append(wire["id"])
                    return
            await original(wire)

        t.emit_wire = drop_one_ping
        for _ in range(70):
            assert (await result(c, await c.system.time())).type == "job.completed"
        assert lost and not c._core._closed
        assert lost[0] not in c._core._sent_sequences
        assert (await result(c, await c.outputs.stop())).type == "job.completed"

    asyncio.run(connect_test(case, timeout=0.5))


def test_query_and_write_share_the_firmware_ordinary_admission_slot():
    from tests.fakes import STATE

    async def case(c, t):
        await result(c, await c.control.acquire())
        t.silent_op = "state"
        await c.state.retrieve()
        await asyncio.sleep(0.01)
        state_wire = t.commands[-1]["id"]
        resource = await c.resource.open(kind="gpio", pins={"pin": 13}, config={})
        await asyncio.sleep(0.01)
        assert not any(r["op"] == "resource.open" for r in t.commands)
        assert (await result(c, await c.session.ping())).type == "command.completed"
        t.silent_op = None
        await t.emit({"id": state_wire, "ok": True, "result": STATE})
        assert (await result(c, resource)).type == "job.completed"

    asyncio.run(connect_test(case))


def test_late_internal_error_does_not_leak_after_request_retirement():
    async def case(c, t):
        await c.recv()
        await c._core._rpc("session.ping", {})
        wire_id = t.commands[-1]["id"]
        await t.emit_wire(
            {
                "jsonrpc": "2.0",
                "id": wire_id,
                "error": {
                    "code": 1000,
                    "message": "Operation rejected",
                    "data": {"reason": "invalid_session"},
                },
            }
        )
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.02):
                await c.recv()

    asyncio.run(connect_test(case))


def test_readonly_batch_rotates_exhausted_seq_before_actual_send():
    async def case(c, t):
        c._core._send_sequence = 2147483647
        ids = await c.batch(
            [{"type": "state", "params": {}}, {"type": "diagnostics", "params": {}}]
        )
        events = await collect(c, ids)
        assert [events[rid].type for rid in ids] == ["state.completed", "diagnostics.completed"]
        frame = next(frame for frame in t.frames if isinstance(frame, list))
        assert [
            (r["params"][0] if isinstance(r["params"], list) else r["params"]["context"])["seq"]
            for r in frame
        ] == [1, 2]
        assert sum(r["op"] == "hello" for r in t.commands) == 2

    asyncio.run(connect_test(case))


def test_sample_loss_does_not_imply_notification_loss():
    async def case(c, t):
        await c.recv()
        for seq, dropped in [(1, 0), (2, 5), (3, 5), (4, 8)]:
            await t.emit(
                {
                    "event": "data.available",
                    "event_sequence": seq,
                    "revision": 1,
                    "resource": 1,
                    "instance": 1,
                    "job_id": 0,
                    "sequence": seq,
                    "dropped": dropped,
                }
            )
            event = await c.recv()
            assert event.type == "data.available"
            assert event.event_sequence == seq and event.dropped == dropped
        # A real gap still produces one recovery hint; its count describes messages, not samples.
        await t.emit(
            {
                "event": "data.available",
                "event_sequence": 7,
                "revision": 1,
                "resource": 1,
                "instance": 2,
                "job_id": 0,
                "sequence": 1,
                "dropped": 0,
            }
        )
        gap, event = await c.recv(), await c.recv()
        assert gap.type == "notifications.gap" and gap.dropped == 2
        assert event.type == "data.available" and event.instance == 2

    asyncio.run(connect_test(case))
