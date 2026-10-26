import json
import secrets

import pytest

from limivia.constants import OperationName
from limivia.protocol import (
    MANAGEMENT,
    OBSERVERS,
    command_object,
    encode_frame,
    parse_command,
    parse_wire_command,
    wire_command_object,
)
from tests.test_protocol import params_for


@pytest.mark.parametrize("op", sorted(MANAGEMENT - {OperationName.HELLO}))
def test_management_compaction_never_changes_a_mutating_operation(op):
    assert op in OBSERVERS
    command = parse_command({"type": op, "params": params_for(op)})
    context = {"session": secrets.token_hex(8), "control": secrets.token_hex(8), "seq": 7}
    original = command_object(command, 23, **context)
    compact = wire_command_object(command, 23, **context)
    assert isinstance(compact["params"], list)
    assert compact["params"][0] == {"session": context["session"], "seq": 7}
    assert compact["params"][1] == command.params
    assert len(encode_frame(compact)) < len(encode_frame(original))
    assert parse_wire_command(encode_frame(compact).decode()) == (23, command)


@pytest.mark.parametrize("action", ["write", "read", "events"])
def test_gpio_and_consuming_resource_calls_keep_exact_original_wire(action):
    command = parse_command(
        {
            "type": "resource.call",
            "params": {"resource": 1, "instance": 1, "action": action, "args": {}},
        }
    )
    context = {"session": secrets.token_hex(8), "control": secrets.token_hex(8), "seq": 7}
    assert wire_command_object(command, 23, **context) == command_object(command, 23, **context)


@pytest.mark.parametrize(
    "op",
    [
        "hello",
        "resource.open",
        "resource.close",
        "resource.recover",
        "outputs.stop",
        "control.acquire",
        "event.subscribe",
    ],
)
def test_mutation_handshake_and_stop_preserve_original_envelope(op):
    command = parse_command({"type": op, "params": params_for(op)})
    context = {
        "session": secrets.token_hex(8),
        "control": secrets.token_hex(8),
        "seq": 7,
        "client_nonce": secrets.token_hex(16),
    }
    assert wire_command_object(command, 23, **context) == command_object(command, 23, **context)


def test_resource_status_uses_compact_form_without_dropping_instance():
    command = parse_command(
        {
            "type": "resource.call",
            "params": {"resource": 1, "instance": 17, "action": "status", "args": {}},
        }
    )
    session = secrets.token_hex(8)
    wire = wire_command_object(command, 23, session=session, control=secrets.token_hex(8), seq=7)
    assert wire["params"] == [{"session": session, "seq": 7}, command.params]
    assert json.loads(encode_frame(wire))["params"][1]["instance"] == 17
