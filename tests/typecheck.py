"""公开业务返回类型、raw 接口与事件 discriminator 的静态检查。"""

from typing import assert_type

from limivia import AsyncLimivia, EventType, Level, Limivia, Pins, TransportKind
from limivia.constants import Edge, OperationName, Parity, PeripheralKind, Pull, UARTMode
from limivia.types import (
    ADCSample,
    CapabilitiesCompletedEvent,
    CommandAcceptedEvent,
    CommandCompletedEvent,
    CommandFailedEvent,
    ConnectionClosedEvent,
    DataAvailableEvent,
    DeviceDiscovery,
    DeviceEvent,
    DeviceIdentity,
    DiagnosticsCompletedEvent,
    DiscoveryCompletedEvent,
    Hello,
    HelloCompletedEvent,
    JobCancelledEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobFinishedEvent,
    JobStatus,
    NotificationGapEvent,
    OperationResult,
    ProtocolErrorEvent,
    ResourceGetCompletedEvent,
    RpcErrorEvent,
    StateChangedEvent,
    StateCompletedEvent,
    StatePage,
    StateSnapshot,
    StateSnapshotCompletedEvent,
    UnknownEvent,
)


def consume(event: DeviceEvent) -> None:
    if event.type == "discovery.completed":
        assert_type(event.result, DeviceDiscovery)
    elif event.type == "state.snapshot.completed":
        assert_type(event.result, StateSnapshot)
    elif event.type == "hello.completed":
        assert_type(event.result, Hello)
    elif event.type == "state.completed":
        assert_type(event.result, StatePage)
    elif event.type == "command.accepted":
        assert_type(event.job, JobStatus)
    elif event.type == "job.completed":
        assert_type(event.job, JobStatus)
        assert_type(event.request_id, int)
    elif event.type == "job.failed":
        assert_type(event.error.reason, str)
        assert_type(event.error.code, int | None)


async def async_api():
    async with AsyncLimivia.connect(kind="usb") as board:
        assert_type(board.identity, DeviceIdentity | None)
        assert_type(await board.discover(), DeviceDiscovery)
        assert_type(await board.state.snapshot(), StateSnapshot)
        async with board.gpio.output(13) as led:
            assert_type(await led.read(), int)
            await led.write(1)
        async with board.adc.open(0) as adc:
            assert_type(await adc.read(), ADCSample)
            assert_type(await adc.events(), list[ADCSample])
        async with board.uart.open(tx=20, rx=21) as uart:
            assert_type(await uart.write(b"hello"), int)
            assert_type(await uart.read(5), bytes)
        assert_type(await board.system.time(), OperationResult)
        assert_type(await board.raw.batch([{"type": "state", "params": {}}]), list[int])
        assert_type(await board.raw.resource.open(kind="uart", pins={"tx": 20}, config={}), int)
        async for event in board.raw:
            consume(event)


def sync_api():
    with Limivia.connect(kind="usb") as board:
        assert_type(board.discover(), DeviceDiscovery)
        assert_type(board.state.snapshot(), StateSnapshot)
        with board.gpio.output(13) as led:
            assert_type(led.read(), int)
        with board.adc.open(0) as adc:
            assert_type(adc.read(), ADCSample)
        assert_type(board.raw.resource.open(kind="gpio", pins={"pin": 13}, config={}), int)
        assert_type(board.buffer.write(buffer_id=1, offset=0, data=b"hello"), OperationResult)
        for event in board.raw:
            consume(event)


def consume_named(event: DeviceEvent) -> None:
    if event.type == EventType.HELLO_COMPLETED:
        assert_type(event, HelloCompletedEvent)
    elif event.type == EventType.STATE_COMPLETED:
        assert_type(event, StateCompletedEvent)
    elif event.type == EventType.CAPABILITIES_COMPLETED:
        assert_type(event, CapabilitiesCompletedEvent)
    elif event.type == EventType.RESOURCE_GET_COMPLETED:
        assert_type(event, ResourceGetCompletedEvent)
    elif event.type == EventType.DIAGNOSTICS_COMPLETED:
        assert_type(event, DiagnosticsCompletedEvent)
    elif event.type == EventType.COMMAND_COMPLETED:
        assert_type(event, CommandCompletedEvent)
    elif event.type == EventType.COMMAND_ACCEPTED:
        assert_type(event, CommandAcceptedEvent)
    elif event.type == EventType.JOB_COMPLETED:
        assert_type(event, JobCompletedEvent)
    elif event.type == EventType.JOB_FAILED:
        assert_type(event, JobFailedEvent)
    elif event.type == EventType.JOB_CANCELLED:
        assert_type(event, JobCancelledEvent)
    elif event.type == EventType.COMMAND_FAILED:
        assert_type(event, CommandFailedEvent)
    elif event.type == EventType.JOB_FINISHED:
        assert_type(event, JobFinishedEvent)
    elif event.type == EventType.STATE_CHANGED:
        assert_type(event, StateChangedEvent)
    elif event.type == EventType.DATA_AVAILABLE:
        assert_type(event, DataAvailableEvent)
    elif event.type == EventType.PROTOCOL_ERROR:
        assert_type(event, ProtocolErrorEvent)
    elif event.type == EventType.UNKNOWN:
        assert_type(event, UnknownEvent)
    elif event.type == EventType.CONNECTION_CLOSED:
        assert_type(event, ConnectionClosedEvent)
    elif event.type == EventType.DISCOVERY_COMPLETED:
        assert_type(event, DiscoveryCompletedEvent)
    elif event.type == EventType.STATE_SNAPSHOT_COMPLETED:
        assert_type(event, StateSnapshotCompletedEvent)
    elif event.type == EventType.RPC_ERROR:
        assert_type(event, RpcErrorEvent)
    elif event.type == EventType.NOTIFICATIONS_GAP:
        assert_type(event, NotificationGapEvent)


async def named_options():
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        async with board.gpio.output(
            Pins.LED, value=Level.HIGH, pull=Pull.NONE, edge=Edge.RISING
        ) as led:
            await led.write(Level.LOW)
        async with board.uart.open(
            tx=Pins.GPIO20, rx=Pins.GPIO21, parity=Parity.NONE, mode=UARTMode.UART
        ):
            pass
        assert_type(
            await board.raw.send(
                {
                    "type": OperationName.RESOURCE_PREFLIGHT,
                    "params": {
                        "kind": PeripheralKind.GPIO,
                        "pins": {"pin": Pins.LED},
                        "config": {},
                    },
                }
            ),
            int,
        )
