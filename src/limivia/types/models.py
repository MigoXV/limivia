from __future__ import annotations

import base64
import re
from typing import Any, Literal

from pydantic import ConfigDict, Field, SecretStr, field_validator

from .._models import Model
from ..constants import ErrorSource, MQTTProtocol

type LinkKind = Literal["usb", "ble", "ws", "mqtt"]
type Profile = Literal["bus", "signal", "iot"]
type ResourceKind = Literal[
    "gpio",
    "pwm",
    "adc",
    "adc.continuous",
    "uart",
    "i2c.master",
    "i2c.device",
    "i2c.slave",
    "spi.master",
    "spi.device",
    "spi.slave",
    "twai",
    "rmt.tx",
    "rmt.rx",
    "i2s",
    "sigma_delta",
    "timer",
    "temperature",
]


class DeviceInfo(Model):
    id: str
    name: str


class DeviceIdentity(Model):
    model_config = ConfigDict(extra="allow", strict=True, frozen=True)
    protocol: Literal[3]
    jsonrpc: Literal["2.0"]
    contract: Literal["limivia-v3-jsonrpc2-r2"]
    firmware: str
    board: Literal["luatos-esp32c3-usb"]
    device_id: str
    boot_id: str
    build_id: str
    profile: str
    request_max: int = Field(gt=0, le=1024)
    response_max: int = Field(gt=0, le=8192)
    session_timeout_ms: int = Field(gt=0)
    capability_pages: int = Field(gt=0)
    batch_max: int = Field(gt=0, le=8)
    sequence_window: int = Field(ge=8, le=64)
    auth_mode: Literal["open"]
    resources_max: int
    job_history: int
    buffer_max: int

    @field_validator("boot_id", "device_id")
    @classmethod
    def not_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("身份和会话不可为空")
        return value

    @field_validator("build_id")
    @classmethod
    def elf_sha(cls, value: str) -> str:
        if not re.fullmatch("[0-9a-f]{64}", value):
            raise ValueError("build_id必须为完整ELF SHA256")
        return value


class Hello(DeviceIdentity):
    session: str = Field(min_length=1, repr=False)
    sequence_high: int = Field(ge=0, le=2147483647)


class ResourceInfo(Model):
    id: int
    instance: int
    kind: ResourceKind
    state: Literal["opening", "ready", "closing", "fault"]
    parent: int = 0
    pin_mask: int
    definition: dict[str, Any]
    driver_error: int = 0
    cleanup_error: int = 0


class StatePage(Model):
    page: int = Field(ge=0)
    pages: int = Field(gt=0)
    revision: int
    epoch: int
    uptime_ms: float
    stopping: bool
    autostart_inhibited: bool
    owner_endpoint: int
    resources: list[ResourceInfo]


class CapabilitiesPage(Model):
    page: int = Field(ge=0)
    pages: int = Field(gt=0)
    items: list[dict[str, Any] | list[dict[str, Any]]]
    kind: str | None = None
    available: bool | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)


class JobStatus(Model):
    job_id: int = Field(gt=0)
    resource: int
    state: Literal["accepted", "completed", "failed", "cancelled"]
    action: str
    driver_error: int = 0
    error_code: str | None = None
    external_effect_possible: bool = False
    result_expired: bool = False
    cancel_requested: bool = False
    result: dict[str, Any] | None = None


class BufferInfo(Model):
    buffer_id: int = Field(gt=0)


class FlowInfo(Model):
    flow_id: int = Field(gt=0)
    name: str
    state: str
    step: int
    resources: list[int]
    variables: dict[str, float]


class Diagnostics(Model):
    rejected: int
    stale_completions: int
    lost_notifications: int
    timing: str
    system: dict[str, Any]


class BinaryResult(Model):
    length: int = Field(ge=0, le=4096)
    data: str

    def to_bytes(self) -> bytes:
        try:
            value = base64.b64decode(self.data, validate=True)
        except ValueError as exc:
            raise ValueError("无效Base64") from exc
        if len(value) != self.length or base64.b64encode(value).decode() != self.data:
            raise ValueError("Base64长度或pad位不符合契约")
        return value


class DeviceError(Model):
    code: int | None = None
    reason: str
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    source: Literal["device", "sdk"] = ErrorSource.DEVICE
    may_have_executed: bool = False
    external_effect_possible: bool = False


class WebSocketOptions(Model):
    model_config = ConfigDict(extra="forbid", strict=True)
    ca_file: str | None = None
    certificate_file: str | None = None
    private_key_file: str | None = Field(default=None, repr=False)


class MQTTOptions(WebSocketOptions):
    device_id: str
    logical_client: str | None = None
    protocol: Literal["3.1.1", "5.0"] = MQTTProtocol.V3_1_1
    username: SecretStr | None = None
    password: SecretStr | None = None

    @field_validator("device_id")
    @classmethod
    def mac(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
            raise ValueError("device_id需要完整MAC")
        return value.lower()

    @field_validator("logical_client")
    @classmethod
    def client_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
            raise ValueError("逻辑客户端仅允许1..32位字母、数字、下划线和横线")
        return value


type ConnectionOptions = WebSocketOptions | MQTTOptions


class ParameterInfo(Model):
    name: str
    type: str
    required: bool = False
    min: int | float | None = None
    max: int | float | None = None
    values: str | None = None


class PinCapability(Model):
    pin: int
    digital: bool
    adc1: bool
    deep_sleep_wake: bool


class ActionCapability(Model):
    action: str
    payload: bool = False
    args: list[ParameterInfo] = Field(default_factory=list)


class ResourceCapability(Model):
    kind: str
    available: bool
    capacity: int
    pin_roles: str
    required_pins: str
    config: list[ParameterInfo]
    actions: list[ActionCapability] = Field(default_factory=list)


class OperationCapability(Model):
    op: str
    params: str
    available: bool


class DeviceDiscovery(Model):
    identity: DeviceIdentity
    pins: list[PinCapability]
    resources: list[ResourceCapability]
    operations: list[OperationCapability]
    raw_pages: list[CapabilitiesPage]


class StateSnapshot(Model):
    revision: int
    epoch: int
    resources: list[ResourceInfo]
    pages: list[StatePage]
