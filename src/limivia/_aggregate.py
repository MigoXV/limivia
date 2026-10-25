"""只读聚合工作；复用已有会话、RPC关联与有界管理通道。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from ._exceptions import DeviceConnectionError, ProtocolError, QueueFullError
from .constants import ErrorReason, ErrorSource, OperationName, QueryName
from .types import (
    ActionCapability,
    CapabilitiesCompletedEvent,
    CommandFailedEvent,
    DeviceDiscovery,
    DeviceError,
    DeviceEvent,
    DiscoveryCompletedEvent,
    OperationCapability,
    PinCapability,
    ResourceCapability,
    StateCompletedEvent,
    StatePage,
    StateSnapshot,
    StateSnapshotCompletedEvent,
)

if TYPE_CHECKING:
    from ._connection import AsyncConnection

type AggregateOperation = Literal["discover", "state.snapshot"]


class QueryFailure(Exception):
    def __init__(self, error: DeviceError):
        self.error = error


def identity_key(connection: AsyncConnection) -> tuple:
    identity = connection.identity
    if identity is None:
        raise DeviceConnectionError("没有有效设备身份")
    return (
        identity.device_id,
        identity.boot_id,
        identity.build_id,
        identity.profile,
        identity.contract,
    )


def start(connection: AsyncConnection, op: AggregateOperation, *, refresh=False) -> int:
    if connection._closed or connection.identity is None:
        raise DeviceConnectionError("需要有效会话")
    if len(connection._aggregate_requests) >= 2:
        raise QueueFullError("最多两个在途聚合查询")
    connection._sequence += 1
    rid = connection._sequence
    connection._aggregate_requests[rid] = op
    task = asyncio.create_task(run(connection, op, rid, refresh), name=f"limivia-{op}")
    connection._aggregate_tasks.add(task)
    task.add_done_callback(connection._aggregate_tasks.discard)
    return rid


async def discover(connection: AsyncConnection, refresh: bool) -> DeviceDiscovery:
    key = identity_key(connection)
    if connection._discovery is not None and not refresh:
        cached = connection._discovery.identity
        cached_key = (
            cached.device_id,
            cached.boot_id,
            cached.build_id,
            cached.profile,
            cached.contract,
        )
        if cached_key == key:
            return connection._discovery.model_copy(deep=True)
    assert connection.identity is not None
    identity = connection.identity.model_copy(deep=True)
    pages = []
    pins = []
    resources: dict[str, ResourceCapability] = {}
    actions: dict[str, list[ActionCapability]] = {}
    operations: list[OperationCapability] = []
    index, count = 0, identity.capability_pages
    while index < count:
        reply = await connection._rpc(OperationName.CAPABILITIES, {"page": index})
        if isinstance(reply, CommandFailedEvent):
            raise QueryFailure(reply.error)
        if not isinstance(reply, CapabilitiesCompletedEvent) or reply.result.page != index:
            raise ProtocolError("能力页身份错误")
        page = reply.result
        if index == 0:
            count = page.pages
        if page.pages != count or identity_key(connection) != key:
            raise ProtocolError("发现期间设备身份或分页变化")
        pages.append(page)
        for item in page.items:
            if isinstance(item, dict):
                if "pin" in item:
                    pins.append(PinCapability.model_validate(item))
                elif "kind" in item:
                    resource = ResourceCapability.model_validate(item)
                    resources[resource.kind] = resource
            elif page.kind is not None:
                actions.setdefault(page.kind, []).extend(
                    ActionCapability.model_validate(action) for action in item
                )
        operations.extend(OperationCapability.model_validate(item) for item in page.operations)
        index += 1
    for kind, descriptions in actions.items():
        if kind in resources:
            resources[kind].actions = descriptions
    result = DeviceDiscovery(
        identity=identity,
        pins=pins,
        resources=list(resources.values()),
        operations=operations,
        raw_pages=pages,
    )
    connection._discovery = result.model_copy(deep=True)
    return result


async def snapshot(connection: AsyncConnection) -> StateSnapshot:
    key = identity_key(connection)
    for _ in range(3):
        pages: list[StatePage] = []
        index, count = 0, 1
        while index < count:
            args = {"page": index}
            if pages:
                args["revision"] = pages[0].revision
            reply = await connection._rpc(OperationName.STATE, args)
            if isinstance(reply, CommandFailedEvent):
                if reply.error.reason == ErrorReason.SNAPSHOT_EXPIRED:
                    break
                raise QueryFailure(reply.error)
            if not isinstance(reply, StateCompletedEvent) or reply.result.page != index:
                raise ProtocolError("状态页身份错误")
            page = reply.result
            if identity_key(connection) != key:
                raise ProtocolError("快照期间设备身份变化")
            if pages and (page.revision, page.epoch, page.pages) != (
                pages[0].revision,
                pages[0].epoch,
                count,
            ):
                break
            count = page.pages
            pages.append(page)
            index += 1
        if index == count:
            return StateSnapshot(
                revision=pages[0].revision,
                epoch=pages[0].epoch,
                resources=[r for page in pages for r in page.resources],
                pages=pages,
            )
    raise QueryFailure(
        DeviceError(
            reason=ErrorReason.SNAPSHOT_EXPIRED,
            source=ErrorSource.SDK,
            message="三次只读快照均发生变化",
        )
    )


async def run(connection: AsyncConnection, op: AggregateOperation, rid: int, refresh: bool) -> None:
    event: DeviceEvent
    try:
        async with asyncio.timeout(connection._job_timeout):
            if op == QueryName.DISCOVER:
                result = await discover(connection, refresh)
                event = DiscoveryCompletedEvent(
                    request_id=rid,
                    op=op,
                    boot_id=connection._boot_id,
                    session=connection._session,
                    result=result,
                )
            else:
                state = await snapshot(connection)
                event = StateSnapshotCompletedEvent(
                    request_id=rid,
                    op=op,
                    boot_id=connection._boot_id,
                    session=connection._session,
                    result=state,
                )
        connection._publish(event)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 -- aggregate task boundary
        error = (
            exc.error
            if isinstance(exc, QueryFailure)
            else DeviceError(
                reason=ErrorReason.TIMEOUT
                if isinstance(exc, TimeoutError)
                else ErrorReason.INVALID_RESPONSE,
                message="只读聚合查询失败",
                source=ErrorSource.SDK,
            )
        )
        connection._publish(
            CommandFailedEvent(
                request_id=rid,
                op=op,
                error=error,
                boot_id=connection._boot_id,
                session=connection._session,
            )
        )
    finally:
        connection._aggregate_requests.pop(rid, None)
