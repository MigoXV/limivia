from typing import Annotated, Any, Literal

from pydantic import Field

from .._models import Model
from ..constants import EventType
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
    type: Literal["hello.completed"] = EventType.HELLO_COMPLETED
    result: Hello


class StateCompletedEvent(ResponseEvent):
    type: Literal["state.completed"] = EventType.STATE_COMPLETED
    result: StatePage


class CapabilitiesCompletedEvent(ResponseEvent):
    type: Literal["capabilities.completed"] = EventType.CAPABILITIES_COMPLETED
    result: CapabilitiesPage


class ResourceGetCompletedEvent(ResponseEvent):
    type: Literal["resource.get.completed"] = EventType.RESOURCE_GET_COMPLETED
    result: ResourceInfo


class DiagnosticsCompletedEvent(ResponseEvent):
    type: Literal["diagnostics.completed"] = EventType.DIAGNOSTICS_COMPLETED
    result: Diagnostics


class CommandCompletedEvent(ResponseEvent):
    type: Literal["command.completed"] = EventType.COMMAND_COMPLETED
    result: dict[str, Any]


class CommandAcceptedEvent(ResponseEvent):
    type: Literal["command.accepted"] = EventType.COMMAND_ACCEPTED
    job: JobStatus


class JobCompletedEvent(ResponseEvent):
    type: Literal["job.completed"] = EventType.JOB_COMPLETED
    job: JobStatus


class JobFailedEvent(ResponseEvent):
    type: Literal["job.failed"] = EventType.JOB_FAILED
    job: JobStatus
    error: DeviceError


class JobCancelledEvent(ResponseEvent):
    type: Literal["job.cancelled"] = EventType.JOB_CANCELLED
    job: JobStatus


class CommandFailedEvent(ResponseEvent):
    type: Literal["command.failed"] = EventType.COMMAND_FAILED
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
    type: Literal["job.finished"] = EventType.JOB_FINISHED


class StateChangedEvent(Notification):
    type: Literal["state.changed"] = EventType.STATE_CHANGED


class DataAvailableEvent(Notification):
    type: Literal["data.available"] = EventType.DATA_AVAILABLE


class ProtocolErrorEvent(Model):
    type: Literal["protocol.error"] = EventType.PROTOCOL_ERROR
    message: str


class UnknownEvent(Model):
    type: Literal["unknown"] = EventType.UNKNOWN
    raw: dict[str, Any]


class ConnectionClosedEvent(Model):
    type: Literal["connection.closed"] = EventType.CONNECTION_CLOSED
    error: DeviceError | None = None


class DiscoveryCompletedEvent(ResponseEvent):
    type: Literal["discovery.completed"] = EventType.DISCOVERY_COMPLETED
    result: DeviceDiscovery


class StateSnapshotCompletedEvent(ResponseEvent):
    type: Literal["state.snapshot.completed"] = EventType.STATE_SNAPSHOT_COMPLETED
    result: StateSnapshot


class RpcErrorEvent(Model):
    type: Literal["rpc.error"] = EventType.RPC_ERROR
    wire_id: str | int | float | None
    error: DeviceError


class NotificationGapEvent(Model):
    type: Literal["notifications.gap"] = EventType.NOTIFICATIONS_GAP
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
