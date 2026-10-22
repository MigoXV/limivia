import json

import pytest

from limivia import InvalidCommandError, ProtocolError
from limivia.protocol import (
    LineReader,
    decode_message,
    encode_command,
    event_to_wire,
    parse_wire_command,
)
from limivia.types import GPIOReadCommand, HelloCommand

COMMAND = '{"v":1,"id":1,"op":"hello","params":{}}\n'


@pytest.mark.parametrize(
    "text",
    [
        "{}\n",
        COMMAND * 2,
        COMMAND.rstrip(),
        "[1]\n",
        "null\n",
        "x" * 1025 + "\n",
        COMMAND.replace('"id":1', '"id":true'),
        COMMAND.replace('"v":1', '"v":true'),
        COMMAND.replace('"id":1', '"id":0'),
        COMMAND.replace('"id":1', '"id":2147483648'),
        COMMAND.replace('"hello"', '"he\u0000llo"'),
    ],
)
def test_invalid_wire_command(text):
    with pytest.raises(ProtocolError):
        parse_wire_command(text)


def test_command_roundtrip_and_limits():
    request_id, event = parse_wire_command(COMMAND)
    assert request_id == 1 and isinstance(event, HelloCommand)
    assert json.loads(encode_command(event, request_id)) == json.loads(COMMAND)
    with pytest.raises(InvalidCommandError):
        encode_command(GPIOReadCommand(params={"pin": 10**1100}), 2)
    with pytest.raises(InvalidCommandError) as error:
        parse_wire_command(COMMAND.replace('"hello"', '"future"'))
    assert error.value.request_id == 1 and error.value.code == "unknown_operation"


def test_incremental_utf8_and_oversize_recovery():
    reader = LineReader(max_length=10)
    lines = []
    for byte in "设备\n".encode():
        lines.extend(reader.feed(bytes([byte])))
    assert lines == ["设备"]
    results = reader.feed(b"x" * 100 + b"\n{}\n")
    assert isinstance(results[0], ProtocolError)
    assert results[1] == "{}"


def test_bridge_id_translation_and_model_serialization():
    event = decode_message(
        {"v": 1, "id": 22, "ok": True, "result": {"pin": 13, "level": 1}}, "gpio.read"
    )
    assert event.type == "gpio.read.completed"
    assert json.loads(event.to_json()) == event.to_dict()
    assert event_to_wire(event) is None
    assert json.loads(event_to_wire(event, 3)) == {
        "v": 1,
        "id": 3,
        "ok": True,
        "result": {"pin": 13, "level": 1},
    }
