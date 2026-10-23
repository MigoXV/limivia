from typing import Annotated, Any, Literal

from pydantic import Field

from .._models import Model
from .commands import Operation
from .models import (
    CapabilitiesPage,
    DeviceDiscovery,
    DeviceError,
    Diagnostics,
    Hello,
    JobStatus,
    ResourceInfo,
    StatePage,
    StateSnapshot,
)


class ResponseEvent(Model):
    request_id: int
    op: Operation | Literal["discover", "state.snapshot"]
    boot_id: str | None = None
    session: str | None = None


class HelloCompletedEvent(ResponseEvent):
    type: Literal["hello.completed"] = "hello.completed"
    result: Hello


class StateCompletedEvent(ResponseEvent):
    type: Literal["state.completed"] = "state.completed"
    result: StatePage


class CapabilitiesCompletedEvent(ResponseEvent):
    type: Literal["capabilities.completed"] = "capabilities.completed"
    result: CapabilitiesPage


class ResourceGetCompletedEvent(ResponseEvent):
    type: Literal["resource.get.completed"] = "resource.get.completed"
    result: ResourceInfo


class DiagnosticsCompletedEvent(ResponseEvent):
    type: Literal["diagnostics.completed"] = "diagnostics.completed"
    result: Diagnostics


class CommandCompletedEvent(ResponseEvent):
    type: Literal["command.completed"] = "command.completed"
    result: dict[str, Any]


class CommandAcceptedEvent(ResponseEvent):
    type: Literal["command.accepted"] = "command.accepted"
    job: JobStatus


class JobCompletedEvent(ResponseEvent):
    type: Literal["job.completed"] = "job.completed"
    job: JobStatus


class JobFailedEvent(ResponseEvent):
    type: Literal["job.failed"] = "job.failed"
    job: JobStatus
    error: DeviceError


class JobCancelledEvent(ResponseEvent):
    type: Literal["job.cancelled"] = "job.cancelled"
    job: JobStatus


class CommandFailedEvent(ResponseEvent):
    type: Literal["command.failed"] = "command.failed"
    error: DeviceError
    job_id: int | None = None
    job: JobStatus | None = None


class Notification(Model):
    boot_id: str
    session: str
    event_sequence: int
    revision: int
    resource: int
    instance: int
    job_id: int
    sequence: int
    dropped: int


class JobFinishedEvent(Notification):
    type: Literal["job.finished"] = "job.finished"


class StateChangedEvent(Notification):
    type: Literal["state.changed"] = "state.changed"


class DataAvailableEvent(Notification):
    type: Literal["data.available"] = "data.available"


class ProtocolErrorEvent(Model):
    type: Literal["protocol.error"] = "protocol.error"
    message: str


class UnknownEvent(Model):
    type: Literal["unknown"] = "unknown"
    raw: dict[str, Any]


class ConnectionClosedEvent(Model):
    type: Literal["connection.closed"] = "connection.closed"
    error: DeviceError | None = None


class DiscoveryCompletedEvent(ResponseEvent):
    type: Literal["discovery.completed"] = "discovery.completed"
    result: DeviceDiscovery


class StateSnapshotCompletedEvent(ResponseEvent):
    type: Literal["state.snapshot.completed"] = "state.snapshot.completed"
    result: StateSnapshot


class RpcErrorEvent(Model):
    type: Literal["rpc.error"] = "rpc.error"
    wire_id: str | int | float | None
    error: DeviceError


class NotificationGapEvent(Model):
    type: Literal["notifications.gap"] = "notifications.gap"
    boot_id: str
    session: str
    expected: int
    received: int
    dropped: int


type DeviceEvent = Annotated[
    DiscoveryCompletedEvent
    | StateSnapshotCompletedEvent
    | RpcErrorEvent
    | NotificationGapEvent
    | HelloCompletedEvent
    | StateCompletedEvent
    | CapabilitiesCompletedEvent
    | ResourceGetCompletedEvent
    | DiagnosticsCompletedEvent
    | CommandCompletedEvent
    | CommandAcceptedEvent
    | JobCompletedEvent
    | JobFailedEvent
    | JobCancelledEvent
    | CommandFailedEvent
    | JobFinishedEvent
    | StateChangedEvent
    | DataAvailableEvent
    | ProtocolErrorEvent
    | UnknownEvent
    | ConnectionClosedEvent,
    Field(discriminator="type"),
]
