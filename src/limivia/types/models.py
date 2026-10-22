from typing import Literal

from limivia._models import Model

type LinkKind = Literal["ble", "usb"]
type PinMode = Literal["idle", "input", "output", "pwm", "adc", "timer"]
type Pull = Literal["none", "up", "down"]


class DeviceInfo(Model):
    id: str
    name: str


class Pin(Model):
    pin: int
    mode: PinMode
    pull: Pull
    level: Literal[0, 1] | None


class PWM(Model):
    pin: int
    frequency: int
    duty: float
    resolution: int
    breath_ms: int


class Timer(Model):
    id: int
    pin: int
    kind: Literal["blink", "pulse"]
    high_ms: int
    low_ms: int
    count: int
    elapsed_ms: int


class ADCStream(Model):
    pin: int
    interval_ms: int


class ADCSample(Model):
    pin: int
    raw: int
    calibrated: bool
    millivolts: int | None
    uptime_ms: int


class GPIOReading(Model):
    pin: int
    level: Literal[0, 1]


class Snapshot(Model):
    revision: int
    uptime_ms: int
    ble_connected: bool
    usb_active: bool
    pins: list[Pin]
    pwm: list[PWM]
    timers: list[Timer]
    streams: list[ADCStream]


class Capabilities(Model):
    features: list[str]
    max_pwm: int
    max_timers: int
    status_led: int
    demo_led: int
    adc_max_mv: int
    adc_calibrated: bool


class Hello(Model):
    name: str
    board: str
    firmware: str
    device_id: str
    protocol: int
    state: Snapshot
    capabilities: Capabilities


class DeviceError(Model):
    code: str
    message: str
    source: Literal["device", "sdk"] = "device"
    may_have_executed: bool = False
