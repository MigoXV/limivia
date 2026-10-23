from __future__ import annotations

import asyncio
import logging
import secrets
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Literal

from anyio import CancelScope

from ._exceptions import DeviceConnectionError, InvalidCommandError, ProtocolError, QueueFullError
from .protocol import (
    JOB_OPERATIONS,
    MANAGEMENT,
    RPC_MANAGEMENT,
    LineReader,
    command_object,
    control_required,
    decode_message,
    encode_command,
    encode_frame,
    load_json,
    parse_command,
    response_context,
    valid_id,
)
from .resources import Resources
from .transports import Transport
from .types import (
    ClientEvent,
    ClientEventParam,
    CommandAcceptedEvent,
    CommandCompletedEvent,
    CommandFailedEvent,
    ConnectionClosedEvent,
    DeviceDiscovery,
    DeviceError,
    DeviceEvent,
    DeviceIdentity,
    Hello,
    HelloCompletedEvent,
    JobCancelledEvent,
    JobCompletedEvent,
    JobFailedEvent,
    JobStatus,
    NotificationGapEvent,
    Operation,
    ProtocolErrorEvent,
    ResponseEvent,
    RpcErrorEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class _Request:
    id: int
    command: ClientEvent
    future: asyncio.Future[DeviceEvent]
    session: str | None
    control: str | None
    internal: bool = False
    wire_id: int | None = None
    sent: bool = False
    seq: int | None = None
    epoch: int = 0
    nonce: str = ""
    barrier_applied: bool = False
    priority: int = 0
    frame_high_seq: int = 0


@dataclass
class _Tracked:
    request: _Request
    job: JobStatus
    deadline: float


class AsyncConnection(Resources[Awaitable[int]]):
    """actor独占关联状态；三个有界RPC通道与一个有界作业跟踪器。"""

    def __init__(
        self,
        transport: Transport,
        *,
        timeout: float,
        connect_timeout: float,
        event_queue_size: int,
        job_timeout: float = 30,
        job_poll_interval: float = 0.1,
        expected_device_id: str | None = None,
    ):
        super().__init__(self.send, snapshot=self._state_snapshot)
        self._transport = transport
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._job_timeout = job_timeout
        self._poll = job_poll_interval
        self._expected_device = expected_device_id
        self._event_limit = event_queue_size
        self._outgoing: asyncio.Queue[_Request | list[_Request]] = asyncio.Queue(8)
        self._management: asyncio.Queue[_Request | list[_Request]] = asyncio.Queue(4)
        self._stops: asyncio.Queue[_Request | list[_Request]] = asyncio.Queue(1)
        self._pending: dict[int, _Request] = {}
        self._wire_pending: dict[int, _Request] = {}
        self._jobs: dict[int, _Tracked] = {}
        self._job_slots: set[int] = set()
        self._events: deque[DeviceEvent] = deque()
        self._terminal: deque[DeviceEvent] = deque()
        self._wake = asyncio.Event()
        self._job_wake = asyncio.Event()
        self._session_ready = asyncio.Event()
        self._session: str | None = None
        self._control: str | None = None
        self._boot_id: str | None = None
        self._heartbeat_interval = 1.5
        self._last_confirmed = 0.0
        self._sequence = 0
        self._wire_sequence = 0
        self._send_sequence = 0
        self._internal_sequence = 0
        self._nonce = secrets.token_hex(16)
        self._control_epoch = 0
        self._stop_inflight = False
        self._stop_job_id: int | None = None
        self._hello: Hello | None = None
        self.identity: DeviceIdentity | None = None
        self._discovery: DeviceDiscovery | None = None
        self._aggregate_requests: dict[int, Literal["discover", "state.snapshot"]] = {}
        self._aggregate_tasks: set[asyncio.Task] = set()
        self._sent_sequences: dict[int, int] = {}
        self._dispatch_wake = asyncio.Event()
        self._lane_inflight = [0, 0, 0]
        self._management_regular = 0
        self._rpc_tasks: set[asyncio.Task] = set()
        self._last_notification = 0
        self._receiving = False
        self._opened = False
        self._closed = False
        self._tasks: list[asyncio.Task[None]] = []
        self._cleanup_task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.handshake_request_id = 0

    async def _open(self) -> None:
        try:
            async with asyncio.timeout(self._connect_timeout):
                await self._transport.open()
                if self._closed:
                    raise DeviceConnectionError("连接已关闭")
                self._opened = True
                self._tasks = [asyncio.create_task(self._read(), name="limivia-reader")]
                self._tasks.append(asyncio.create_task(self._writer(), name="limivia-writer"))
                self.handshake_request_id = await self.hello()
                await self._ready
                if self._closed:
                    raise DeviceConnectionError("握手后连接关闭")
                self._tasks.extend(
                    (
                        asyncio.create_task(self._heartbeat(), name="limivia-heartbeat"),
                        asyncio.create_task(self._track_jobs(), name="limivia-jobs"),
                        asyncio.create_task(
                            self._track_jobs(stop_only=True), name="limivia-stop-jobs"
                        ),
                    )
                )
        except BaseException:
            await self.close()
            raise

    async def hello(self, *, client_nonce: str | None = None) -> int:
        nonce = self._nonce if client_nonce is None else client_nonce
        if len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce):
            raise InvalidCommandError("client_nonce需要32位小写十六进制")
        request = self._enqueue({"type": "hello", "params": {}})
        request.nonce = nonce
        return request.id

    async def send(self, event: ClientEvent | ClientEventParam) -> int:
        return self._enqueue(event).id

    def _enqueue(
        self,
        event: ClientEvent | ClientEventParam,
        *,
        internal: bool = False,
        queue_it: bool = True,
    ) -> _Request:
        if not self._opened or self._closed:
            raise DeviceConnectionError("设备连接已关闭，请重新连接")
        command = parse_command(event)
        encode_command(command, 2147483647, session=self._session, control=self._control)
        if command.type == "hello" and (
            self._jobs
            or self._job_slots
            or any(
                r.command.type in JOB_OPERATIONS or r.command.type == "hello"
                for r in self._pending.values()
            )
        ):
            raise QueueFullError("作业跟踪或hello进行中，不能轮换会话")
        reserved = (
            command.type in JOB_OPERATIONS and command.type != "outputs.stop" and not internal
        )
        if reserved and len(self._job_slots) >= self._job_limit:
            raise QueueFullError("最多8个待受理/跟踪作业，停止入口仍可用")
        rid = self._sequence + 1 if not internal else self._internal_sequence - 1
        request = _Request(
            rid,
            command,
            asyncio.get_running_loop().create_future(),
            self._session,
            self._control,
            internal,
        )
        request.epoch = self._control_epoch
        request.nonce = self._nonce
        queue = (
            self._stops
            if command.type == "outputs.stop"
            else self._management
            if command.type in MANAGEMENT
            else self._outgoing
        )
        try:
            if queue_it:
                queue.put_nowait(request)
        except asyncio.QueueFull as exc:
            raise QueueFullError("命令通道已满") from exc
        if internal:
            self._internal_sequence = rid
        else:
            self._sequence = rid
        self._pending[rid] = request
        if reserved:
            self._job_slots.add(rid)
        if command.type == "outputs.stop":
            self._stop_inflight = True
        if command.type == "hello":
            self._session_ready.clear()
        self._dispatch_wake.set()
        return request

    def __aiter__(self) -> AsyncConnection:
        return self

    async def __anext__(self) -> DeviceEvent:
        return await self.recv()

    async def recv(self) -> DeviceEvent:
        if self._receiving:
            raise RuntimeError("一个连接只能有一个事件消费者")
        self._receiving = True
        try:
            while True:
                if self._events:
                    return self._events.popleft()
                if self._terminal:
                    return self._terminal.popleft()
                if self._closed:
                    raise StopAsyncIteration
                self._wake.clear()
                await self._wake.wait()
        finally:
            self._receiving = False

    def _publish(self, event: DeviceEvent) -> None:
        if self._closed:
            return
        if len(self._events) >= self._event_limit:
            if isinstance(event, ResponseEvent):
                self._terminal.append(event)
            self._terminate(
                DeviceError(
                    reason="event_buffer_overflow",
                    message="事件缓冲溢出，请重连查询状态",
                    source="sdk",
                )
            )
            return
        self._events.append(event)
        self._wake.set()

    def _failure(
        self,
        request: _Request,
        code: str,
        message: str,
        job_id: int | None = None,
        job: JobStatus | None = None,
    ) -> CommandFailedEvent:
        return CommandFailedEvent(
            request_id=request.id,
            op=request.command.type,
            boot_id=self._boot_id,
            session=self._session,
            job_id=job_id,
            job=job,
            error=DeviceError(
                reason=code,
                message=message,
                source="sdk",
                may_have_executed=request.sent,
                external_effect_possible=job.external_effect_possible if job else False,
            ),
        )

    def _complete(self, request: _Request, event: DeviceEvent) -> None:
        if self._pending.pop(request.id, None) is None:
            return
        if request.wire_id is not None and not (
            isinstance(event, CommandFailedEvent)
            and event.error.reason == "timeout"
            and request.wire_id in self._sent_sequences
        ):
            self._wire_pending.pop(request.wire_id, None)
            self._sent_sequences.pop(request.wire_id, None)
        if isinstance(event, HelloCompletedEvent):
            hello = event.result
            if self._expected_device and hello.device_id.lower() != self._expected_device.lower():
                event = self._failure(request, "wrong_device", "设备MAC不匹配，停止连接")
            elif hello.session_timeout_ms < 300:
                event = self._failure(request, "incompatible_device", "会话租约过短")
            else:
                same = self._session == hello.session and self._boot_id == hello.boot_id
                if hello.boot_id != event.boot_id or hello.session != event.session:
                    self._terminate(DeviceError(reason="invalid_identity", source="sdk"))
                    return
                if not same:
                    self._control_epoch += 1
                    self._control = None
                    self._discovery = None
                    self._last_notification = 0
                    self._send_sequence = hello.sequence_high
                    self._sent_sequences.clear()
                self._nonce = request.nonce
                self._hello = hello
                self.identity = DeviceIdentity.model_validate(
                    hello.model_dump(exclude={"session", "sequence_high"})
                )
                self._session = hello.session
                self._boot_id = hello.boot_id
                self._heartbeat_interval = min(1.5, hello.session_timeout_ms / 3000)
                self._session_ready.set()
        if isinstance(event, CommandCompletedEvent) and request.command.type == "control.acquire":
            token = event.result.get("control")
            if not isinstance(token, str) or not token:
                event = self._failure(request, "invalid_response", "缺少控制token")
            elif request.epoch == self._control_epoch and not self._stop_inflight:
                self._control = token
        if request.command.type in ("control.release", "outputs.stop") and not isinstance(
            event, CommandFailedEvent
        ):
            self._revoke(request)
        if request.command.type == "outputs.stop" and isinstance(event, CommandFailedEvent):
            self._stop_inflight = False
        if (
            isinstance(event, CommandFailedEvent)
            and event.error.reason == "control_required"
            and request.control == self._control
        ):
            self._control = None
        if not request.future.done():
            request.future.set_result(event)
        if isinstance(event, CommandAcceptedEvent) and request.command.type == "outputs.stop":
            self._stop_job_id = event.job.job_id
        if (
            isinstance(event, CommandCompletedEvent)
            and request.command.type == "job.get"
            and event.result.get("job_id") == self._stop_job_id
            and event.result.get("state") in {"completed", "failed", "cancelled"}
        ):
            self._stop_inflight = False
        if isinstance(event, CommandAcceptedEvent) and not request.internal:
            self._jobs[request.id] = _Tracked(
                request, event.job, asyncio.get_running_loop().time() + self._job_timeout
            )
        else:
            self._job_slots.discard(request.id)
        if not request.internal:
            self._publish(event)
        if isinstance(event, CommandAcceptedEvent) and not self._closed:
            self._job_wake.set()
            if event.job.state != "accepted":
                self._finish_job(request.id, event.job)
        if request.id == self.handshake_request_id and not self._ready.done():
            if isinstance(event, HelloCompletedEvent):
                self._ready.set_result(None)
            else:
                self._ready.set_exception(DeviceConnectionError("v3握手失败或设备身份不匹配"))
                self._ready.exception()
        if isinstance(event, CommandFailedEvent) and (
            request.command.type == "hello" or event.error.reason == "invalid_session"
        ):
            self._terminate(event.error)

    def _finish_job(self, rid: int, job: JobStatus) -> None:
        tracked = self._jobs.pop(rid, None)
        if tracked is None:
            return
        self._job_slots.discard(rid)
        req = tracked.request
        meta: dict[str, Any] = {
            "request_id": rid,
            "op": req.command.type,
            "boot_id": self._boot_id,
            "session": self._session,
            "job": job,
        }
        event: DeviceEvent
        if job.result_expired:
            event = self._failure(
                req, "result_expired", "作业结果已过期，不能据此确认执行结果", job.job_id, job
            )
        elif job.state == "completed":
            result = job.result or {}
            if req.command.type == "outputs.stop" and (
                result.get("cleanup_faults") != 0
                or result.get("persist_error") != 0
                or result.get("autostart_inhibited") is not True
            ):
                event = self._failure(
                    req, "stop_unconfirmed", "停止清理/持久化未确认", job.job_id, job
                )
            else:
                event = JobCompletedEvent(**meta)
        elif job.state == "cancelled":
            event = JobCancelledEvent(**meta)
        else:
            result = job.result or {}
            code = (
                job.error_code or result.get("error_code") or result.get("error") or "driver_error"
            )
            event = JobFailedEvent(
                **meta,
                error=DeviceError(
                    reason=str(code),
                    message=f"设备作业失败，driver_error={job.driver_error}",
                    external_effect_possible=job.external_effect_possible,
                    may_have_executed=job.external_effect_possible,
                ),
            )
        if req.command.type == "outputs.stop":
            self._stop_inflight = False
        self._publish(event)

    async def _rpc(self, op: Operation, params: dict[str, Any]) -> DeviceEvent:
        request = self._enqueue({"type": op, "params": params}, internal=True)
        return await asyncio.shield(request.future)

    async def _track_jobs(self, *, stop_only: bool = False) -> None:
        try:
            while not self._closed:
                try:
                    await asyncio.wait_for(self._job_wake.wait(), timeout=self._poll)
                except TimeoutError:
                    pass
                self._job_wake.clear()
                # Stop completion gets first query after any in-flight query releases the lane.
                ordered = sorted(
                    (
                        i
                        for i, tracked in self._jobs.items()
                        if (tracked.request.command.type == "outputs.stop") == stop_only
                    ),
                    key=lambda i: self._jobs[i].request.command.type != "outputs.stop",
                )
                for rid in ordered:
                    item = self._jobs.get(rid)
                    if item is None:
                        continue
                    if asyncio.get_running_loop().time() >= item.deadline:
                        self._jobs.pop(rid)
                        self._job_slots.discard(rid)
                        self._publish(
                            self._failure(
                                item.request,
                                "result_unknown",
                                "作业跟踪超时；可显式job.get查询，勿重试写操作",
                                item.job.job_id,
                            )
                        )
                        continue
                    try:
                        query = self._enqueue(
                            {"type": "job.get", "params": {"job_id": item.job.job_id}},
                            internal=True,
                        )
                    except QueueFullError:
                        break
                    try:
                        # Keep the read-only RPC owned by its writer after the job deadline.
                        # Cancelling its future would otherwise terminate the management lane.
                        reply = await asyncio.wait_for(
                            asyncio.shield(query.future),
                            timeout=max(0, item.deadline - asyncio.get_running_loop().time()),
                        )
                    except TimeoutError:
                        self._jobs.pop(rid, None)
                        self._job_slots.discard(rid)
                        self._publish(
                            self._failure(
                                item.request,
                                "result_unknown",
                                "作业跟踪期限已到，查询仍在途",
                                item.job.job_id,
                            )
                        )
                        continue
                    if self._closed:
                        return
                    if isinstance(reply, CommandFailedEvent):
                        if reply.error.reason == "timeout":
                            continue  # Read-only query may be repeated.
                        self._jobs.pop(rid, None)
                        self._job_slots.discard(rid)
                        failed = self._failure(
                            item.request,
                            reply.error.reason,
                            reply.error.message,
                            item.job.job_id,
                            item.job,
                        )
                        failed.error = reply.error.model_copy(deep=True)
                        failed.error.may_have_executed = item.request.sent
                        self._publish(failed)
                        continue
                    if not isinstance(reply, CommandCompletedEvent):
                        raise ProtocolError("job.get响应类型错误")
                    job = JobStatus.model_validate(reply.result)
                    if (
                        job.job_id != item.job.job_id
                        or job.resource != item.job.resource
                        or job.action != item.job.action
                    ):
                        raise ProtocolError("作业身份与受理结果不一致")
                    if job.state != "accepted":
                        self._finish_job(rid, job)
                if self._jobs:
                    await asyncio.sleep(self._poll)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- background boundary must terminate pending work
            self._terminate(
                DeviceError(reason="invalid_job_response", message=type(exc).__name__, source="sdk")
            )

    async def _heartbeat(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._heartbeat_interval)
                if any(r.command.type == "session.ping" for r in self._pending.values()):
                    continue
                try:
                    request = self._enqueue({"type": "session.ping", "params": {}}, internal=True)
                except QueueFullError:
                    continue
                started = asyncio.get_running_loop().time()
                try:
                    event = await asyncio.wait_for(
                        asyncio.shield(request.future),
                        timeout=min(self._timeout, self._heartbeat_interval),
                    )
                except TimeoutError:
                    event = self._failure(request, "timeout", "心跳回复未确认")
                    self._complete(request, event)
                if isinstance(event, CommandFailedEvent):
                    now = asyncio.get_running_loop().time()
                    lease = self._hello.session_timeout_ms / 1000 if self._hello else 0
                    if (
                        event.error.reason == "timeout"
                        and self._last_confirmed > started
                        and now - self._last_confirmed < lease - self._heartbeat_interval
                    ):
                        continue  # Another valid RPC confirms the same session and renews the lease.
                    self._terminate(
                        DeviceError(
                            reason="heartbeat_failed", source="sdk", message="会话租约无法确认"
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- heartbeat boundary
            self._terminate(
                DeviceError(reason="heartbeat_failed", message=type(exc).__name__, source="sdk")
            )

    @property
    def _job_limit(self) -> int:
        return min(8, max(0, self._hello.job_history - 1)) if self._hello else 8

    def _revoke(self, request: _Request) -> None:
        if not request.barrier_applied:
            request.barrier_applied = True
            self._control_epoch += 1
        self._control = None

    async def batch(self, commands: list[ClientEvent | ClientEventParam]) -> list[int]:
        if self._closed or not self._hello:
            raise DeviceConnectionError("需要有效会话")
        parsed = [parse_command(c) for c in commands]
        if not 1 <= len(parsed) <= self._hello.batch_max or any(c.type == "hello" for c in parsed):
            raise InvalidCommandError("batch需要1..设备batch_max项，hello必须单独发送")
        queue = self._stops if any(c.type == "outputs.stop" for c in parsed) else self._outgoing
        if queue.full():
            raise QueueFullError("batch通道已满")
        required = sum(c.type in JOB_OPERATIONS and c.type != "outputs.stop" for c in parsed)
        if len(self._job_slots) + required > self._job_limit:
            raise QueueFullError("batch超出可跟踪作业容量")
        encode_frame(
            [
                command_object(
                    c,
                    self._wire_sequence + i + 1,
                    session=self._session,
                    control=self._control,
                    seq=min(2147483647, self._send_sequence + i + 1),
                )
                for i, c in enumerate(parsed)
            ],
            maximum=self._hello.request_max,
        )
        requests = [self._enqueue(c, queue_it=False) for c in parsed]
        queue.put_nowait(requests)
        self._dispatch_wake.set()
        return [r.id for r in requests]

    @staticmethod
    def _frame_priority(requests: list[_Request]) -> int:
        if any(r.command.type == "outputs.stop" for r in requests):
            return 2
        return 1 if all(r.command.type in RPC_MANAGEMENT for r in requests) else 0

    def _next_frame(self):
        for lane, queue in ((2, self._stops), (1, self._management), (0, self._outgoing)):
            if self._lane_inflight[lane] >= (4 if lane == 1 else 1):
                continue
            for _ in range(queue.qsize()):
                item = queue.get_nowait()
                requests = item if isinstance(item, list) else [item]
                # State/capability queries use firmware's ordinary slot too. Never let
                # those overlap a write frame; admission drops would make writes unknown.
                if self._frame_priority(requests) == 0 and any(
                    r.sent and r.priority == 0 for r in self._pending.values()
                ):
                    queue.put_nowait(item)
                    continue
                urgent = requests[0].command.type in {"hello", "session.ping"} or (
                    requests[0].command.type == "job.get"
                    and requests[0].command.params.get("job_id") == self._stop_job_id
                )
                if lane == 1 and not urgent and self._management_regular >= 2:
                    queue.put_nowait(item)
                    continue
                self._lane_inflight[lane] += 1
                if lane == 1 and not urgent:
                    self._management_regular += 1
                return lane, urgent, item
        return None

    def _release_lane(self, lane: int, urgent: bool) -> None:
        self._lane_inflight[lane] -= 1
        if lane == 1 and not urgent:
            self._management_regular -= 1
        self._dispatch_wake.set()

    async def _watch_frame(
        self, lane: int, urgent: bool, requests: list[_Request], deadline: float
    ):
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*(r.future for r in requests))),
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
            )
        except TimeoutError:
            for request in requests:
                self._complete(request, self._failure(request, "timeout", "响应超时；勿重试写操作"))
        finally:
            self._release_lane(lane, urgent)

    async def _rotate_session(self) -> None:
        if self._sent_sequences:
            raise DeviceConnectionError("序号耗尽时仍有未确认发送，不能轮换会话")
        self._internal_sequence -= 1
        request = _Request(
            self._internal_sequence,
            parse_command({"type": "hello", "params": {}}),
            asyncio.get_running_loop().create_future(),
            self._session,
            None,
            internal=True,
            nonce=secrets.token_hex(16),
            epoch=self._control_epoch,
        )
        self._pending[request.id] = request
        await self._send_frame(request, 1)
        async with asyncio.timeout(self._timeout):
            reply = await asyncio.shield(request.future)
        if not isinstance(reply, HelloCompletedEvent):
            raise DeviceConnectionError("序号轮换握手失败")

    async def _send_frame(self, item: _Request | list[_Request], lane: int):
        requests = item if isinstance(item, list) else [item]
        is_batch = isinstance(item, list)
        stop = any(r.command.type == "outputs.stop" for r in requests)
        hello = requests[0].command.type == "hello"
        if not hello and self._send_sequence + len(requests) > 2147483647:
            await self._rotate_session()
        if not hello:
            await self._session_ready.wait()
        active = []
        for request in requests:
            mutation = control_required(request.command) or request.command.type in {
                "control.acquire",
                "event.subscribe",
                "event.unsubscribe",
            }
            if (
                control_required(request.command)
                and (request.control != self._control or request.epoch != self._control_epoch)
            ) or (mutation and self._stop_inflight and not stop):
                self._complete(
                    request, self._failure(request, "control_revoked", "控制绑定已撤销，未发送")
                )
            else:
                active.append(request)
        if is_batch and len(active) != len(requests):
            for request in active:
                self._complete(request, self._failure(request, "batch_rejected", "整批未发送"))
            return [], 0.0
        if not active:
            return [], 0.0
        window = self._hello.sequence_window if self._hello else 64
        reserve = 0 if stop else 1 if lane == 1 else 4
        oldest = min(self._sent_sequences.values(), default=self._send_sequence + 1)
        if not hello and self._send_sequence + len(active) - oldest >= window - reserve:
            # Keep tombstones for timed-out writes; never slide past an unresolved request.
            for request in active:
                self._complete(
                    request,
                    self._failure(
                        request,
                        "sequence_window_blocked",
                        "序号窗口未释放，本帧未发送；停止保留位置仍可用",
                    ),
                )
            return [], 0.0
        objects = []
        for request in active:
            self._wire_sequence += 1
            request.wire_id = self._wire_sequence
            if request.command.type != "hello":
                self._send_sequence += 1
                request.seq = self._send_sequence
            if not control_required(request.command):
                request.session = self._session
                if request.epoch != self._control_epoch:
                    request.control = None
            objects.append(
                command_object(
                    request.command,
                    request.wire_id,
                    session=request.session,
                    control=request.control,
                    seq=request.seq or 1,
                    client_nonce=request.nonce,
                )
            )
        try:
            data = encode_frame(
                objects if is_batch else objects[0],
                maximum=self._hello.request_max if self._hello else 1024,
            )
        except InvalidCommandError:
            for request in active:
                self._complete(
                    request, self._failure(request, "frame_too_large", "整帧超过设备请求容量")
                )
            return [], 0.0
        priority = self._frame_priority(active)
        for request in active:
            request.priority = priority
            request.frame_high_seq = self._send_sequence
            assert request.wire_id is not None
            self._wire_pending[request.wire_id] = request
            if request.seq is not None:
                self._sent_sequences[request.wire_id] = request.seq
            request.sent = True
            if request.command.type == "outputs.stop":
                # Fail closed while the stop reply is in flight, including response loss.
                self._revoke(request)
        deadline = asyncio.get_running_loop().time() + self._timeout
        try:
            await asyncio.wait_for(self._transport.write(data), timeout=min(3, self._timeout))
        except TimeoutError:
            self._terminate(
                DeviceError(
                    reason="write_timeout", source="sdk", message="半帧写入超时，请重连查询"
                )
            )
            return [], 0.0
        return active, deadline

    async def _writer(self) -> None:
        try:
            while not self._closed:
                self._dispatch_wake.clear()
                frame = self._next_frame()
                if frame is None:
                    await self._dispatch_wake.wait()
                    continue
                lane, urgent, item = frame
                active, deadline = await self._send_frame(item, lane)
                if not active:
                    self._release_lane(lane, urgent)
                    continue
                task = asyncio.create_task(
                    self._watch_frame(lane, urgent, active, deadline), name="limivia-rpc-deadline"
                )
                self._rpc_tasks.add(task)
                task.add_done_callback(self._rpc_tasks.discard)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- transport boundary
            logger.debug("传输写入失败：%s", type(exc).__name__)
            self._terminate(
                DeviceError(reason="connection_lost", message=type(exc).__name__, source="sdk")
            )

    def _confirm_frame(self, request: _Request) -> None:
        self._last_confirmed = asyncio.get_running_loop().time()
        # USB/BLE/WS/MQTT preserve frame delivery order. Firmware queues are FIFO per RPC
        # priority, and a batch registers all seq before dispatch. A later valid response
        # in the same queue proves older frames were admitted or dropped, even if TX lost
        # their replies. Keep original futures/deadlines; never invent a response or replay.
        for wire_id, seq in list(self._sent_sequences.items()):
            earlier = self._wire_pending.get(wire_id)
            if (
                earlier is not None
                and earlier.priority == request.priority
                and seq <= request.frame_high_seq
            ):
                self._sent_sequences.pop(wire_id, None)
                if earlier.id not in self._pending:
                    self._wire_pending.pop(wire_id, None)

    def _message(self, message: Any) -> None:
        if not isinstance(message, dict):
            self._publish(ProtocolErrorEvent(message="设备响应项需要对象"))
            return
        request = None
        if "method" in message and "id" not in message:
            context = message.get("params", {})
            context = (
                (context[0] if context else {})
                if isinstance(context, list)
                else context.get("context", {})
            )
            if not isinstance(context, dict):
                raise ProtocolError("通知context无效")
            if context.get("boot_id") != self._boot_id or context.get("session") != self._session:
                return
        else:
            wire_id = message.get("id")
            if not valid_id(wire_id):
                raise ProtocolError("响应ID无效")
            request = self._wire_pending.get(wire_id) if type(wire_id) is int else None
            if request is None:
                if type(wire_id) is int and 1 <= wire_id <= self._wire_sequence:
                    return  # Retired RPC: late/duplicate internal replies stay private.
                if "error" in message:
                    event = decode_message(message)
                    if isinstance(event, RpcErrorEvent):
                        self._publish(event)
                return
            context = response_context(message)
            if request.command.type != "hello":
                if context.get("boot_id") != self._boot_id:
                    self._terminate(
                        DeviceError(reason="boot_changed", source="sdk", message="设备已重启")
                    )
                    return
                if context.get("session") != request.session:
                    self._terminate(
                        DeviceError(
                            reason="session_changed", source="sdk", message="设备会话已失效"
                        )
                    )
                    return
            if request.id not in self._pending:
                # Late response after an SDK timeout retires the tombstone without a second event.
                decode_message(message, request.command.type, request_id=request.id)
                self._confirm_frame(request)
                self._wire_pending.pop(request.wire_id, None)  # type: ignore[arg-type]
                self._sent_sequences.pop(request.wire_id, None)  # type: ignore[arg-type]
                return
        try:
            event = decode_message(
                message,
                request.command.type if request else None,
                request_id=request.id if request else None,
            )
        except ProtocolError:
            if request:
                self._complete(
                    request, self._failure(request, "invalid_response", "设备响应字段无效")
                )
            else:
                self._publish(ProtocolErrorEvent(message="设备通知字段无效"))
            return
        if request:
            self._confirm_frame(request)
            self._complete(request, event)
        else:
            if event.type in ("job.finished", "state.changed", "data.available"):
                expected = self._last_notification + 1
                if event.event_sequence < expected:
                    return
                if event.event_sequence != expected or event.dropped:
                    self._publish(
                        NotificationGapEvent(
                            boot_id=event.boot_id,
                            session=event.session,
                            expected=expected,
                            received=event.event_sequence,
                            dropped=event.dropped,
                        )
                    )
                self._last_notification = event.event_sequence
                if event.type == "job.finished":
                    self._job_wake.set()
            self._publish(event)

    async def _read(self) -> None:
        reader = LineReader()
        read_task = None
        try:
            while not self._closed:
                if read_task is None:
                    read_task = asyncio.create_task(self._transport.read())
                ready, _ = await asyncio.wait({read_task}, timeout=0.2)
                if not ready:
                    for error in reader.expire():
                        self._publish(ProtocolErrorEvent(message=str(error)))
                    continue
                data = read_task.result()
                read_task = None
                if not data:
                    raise ConnectionError("连接已断开")
                reader.max_length = self._hello.response_max if self._hello else 8192
                lines: list[str | ProtocolError]
                if getattr(self._transport, "message_framed", False):
                    if len(data.removesuffix(b"\n")) > reader.max_length:
                        raise ProtocolError("设备消息超过响应容量")
                    lines = [data.decode("utf-8", errors="strict")]
                else:
                    lines = reader.feed(data)
                for line in lines:
                    if self._closed:
                        return
                    if isinstance(line, ProtocolError):
                        self._publish(ProtocolErrorEvent(message=str(line)))
                        continue
                    try:
                        decoded = load_json(line)
                        messages = decoded if isinstance(decoded, list) else [decoded]
                        if not messages or len(messages) > (
                            self._hello.batch_max if self._hello else 8
                        ):
                            raise ProtocolError("响应batch数量无效")
                        # Apply every accepted stop barrier before any token binding in this frame.
                        for message in messages:
                            if not isinstance(message, dict):
                                continue
                            rid = message.get("id")
                            request = self._wire_pending.get(rid) if type(rid) is int else None
                            if (
                                request
                                and request.command.type == "outputs.stop"
                                and (
                                    "result" in message
                                    or message.get("error", {})
                                    .get("data", {})
                                    .get("external_effect_possible")
                                )
                            ) and response_context(message).get("session") == request.session:
                                self._revoke(request)
                        for message in messages:
                            self._message(message)
                    except (ValueError, TypeError, AttributeError, RecursionError):
                        self._publish(ProtocolErrorEvent(message="设备JSON-RPC帧无效"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- background boundary
            logger.debug("传输读取失败：%s", type(exc).__name__)
            self._terminate(
                DeviceError(reason="connection_lost", message=type(exc).__name__, source="sdk")
            )
        finally:
            if read_task is not None:
                read_task.cancel()
                await asyncio.gather(read_task, return_exceptions=True)

    async def discover(self, *, refresh: bool = False) -> int:
        from ._aggregate import start

        return start(self, "discover", refresh=refresh)

    async def _state_snapshot(self) -> int:
        from ._aggregate import start

        return start(self, "state.snapshot")

    def _terminate(self, error: DeviceError | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._discovery = None
        self.identity = None
        self._control = None
        for rid, op in self._aggregate_requests.items():
            self._terminal.append(
                CommandFailedEvent(
                    request_id=rid,
                    op=op,
                    error=DeviceError(
                        reason="result_unknown", message="聚合查询期间连接终止", source="sdk"
                    ),
                )
            )
        self._aggregate_requests.clear()
        for task in (*self._aggregate_tasks, *self._rpc_tasks):
            task.cancel()
        if not self._ready.done():
            self._ready.set_exception(
                DeviceConnectionError(error.message if error else "握手前关闭连接")
            )
            self._ready.exception()
        for request in self._pending.values():
            event = self._failure(
                request,
                error.reason if error else "cancelled",
                error.message if error else "SDK连接关闭",
            )
            if not request.future.done():
                request.future.set_result(event)
            if not request.internal:
                self._terminal.append(event)
        for tracked in self._jobs.values():
            self._terminal.append(
                self._failure(
                    tracked.request,
                    "result_unknown",
                    "连接终止，设备作业未确认终态",
                    tracked.job.job_id,
                )
            )
        self._pending.clear()
        self._wire_pending.clear()
        self._jobs.clear()
        self._job_slots.clear()
        self._terminal.append(ConnectionClosedEvent(error=error))
        self._wake.set()
        self._cleanup_task = asyncio.create_task(self._cleanup(), name="limivia-cleanup")

    async def _cleanup(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(
            *self._tasks, *self._aggregate_tasks, *self._rpc_tasks, return_exceptions=True
        )
        try:
            await asyncio.wait_for(self._transport.close(), timeout=5)
        except Exception:  # noqa: BLE001 -- cleanup must preserve the original failure
            for event in self._terminal:
                if isinstance(event, ConnectionClosedEvent) and event.error is None:
                    event.error = DeviceError(
                        reason="close_failed", message="传输资源释放失败", source="sdk"
                    )

    async def close(self) -> None:
        self._terminate()
        assert self._cleanup_task is not None
        with CancelScope(shield=True):
            try:
                await asyncio.shield(self._cleanup_task)
            except asyncio.CancelledError:
                await asyncio.shield(self._cleanup_task)
                raise
