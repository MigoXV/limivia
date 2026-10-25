"""常量对照独立类型契约与原始 wire 值，不依赖相邻固件或实物。"""

import json
import secrets
from typing import get_args

import pytest

from limivia import EventType, Level, Pins, TransportKind, constants
from limivia._schema import OPERATIONS
from limivia.constants import (
    FirmwareProfile,
    JobState,
    MQTTProtocol,
    NotificationTopic,
    OperationName,
    PeripheralKind,
    QueryName,
    ResourceState,
)
from limivia.protocol import EVENT_ADAPTER, encode_command, parse_command
from limivia.types import (
    ClientEventParam,
    DeviceError,
    DeviceEvent,
    JobStatus,
    LinkKind,
    Operation,
    ResourceKind,
)
from limivia.types.events import ResponseEvent


def values(namespace):
    return {value for name, value in vars(namespace).items() if name.isupper()}


def test_wire_operations_match_independent_literal_contract_and_schema():
    assert values(OperationName) == set(get_args(Operation.__value__)) == set(OPERATIONS)
    assert len(values(OperationName)) == 76
    assert values(QueryName).isdisjoint(values(OperationName))


def test_events_match_literal_discriminators_and_pydantic_defaults():
    models = get_args(get_args(DeviceEvent.__value__)[0])
    declared = set()
    for model in models:
        field = model.model_fields["type"]
        (literal,) = get_args(field.annotation)
        assert field.default == literal
        declared.add(literal)
    assert values(EventType) == declared
    assert len(declared) == len(models)


def test_kinds_and_states_match_independent_model_types():
    assert values(TransportKind) == set(get_args(LinkKind.__value__))
    assert values(PeripheralKind) == set(get_args(ResourceKind.__value__))
    assert values(JobState) == set(get_args(JobStatus.model_fields["state"].annotation))
    # 已删除的资源不出现在 ResourceInfo 中，free 是生命周期名称而非活动快照状态。
    from limivia.types import ResourceInfo

    assert values(ResourceState) - {"free"} == set(
        get_args(ResourceInfo.model_fields["state"].annotation)
    )


def test_board_aliases_keep_exact_chip_gpio_numbers():
    for pin in range(22):
        assert type(getattr(Pins, f"GPIO{pin}")) is int
        assert getattr(Pins, f"GPIO{pin}") == pin
    assert {
        name: getattr(Pins, name)
        for name in ["LED", "STATUS_LED", "BOOT_BUTTON", "USB_DM", "USB_DP"]
    } == {
        "LED": 13,
        "STATUS_LED": 12,
        "BOOT_BUTTON": 9,
        "USB_DM": 18,
        "USB_DP": 19,
    }
    assert not hasattr(Pins, "UART_TX") and not hasattr(Pins, "UART_RX")
    assert Level.LOW == 0 and Level.HIGH == 1


def test_every_public_constant_is_a_primitive_json_value():
    for name in constants.__all__:
        namespace = getattr(constants, name)
        if namespace is not Pins:
            assert len(values(namespace)) == sum(key.isupper() for key in vars(namespace))
        for value in values(namespace):
            assert type(value) in (str, int)
            assert json.loads(json.dumps(value)) == value


@pytest.mark.parametrize("pin", [Pins.LED, Pins.STATUS_LED])
def test_named_pins_and_levels_survive_strict_validation_without_local_pin_policy(pin):
    # STATUS_LED 仍由设备拒绝；命名常量不会增添本地准入表。
    command: ClientEventParam = {
        "type": OperationName.RESOURCE_OPEN,
        "params": {
            "kind": PeripheralKind.GPIO,
            "pins": {"pin": pin},
            "config": {"mode": "output", "level": Level.HIGH},
        },
    }
    wire = json.loads(encode_command(parse_command(command), 1))
    assert wire["method"] == "resource.open"
    assert wire["params"]["args"] == {
        "kind": "gpio",
        "pins": {"pin": pin},
        "config": {"mode": "output", "level": 1},
    }


def test_named_notifications_round_trip_through_discriminator():
    raw = {
        "type": EventType.DATA_AVAILABLE,
        "boot_id": "0" * 16,
        "session": secrets.token_hex(16),
        "event_sequence": 1,
        "revision": 1,
        "resource": 1,
        "instance": 1,
        "job_id": 0,
        "sequence": 1,
        "dropped": 0,
    }
    event = EVENT_ADAPTER.validate_python(raw)
    assert event.type == "data.available"
    assert json.loads(event.to_json()) == raw
    assert not isinstance(event, ResponseEvent)
    command = parse_command(
        {"type": OperationName.EVENT_SUBSCRIBE, "params": {"topics": [NotificationTopic.DATA]}}
    )
    assert command.params["topics"] == ["data"]


def test_unknown_error_reason_and_profile_remain_forward_compatible():
    from limivia.types import Hello, MQTTOptions
    from tests.fakes import HELLO

    assert DeviceError(reason="future_driver_reason").reason == "future_driver_reason"
    assert Hello.model_validate({**HELLO, "profile": "future-image"}).profile == "future-image"
    assert FirmwareProfile.BUS == "bus"
    options = MQTTOptions(device_id=HELLO["device_id"], protocol=MQTTProtocol.V5)
    assert json.loads(options.to_json())["protocol"] == "5.0"
