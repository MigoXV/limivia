import json
from pathlib import Path
from typing import cast

import pytest

from limivia import InvalidCommandError, ProtocolError
from limivia._schema import OPERATIONS, REQUIRED
from limivia.protocol import (
    LineReader,
    decode_message,
    encode_command,
    event_to_wire,
    parse_command,
    parse_wire_command,
)
from limivia.resources import Resources
from limivia.types import BinaryResult, Operation


def params_for(op):
    values = {
        "kind": "gpio",
        "pins": {"pin": 13},
        "config": {},
        "resource": 1,
        "parent": 1,
        "action": "status",
        "args": {},
        "job_id": 1,
        "buffer_id": 1,
        "upload_id": 1,
        "flow_id": 1,
        "resources": [{"resource": 1}]
        if op == "gpio.group.read"
        else [{"resource": 1, "level": 1}]
        if op == "gpio.group.write"
        else [{"resource": 1, "data": "AA=="}],
        "size": 1,
        "offset": 0,
        "data": "AA==",
        "length": 1,
        "confirm": "erase_littlefs",
        "name": "test.bin",
        "sha256": "0" * 64,
        "value": {},
        "limit_bytes": 4096,
        "board": "luatos-esp32c3-usb",
        "protocol": 3,
        "profile": "bus",
        "ssid": "test",
        "password": "",
        "enable": True,
        "uri": "mqtt://localhost",
        "topic": "test",
        "mac": "ff:ff:ff:ff:ff:ff",
        "mode": "light",
        "duration_ms": 100,
        "topics": ["job"],
    }
    result = {key: values[key] for key in REQUIRED.get(op, [])}
    if op in ("mqtt.publish", "espnow.send"):
        result["data"] = "AA=="
    return result


@pytest.mark.parametrize("op", list(OPERATIONS))
def test_all_v3_operations_roundtrip(op):
    command = parse_command({"type": op, "params": params_for(op)})
    data = encode_command(command, 1, session="session", control="control")
    rid, decoded = parse_wire_command(data.decode())
    assert rid == 1 and decoded == command and json.loads(data)["jsonrpc"] == "2.0"


@pytest.mark.parametrize("op", list(OPERATIONS))
def test_all_namespace_methods_route_to_the_same_operation(op):
    if op == "hello":
        return
    captured = []
    api = Resources(lambda command: captured.append(command) or 42)
    parts = op.split(".")
    namespace = parts[0] if parts[0] != "event" else "events"
    method = "_".join(parts[1:]) if len(parts) > 1 else "retrieve"
    method_params = params_for(op)
    if op == "gpio.group.read":
        method_params = {"resources": [1]}
    assert getattr(getattr(api, namespace), method)(**method_params) == 42
    assert captured == [{"type": op, "params": params_for(op)}]


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "gpio.set", "params": {}},
        {"type": "state", "params": {"oops": 1}},
        {"type": "resource.open", "params": {"kind": "gpio", "pins": {"pin": True}, "config": {}}},
        {"type": "buffer.write", "params": {"buffer_id": 1, "offset": 0, "data": "AB=="}},
        {"type": "buffer.delete", "params": {"buffer_id": True}},
        {
            "type": "resource.call",
            "params": {"resource": 1, "action": "write", "args": {"data": "AA==", "buffer_id": 1}},
        },
        {
            "type": "resource.call",
            "params": {"resource": 1, "action": "read", "args": {"timeout_ms": 1001}},
        },
        {"type": "mqtt.publish", "params": {"topic": "test", "data": "AA==", "json": {}}},
        {"type": "storage.record", "params": {"name": "a", "value": float("nan")}},
        {"type": "state", "params": {}, "unknown": True},
    ],
)
def test_invalid_commands_are_rejected_before_io(raw):
    with pytest.raises(InvalidCommandError):
        parse_command(raw)


@pytest.mark.parametrize(
    "frame",
    [
        "{}\n",
        '{"v":2,"id":1,"op":"hello","params":{}}\n',
        '{"v":3,"v":3,"id":1,"op":"hello","params":{}}\n',
        '{"v":3,"id":true,"op":"hello","params":{}}\n',
        '{"v":3,"id":1,"op":"hello","params":{}}',
        '{"v":3,"id":1,"op":"hello","params":{}}\n{}\n',
        '{"v":3,"id":1,"op":"hello","params":{},"bad":1}\n',
    ],
)
def test_invalid_wire_command(frame):
    with pytest.raises(ProtocolError):
        parse_wire_command(frame)


def test_binary_conversion_does_not_invent_transaction_chunking():
    command = parse_command(
        {
            "type": "resource.call",
            "params": {"resource": 1, "action": "write", "args": {"data": b"abc\x00\xff"}},
        }
    )
    assert command.params["args"]["data"] == "YWJjAP8="
    assert BinaryResult(length=5, data=command.params["args"]["data"]).to_bytes() == b"abc\x00\xff"
    command.params["args"]["data"] = "A" * 1600
    with pytest.raises(InvalidCommandError, match="1024"):
        encode_command(command, 1)
    with pytest.raises(ValueError):
        BinaryResult(length=2, data="AA==").to_bytes()


def test_utf8_fragments_overflow_and_recovery():
    reader = LineReader()
    encoded = '{"中文":1}\n'.encode()
    assert reader.feed(encoded[:3]) == []
    assert reader.feed(encoded[3:]) == ['{"中文":1}']
    results = reader.feed(b"x" * 8193 + b"\n{}\n")
    assert isinstance(results[0], ProtocolError) and results[1] == "{}"
    assert isinstance(reader.feed(b"\xff\n")[0], ProtocolError)


VECTORS = json.loads((Path(__file__).parent / "vectors/jsonrpc-captured.json").read_text())


@pytest.mark.parametrize("case", VECTORS["cases"])
def test_real_firmware_frames_decode_and_bridge_without_shape_invention(case):
    frame = case["message"]
    method = case["method"]
    op = cast(Operation, method) if method in OPERATIONS else None
    event = decode_message(frame, op, request_id=1 if op else None)
    wire = event_to_wire(event, frame.get("id"))
    assert wire is not None
    restored = json.loads(wire)
    assert restored["jsonrpc"] == "2.0"
    if "result" in frame:
        for key, value in frame["result"]["value"].items():
            assert restored["result"]["value"][key] == value
    elif "error" in frame:
        assert restored["error"] == frame["error"]


def test_validation_errors_do_not_echo_credentials():
    with pytest.raises(InvalidCommandError) as error:
        parse_command({"params": {"password": "do-not-echo-secret"}})
    assert "do-not-echo-secret" not in str(error.value)
