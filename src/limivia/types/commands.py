from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import Field

from limivia._models import Model

from .models import Pull

type Operation = Literal[
    "hello",
    "state",
    "gpio.set",
    "gpio.read",
    "pwm.set",
    "pwm.stop",
    "adc.read",
    "adc.start",
    "adc.stop",
    "timer.start",
    "timer.stop",
    "pin.release",
    "outputs.stop",
]


class EmptyParams(TypedDict):
    pass


class PinParams(TypedDict):
    pin: int


class GPIOSetParams(PinParams):
    mode: Literal["input", "output"]
    pull: Pull
    level: Literal[0, 1]


class PWMSetParams(PinParams):
    frequency: Annotated[int, Field(ge=5, le=40000)]
    duty: Annotated[float, Field(ge=0, le=100)]
    breath_ms: NotRequired[Annotated[int, Field(ge=0, le=60000)]]


class ADCStartParams(PinParams):
    interval_ms: Annotated[int, Field(ge=100, le=10000)]


class TimerStartParams(PinParams):
    kind: Literal["blink", "pulse"]
    high_ms: Annotated[int, Field(ge=10, le=3600000)]
    low_ms: Annotated[int, Field(ge=10, le=3600000)]
    count: Annotated[int, Field(ge=0, le=100000)]


class HelloCommand(Model):
    type: Literal["hello"] = "hello"
    params: EmptyParams = Field(default_factory=lambda: EmptyParams())


class HelloCommandParam(TypedDict):
    type: Literal["hello"]
    params: EmptyParams


class StateCommand(Model):
    type: Literal["state"] = "state"
    params: EmptyParams = Field(default_factory=lambda: EmptyParams())


class StateCommandParam(TypedDict):
    type: Literal["state"]
    params: EmptyParams


class GPIOSetCommand(Model):
    type: Literal["gpio.set"] = "gpio.set"
    params: GPIOSetParams


class GPIOSetCommandParam(TypedDict):
    type: Literal["gpio.set"]
    params: GPIOSetParams


class GPIOReadCommand(Model):
    type: Literal["gpio.read"] = "gpio.read"
    params: PinParams


class GPIOReadCommandParam(TypedDict):
    type: Literal["gpio.read"]
    params: PinParams


class PWMSetCommand(Model):
    type: Literal["pwm.set"] = "pwm.set"
    params: PWMSetParams


class PWMSetCommandParam(TypedDict):
    type: Literal["pwm.set"]
    params: PWMSetParams


class PWMStopCommand(Model):
    type: Literal["pwm.stop"] = "pwm.stop"
    params: PinParams


class PWMStopCommandParam(TypedDict):
    type: Literal["pwm.stop"]
    params: PinParams


class ADCReadCommand(Model):
    type: Literal["adc.read"] = "adc.read"
    params: PinParams


class ADCReadCommandParam(TypedDict):
    type: Literal["adc.read"]
    params: PinParams


class ADCStartCommand(Model):
    type: Literal["adc.start"] = "adc.start"
    params: ADCStartParams


class ADCStartCommandParam(TypedDict):
    type: Literal["adc.start"]
    params: ADCStartParams


class ADCStopCommand(Model):
    type: Literal["adc.stop"] = "adc.stop"
    params: PinParams


class ADCStopCommandParam(TypedDict):
    type: Literal["adc.stop"]
    params: PinParams


class TimerStartCommand(Model):
    type: Literal["timer.start"] = "timer.start"
    params: TimerStartParams


class TimerStartCommandParam(TypedDict):
    type: Literal["timer.start"]
    params: TimerStartParams


class TimerStopCommand(Model):
    type: Literal["timer.stop"] = "timer.stop"
    params: PinParams


class TimerStopCommandParam(TypedDict):
    type: Literal["timer.stop"]
    params: PinParams


class PinReleaseCommand(Model):
    type: Literal["pin.release"] = "pin.release"
    params: PinParams


class PinReleaseCommandParam(TypedDict):
    type: Literal["pin.release"]
    params: PinParams


class OutputsStopCommand(Model):
    type: Literal["outputs.stop"] = "outputs.stop"
    params: EmptyParams = Field(default_factory=lambda: EmptyParams())


class OutputsStopCommandParam(TypedDict):
    type: Literal["outputs.stop"]
    params: EmptyParams


type ClientEvent = Annotated[
    HelloCommand
    | StateCommand
    | GPIOSetCommand
    | GPIOReadCommand
    | PWMSetCommand
    | PWMStopCommand
    | ADCReadCommand
    | ADCStartCommand
    | ADCStopCommand
    | TimerStartCommand
    | TimerStopCommand
    | PinReleaseCommand
    | OutputsStopCommand,
    Field(discriminator="type"),
]

type ClientEventParam = (
    HelloCommandParam
    | StateCommandParam
    | GPIOSetCommandParam
    | GPIOReadCommandParam
    | PWMSetCommandParam
    | PWMStopCommandParam
    | ADCReadCommandParam
    | ADCStartCommandParam
    | ADCStopCommandParam
    | TimerStartCommandParam
    | TimerStopCommandParam
    | PinReleaseCommandParam
    | OutputsStopCommandParam
)
