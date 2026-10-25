"""在核心发布边界分发事件；等待与各订阅之间没有抢读。"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

from ._connection import AsyncConnection
from ._exceptions import (
    ControlBusyError,
    DeviceRejectedError,
    JobCancelledError,
    JobFailedError,
    OperationError,
    ResourceConflictError,
    ResultUnknownError,
    SubscriptionOverflowError,
)
from .constants import ErrorReason, ErrorSource, EventType, NotificationTopic
from .types import (
    ClientEvent,
    ClientEventParam,
    CommandAcceptedEvent,
    CommandFailedEvent,
    ConnectionClosedEvent,
    DeviceEvent,
    JobCancelledEvent,
    JobFailedEvent,
    JobStatus,
    ResponseEvent,
)


def check(event: DeviceEvent) -> DeviceEvent:
    """仅在 API 边界构造异常，Future 自身保存事件，避免无人领取的异常。"""
    if isinstance(event, (CommandFailedEvent, JobFailedEvent, JobCancelledEvent)):
        error = getattr(event, "error", None)
        job = getattr(event, "job", None)
        reason = error.reason if error else ErrorReason.CANCELLED
        cls: type[OperationError]
        if isinstance(event, JobCancelledEvent):
            cls = JobCancelledError
        elif isinstance(event, JobFailedEvent):
            cls = JobFailedError
        elif reason == ErrorReason.CONTROL_BUSY:
            cls = ControlBusyError
        elif reason in {
            ErrorReason.PIN_CONFLICT,
            ErrorReason.CONTROLLER_CONFLICT,
            ErrorReason.ADC_UNIT_CONFLICT,
            ErrorReason.RESOURCE_BUSY,
            ErrorReason.BUSY,
            ErrorReason.CHILDREN_EXIST,
        }:
            cls = ResourceConflictError
        elif reason in {
            ErrorReason.TIMEOUT,
            ErrorReason.RESULT_UNKNOWN,
            ErrorReason.RESULT_EXPIRED,
            ErrorReason.JOB_EXPIRED,
            ErrorReason.TRANSPORT_ERROR,
            ErrorReason.CONNECTION_LOST,
            ErrorReason.CANCELLED,
        } or (error and error.source == ErrorSource.SDK and error.may_have_executed):
            cls = ResultUnknownError
        else:
            cls = DeviceRejectedError
        raise cls(
            f"{event.op}: {reason}" + (f"（{error.message}）" if error and error.message else ""),
            request_id=event.request_id,
            op=event.op,
            error=error,
            job=job,
            job_id=getattr(event, "job_id", None),
            event=event,
        )
    return event


def payload(event: DeviceEvent) -> Any:
    check(event)
    if event.type == EventType.JOB_COMPLETED:
        return event.job.result or {}
    return getattr(event, "result", {})


@dataclass(eq=False)
class Ticket:
    request_id: int
    op: str
    accepted: asyncio.Future[DeviceEvent]
    terminal: asyncio.Future[DeviceEvent]
    core: AsyncConnection
    job: JobStatus | None = None

    async def wait(self, *, timeout: float | None = None, accepted: bool = False) -> DeviceEvent:
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("等待超时必须有限且大于零")
        try:
            async with asyncio.timeout(timeout):
                return check(await asyncio.shield(self.accepted if accepted else self.terminal))
        except asyncio.CancelledError as exc:
            exc.add_note(f"仅取消等待；请求 {self.request_id} 的设备作业未被取消，也不会自动重放")
            exc.request_id = self.request_id  # type: ignore[attr-defined]
            exc.job = self.job  # type: ignore[attr-defined]
            raise
        except TimeoutError as exc:
            if isinstance(exc, OperationError):
                raise
            request = self.core._pending.get(self.request_id)
            raise ResultUnknownError(
                f"{self.op}: 等待超时，设备执行结果未知；不要重放写操作",
                request_id=self.request_id,
                op=self.op,
                job=self.job,
                may_have_executed=bool(self.job or (request and request.sent)),
            ) from None


class EventStream:
    def __init__(self, hub: Dispatcher, size: int, *, raw: bool = False):
        if type(size) is not int or size < 1:
            raise ValueError("订阅缓冲需要正整数")
        self.hub = hub
        self.raw = raw
        self.topics: set[str] | None = None
        self.queue: asyncio.Queue[DeviceEvent] = asyncio.Queue(size)
        self.error: BaseException | None = None
        self.closed = False
        self.wake = asyncio.Event()
        self.receiving = False

    def push(self, event: DeviceEvent) -> None:
        if self.closed:
            return
        category = {
            EventType.JOB_FINISHED: {NotificationTopic.JOB},
            EventType.STATE_CHANGED: {NotificationTopic.RESOURCE, NotificationTopic.FLOW},
            EventType.DATA_AVAILABLE: {NotificationTopic.DATA},
        }.get(event.type)
        if (
            self.topics is not None
            and category is not None
            and not category.intersection(self.topics)
        ):
            return
        if self.queue.full():
            self.error = SubscriptionOverflowError("订阅缓冲溢出，请查询设备状态恢复")
            self.close()
            return
        self.queue.put_nowait(event.model_copy(deep=True))
        self.wake.set()
        if isinstance(event, ConnectionClosedEvent):
            self.close()

    def close(self) -> None:
        self.closed = True
        self.hub.streams.discard(self)
        self.wake.set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.close()

    def __aiter__(self):
        return self

    async def __anext__(self) -> DeviceEvent:
        if self.receiving:
            raise RuntimeError("一个订阅只能有一个读取者；请为每个消费者创建订阅")
        self.receiving = True
        try:
            while True:
                if self.error:
                    raise self.error
                if not self.queue.empty():
                    return self.queue.get_nowait()
                if self.closed:
                    raise StopAsyncIteration
                self.wake.clear()
                await self.wake.wait()
        finally:
            self.receiving = False


class Dispatcher:
    def __init__(self, core: AsyncConnection):
        self.core = core
        self.tickets: dict[int, Ticket] = {}
        self.streams: set[EventStream] = set()
        self.hello: DeviceEvent | None = None
        core._attach(self.publish)

    def stream(self, *, size: int | None = None, raw: bool = False) -> EventStream:
        stream = EventStream(self, self.core._event_limit if size is None else size, raw=raw)
        self.streams.add(stream)
        if raw and self.hello:
            stream.push(self.hello)
        if self.core._closed:
            stream.push(ConnectionClosedEvent())
        return stream

    def register(self, rid: int, op: str) -> Ticket:
        loop = asyncio.get_running_loop()
        ticket = Ticket(rid, op, loop.create_future(), loop.create_future(), self.core)
        self.tickets[rid] = ticket
        return ticket

    def submit(
        self, command: ClientEvent | ClientEventParam, *, control: bool | None = None
    ) -> Ticket:
        # _enqueue 不让出执行权：返回前完成登记，writer 不可能提前发出响应。
        request = self.core._enqueue(command, requires_control=control)
        return self.register(request.id, request.command.type)

    def aggregate(self, op: str, *, refresh: bool = False) -> Ticket:
        from . import _aggregate

        rid = _aggregate.start(self.core, op, refresh=refresh)  # type: ignore[arg-type]
        return self.register(rid, op)

    def publish(self, event: DeviceEvent) -> None:
        if event.type == EventType.HELLO_COMPLETED:
            self.hello = event
        if isinstance(event, ResponseEvent):
            ticket = self.tickets.get(event.request_id)
            if ticket:
                if hasattr(event, "job") and event.job is not None:
                    ticket.job = event.job
                if not ticket.accepted.done():
                    ticket.accepted.set_result(event)
                if not isinstance(event, CommandAcceptedEvent):
                    ticket.terminal.set_result(event)
                    self.tickets.pop(event.request_id, None)
        for stream in tuple(self.streams):
            if stream.raw or not isinstance(event, ResponseEvent):
                stream.push(event)
