"""面向业务调用的结果和配置；参数命名与固件 v3 契约对应。"""

from typing import Any, Literal, TypedDict

from .._models import Model


class OperationResult(Model):
    data: dict[str, Any]


class ConfirmedState(Model):
    resource: int
    instance: int
    revision: int
    observed_us: int
    enabled: bool


class GPIOState(ConfirmedState):
    mode: Literal["input", "output", "open_drain"]
    level: Literal[0, 1]


class PWMState(ConfirmedState):
    duty_percent: float


class ADCSample(Model):
    raw: int
    millivolts: int | None
    sequence: int | None = None
    time_us: float | None = None


class PeripheralEvent(Model):
    sequence: int
    data: str


class PeripheralEvents(Model):
    events: list[PeripheralEvent]


class GPIOConfig(TypedDict, total=False):
    pull: Literal["none", "up", "down"]
    drive: int
    invert: bool
    edge: Literal["none", "rising", "falling", "any"]
    debounce_us: int


class PWMConfig(TypedDict, total=False):
    invert: bool
    end_level: int
    breath_ms: int


class UARTConfig(TypedDict, total=False):
    data_bits: int
    parity: Literal["none", "even", "odd"]
    stop_bits: int
    flow_control: bool
    rx_threshold: int
    invert_mask: int
    mode: Literal["uart", "rs485"]
    rx_buffer: int
    tx_buffer: int
    loopback: bool
