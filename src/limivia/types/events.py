from typing import Annotated, Any, Literal

from pydantic import Field

from limivia._models import Model

from .commands import Operation
from .models import ADCSample, DeviceError, GPIOReading, Hello, Snapshot


class HelloCompletedEvent(Model):
    type: Literal["hello.completed"] = "hello.completed"
    op: Literal["hello"] = "hello"
    request_id: int
    result: Hello


class StateCompletedEvent(Model):
    type: Literal["state.completed"] = "state.completed"
    op: Literal["state"] = "state"
    request_id: int
    result: Snapshot


class GPIOSetCompletedEvent(Model):
    type: Literal["gpio.set.completed"] = "gpio.set.completed"
    op: Literal["gpio.set"] = "gpio.set"
    request_id: int
    result: Snapshot


class GPIOReadCompletedEvent(Model):
    type: Literal["gpio.read.completed"] = "gpio.read.completed"
    op: Literal["gpio.read"] = "gpio.read"
    request_id: int
    result: GPIOReading


class PWMSetCompletedEvent(Model):
    type: Literal["pwm.set.completed"] = "pwm.set.completed"
    op: Literal["pwm.set"] = "pwm.set"
    request_id: int
    result: Snapshot


class PWMStopCompletedEvent(Model):
    type: Literal["pwm.stop.completed"] = "pwm.stop.completed"
    op: Literal["pwm.stop"] = "pwm.stop"
    request_id: int
    result: Snapshot


class ADCReadCompletedEvent(Model):
    type: Literal["adc.read.completed"] = "adc.read.completed"
    op: Literal["adc.read"] = "adc.read"
    request_id: int
    result: ADCSample


class ADCStartCompletedEvent(Model):
    type: Literal["adc.start.completed"] = "adc.start.completed"
    op: Literal["adc.start"] = "adc.start"
    request_id: int
    result: ADCSample


class ADCStopCompletedEvent(Model):
    type: Literal["adc.stop.completed"] = "adc.stop.completed"
    op: Literal["adc.stop"] = "adc.stop"
    request_id: int
    result: Snapshot


class TimerStartCompletedEvent(Model):
    type: Literal["timer.start.completed"] = "timer.start.completed"
    op: Literal["timer.start"] = "timer.start"
    request_id: int
    result: Snapshot


class TimerStopCompletedEvent(Model):
    type: Literal["timer.stop.completed"] = "timer.stop.completed"
    op: Literal["timer.stop"] = "timer.stop"
    request_id: int
    result: Snapshot


class PinReleaseCompletedEvent(Model):
    type: Literal["pin.release.completed"] = "pin.release.completed"
    op: Literal["pin.release"] = "pin.release"
    request_id: int
    result: Snapshot


class OutputsStopCompletedEvent(Model):
    type: Literal["outputs.stop.completed"] = "outputs.stop.completed"
    op: Literal["outputs.stop"] = "outputs.stop"
    request_id: int
    result: Snapshot


class CommandFailedEvent(Model):
    type: Literal["command.failed"] = "command.failed"
    request_id: int
    op: Operation
    error: DeviceError


class StateChangedEvent(Model):
    type: Literal["state.changed"] = "state.changed"
    revision: int


class ADCSampleEvent(Model):
    type: Literal["adc.sample"] = "adc.sample"
    data: ADCSample


class ProtocolErrorEvent(Model):
    type: Literal["protocol.error"] = "protocol.error"
    message: str


class UnknownEvent(Model):
    type: Literal["unknown"] = "unknown"
    raw: dict[str, Any]


class ConnectionClosedEvent(Model):
    type: Literal["connection.closed"] = "connection.closed"
    error: DeviceError | None = None


type CommandCompletedEvent = (
    HelloCompletedEvent
    | StateCompletedEvent
    | GPIOSetCompletedEvent
    | GPIOReadCompletedEvent
    | PWMSetCompletedEvent
    | PWMStopCompletedEvent
    | ADCReadCompletedEvent
    | ADCStartCompletedEvent
    | ADCStopCompletedEvent
    | TimerStartCompletedEvent
    | TimerStopCompletedEvent
    | PinReleaseCompletedEvent
    | OutputsStopCompletedEvent
)

type DeviceEvent = Annotated[
    CommandCompletedEvent
    | CommandFailedEvent
    | StateChangedEvent
    | ADCSampleEvent
    | ProtocolErrorEvent
    | UnknownEvent
    | ConnectionClosedEvent,
    Field(discriminator="type"),
]
