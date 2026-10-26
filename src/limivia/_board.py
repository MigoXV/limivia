"""等待设备确认的异步业务门面；底层提交入口保留在 raw。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Literal

from ._connection import AsyncConnection
from ._dispatch import Dispatcher, EventStream, Ticket, check, payload
from ._exceptions import DeviceConnectionError, InvalidCommandError, OperationError
from ._lifecycle import cleanup
from .constants import ErrorReason, EventType, JobState, NotificationTopic, OperationName, QueryName
from .protocol import JOB_OPERATIONS, control_required, parse_command
from .resources import Resources
from .types import (
    CapabilitiesPage,
    ClientEvent,
    ClientEventParam,
    DeviceDiscovery,
    DeviceEvent,
    DeviceIdentity,
    Diagnostics,
    JobStatus,
    ResourceInfo,
    StatePage,
    StateSnapshot,
)
from .types.results import OperationResult

Topic = Literal["job", "resource", "flow", "data"]


class AsyncRaw(Resources[Awaitable[int]]):
    """显式低层提交；单个订阅单个消费者，业务等待独立分发。"""

    def __init__(self, board: AsyncBoard):
        self._board = board
        self._core = board._core
        self._stream = board._hub.stream(raw=True)
        super().__init__(self.send, snapshot=self._state_snapshot)

    @property
    def identity(self) -> DeviceIdentity | None:
        return self._core.identity

    @property
    def handshake_request_id(self) -> int:
        return self._core.handshake_request_id

    async def send(self, event: ClientEvent | ClientEventParam) -> int:
        return await self._core.send(event)

    async def hello(self, *, client_nonce: str | None = None) -> int:
        return await self._core.hello(client_nonce=client_nonce)

    async def discover(self, *, refresh: bool = False) -> int:
        return await self._core.discover(refresh=refresh)

    async def _state_snapshot(self) -> int:
        return await self._core._state_snapshot()

    async def batch(self, commands: list[ClientEvent | ClientEventParam]) -> list[int]:
        return await self._core.batch(commands)

    def __aiter__(self):
        return self

    async def __anext__(self) -> DeviceEvent:
        return await self.recv()

    async def recv(self) -> DeviceEvent:
        return await anext(self._stream)

    def subscribe(self, *, queue_size: int | None = None) -> EventStream:
        return self._board._hub.stream(size=queue_size, raw=True)

    async def close(self) -> None:
        await self._board.close()


class AsyncControl:
    def __init__(self, board: AsyncBoard):
        self.board = board

    async def acquire(self) -> None:
        await self.board._ensure_control()

    async def release(self) -> None:
        async with self.board._control_lock:
            ticket = self.board._hub.submit({"type": OperationName.CONTROL_RELEASE, "params": {}})
            await ticket.wait()


class AsyncState:
    def __init__(self, board: AsyncBoard):
        self.board = board

    async def retrieve(self, *, page: int | None = None, revision: int | None = None) -> StatePage:
        args = {k: v for k, v in {"page": page, "revision": revision}.items() if v is not None}
        event = await self.board._request(OperationName.STATE, args, control=False)
        assert event.type == EventType.STATE_COMPLETED
        return event.result

    async def snapshot(self) -> StateSnapshot:
        event = await self.board._hub.aggregate(QueryName.STATE_SNAPSHOT).wait()
        assert event.type == EventType.STATE_SNAPSHOT_COMPLETED
        return event.result


class AsyncCapabilities:
    def __init__(self, board: AsyncBoard):
        self.board = board

    async def retrieve(self, *, page: int | None = None) -> CapabilitiesPage:
        event = await self.board._request(
            OperationName.CAPABILITIES, {} if page is None else {"page": page}, control=False
        )
        assert event.type == EventType.CAPABILITIES_COMPLETED
        return event.result


class AsyncDiagnostics:
    def __init__(self, board: AsyncBoard):
        self.board = board

    async def retrieve(self) -> Diagnostics:
        event = await self.board._request(OperationName.DIAGNOSTICS, {}, control=False)
        assert event.type == EventType.DIAGNOSTICS_COMPLETED
        return event.result


class AsyncJob:
    def __init__(self, board: AsyncBoard, ticket: Ticket | None, job: JobStatus):
        self._board = board
        self._ticket = ticket
        self._status = job
        self._boot = board.identity.boot_id if board.identity else None

    @property
    def id(self) -> int:
        return self._status.job_id

    @property
    def request_id(self) -> int | None:
        return self._ticket.request_id if self._ticket else None

    def _check(self):
        if self._board.identity is None or self._board.identity.boot_id != self._boot:
            raise DeviceConnectionError("作业所属连接/boot 已失效")

    async def status(self) -> JobStatus:
        self._check()
        event = await self._board._request(
            OperationName.JOB_GET, {"job_id": self.id}, control=False
        )
        self._status = JobStatus.model_validate(payload(event))
        return self._status.model_copy(deep=True)

    async def cancel(self) -> JobStatus:
        self._check()
        event = await self._board._request(OperationName.JOB_CANCEL, {"job_id": self.id})
        return JobStatus.model_validate(payload(event))

    async def wait(self, *, timeout: float | None = None) -> OperationResult:
        if self._ticket is not None:
            return OperationResult(data=payload(await self._ticket.wait(timeout=timeout)))
        self._check()

        # 已知 job 的显式恢复仅查询，不重发原操作。
        async def query():
            while True:
                status = await self.status()
                if status.state != JobState.ACCEPTED:
                    from .types import (
                        DeviceError,
                        JobCancelledEvent,
                        JobCompletedEvent,
                        JobFailedEvent,
                    )

                    meta: dict[str, Any] = {
                        "request_id": 0,
                        "op": OperationName.JOB_GET,
                        "job": status,
                    }
                    if status.result_expired:
                        from ._exceptions import ResultUnknownError

                        raise ResultUnknownError("作业结果已过期", job=status)
                    if status.state == JobState.FAILED:
                        check(
                            JobFailedEvent(
                                **meta,
                                error=DeviceError(
                                    reason=status.error_code or ErrorReason.DRIVER_ERROR,
                                    external_effect_possible=status.external_effect_possible,
                                ),
                            )
                        )
                    elif status.state == JobState.CANCELLED:
                        check(JobCancelledEvent(**meta))
                    return OperationResult(data=payload(JobCompletedEvent(**meta)))
                await asyncio.sleep(self._board._core._poll)

        try:
            async with asyncio.timeout(timeout or self._board._core._job_timeout):
                return await query()
        except TimeoutError as exc:
            if isinstance(exc, OperationError):
                raise
            from ._exceptions import ResultUnknownError

            raise ResultUnknownError("查询作业超时，执行结果未知", job=self._status) from None


class AsyncJobs:
    def __init__(self, board: AsyncBoard):
        self.board = board

    async def submit(self, command: ClientEvent | ClientEventParam) -> AsyncJob:
        parsed = parse_command(command)
        if parsed.type not in JOB_OPERATIONS:
            raise InvalidCommandError("该操作不产生设备作业，请使用普通业务方法或 raw")
        direct = parsed.type == OperationName.RESOURCE_OPEN and parsed.params.get("kind") == "gpio"
        if parsed.type == OperationName.RESOURCE_CALL:
            info = await self.board._resource_info(parsed.params["resource"])
            direct = (
                info.kind == "gpio" and parsed.params["action"] in {"read", "write", "status"}
            ) or (info.kind == "pwm" and parsed.params["action"] in {"duty", "status"})
        if direct:
            raise InvalidCommandError(
                "该操作直接返回确认结果，不产生公开作业；请使用业务方法或 raw"
            )
        await self.board._prepare(parsed)
        ticket = self.board._hub.submit(parsed)
        event = await ticket.wait(accepted=True)
        if event.type != EventType.COMMAND_ACCEPTED:
            raise InvalidCommandError("设备未返回作业；响应已保留在 raw 订阅")
        return AsyncJob(self.board, ticket, event.job)

    async def get(self, job_id: int) -> AsyncJob:
        event = await self.board._request(OperationName.JOB_GET, {"job_id": job_id}, control=False)
        return AsyncJob(self.board, None, JobStatus.model_validate(payload(event)))


class AsyncSubscription:
    def __init__(
        self,
        owner: AsyncNotifications,
        topics: list[Topic],
        interval_ms: int,
        queue_size: int | None,
    ):
        if not topics or set(topics) - {
            NotificationTopic.JOB,
            NotificationTopic.RESOURCE,
            NotificationTopic.FLOW,
            NotificationTopic.DATA,
        }:
            raise ValueError("topics 需要 job/resource/flow/data")
        if type(interval_ms) is not int or not 10 <= interval_ms <= 60000:
            raise ValueError("interval_ms 需要 10..60000")
        self.owner = owner
        self.topics = topics
        self.interval = interval_ms
        self.size = queue_size
        self.stream: EventStream | None = None
        self.entered = False

    async def __aenter__(self):
        if self.entered:
            raise RuntimeError("订阅上下文不能重复使用")
        self.entered = True
        async with self.owner.lock:
            self.stream = self.owner.board._hub.stream(size=self.size)
            self.stream.topics = set(self.topics)
            self.owner.active.add(self)
            try:
                await self.owner.update()
            except BaseException:
                self.owner.active.discard(self)
                self.stream.close()
                raise
        return self.stream

    async def __aexit__(self, exc_type, exc, tb):
        async def release():
            async with self.owner.lock:
                self.owner.active.discard(self)
                if self.stream:
                    self.stream.close()
                if not self.owner.board._core._closed:
                    await self.owner.update()

        await cleanup(release(), exc, self.owner.board._cleanup_timeout)


class AsyncNotifications:
    def __init__(self, board: AsyncBoard):
        self.board = board
        self.lock = asyncio.Lock()
        self.active: set[AsyncSubscription] = set()

    def subscribe(
        self, *, topics: list[Topic], interval_ms: int = 100, queue_size: int | None = None
    ) -> AsyncSubscription:
        return AsyncSubscription(self, topics, interval_ms, queue_size)

    async def update(self):
        topics = sorted({t for sub in self.active for t in sub.topics})
        if topics:
            await self.board._request(
                OperationName.EVENT_SUBSCRIBE,
                {
                    "topics": topics,
                    "interval_ms": min(sub.interval for sub in self.active),
                },
                control=False,
            )
        else:
            await self.board._request(OperationName.EVENT_UNSUBSCRIBE, {}, control=False)


class AsyncBoard:
    def __init__(self, core: AsyncConnection):
        from ._peripherals import AsyncADC, AsyncGPIO, AsyncPWM, AsyncResources, AsyncUART

        self._core = core
        self._hub = Dispatcher(core)
        self._raw: AsyncRaw | None = None
        self._control_lock = asyncio.Lock()
        self._control_task: asyncio.Task | None = None
        self._cleanup_timeout = core._job_timeout + core._timeout
        self._owned: list[Any] = []
        self._operations: set[asyncio.Task] = set()
        self._closing = False
        self._close_task: asyncio.Task | None = None
        commands = Resources(self._execute)
        self.session = commands.session
        self.outputs = commands.outputs
        self.capabilities = AsyncCapabilities(self)
        self.mux = commands.mux
        self.buffer = commands.buffer
        self.storage = commands.storage
        self.ota = commands.ota
        self.wifi = commands.wifi
        self.mqtt = commands.mqtt
        self.espnow = commands.espnow
        self.power = commands.power
        self.system = commands.system
        self.flow = commands.flow
        self.rmt = commands.rmt
        self.control = AsyncControl(self)
        self.state = AsyncState(self)
        self.diagnostics = AsyncDiagnostics(self)
        self.jobs = AsyncJobs(self)
        self.notifications = AsyncNotifications(self)
        self.resources = AsyncResources(self)
        self.gpio = AsyncGPIO(self)
        self.pwm = AsyncPWM(self)
        self.adc = AsyncADC(self)
        self.uart = AsyncUART(self)

    @property
    def identity(self) -> DeviceIdentity | None:
        return self._core.identity

    @property
    def raw(self) -> AsyncRaw:
        if self._raw is None:
            self._raw = AsyncRaw(self)
        return self._raw

    async def _ensure_control(self):
        async with self._control_lock:
            if self._core._control is None:
                if self._control_task is None or self._control_task.done():
                    ticket = self._hub.submit({"type": OperationName.CONTROL_ACQUIRE, "params": {}})
                    self._control_task = asyncio.create_task(ticket.wait())
                    self._control_task.add_done_callback(
                        lambda task: task.exception() if not task.cancelled() else None
                    )
                await asyncio.shield(self._control_task)
                if self._core._control is None:
                    raise DeviceConnectionError("控制权申请已被停止或会话轮换撤销")

    async def _prepare(self, command: ClientEvent, control: bool | None = None):
        if self._core._closed:
            raise DeviceConnectionError("设备连接已关闭")
        if control if control is not None else control_required(command):
            await self._ensure_control()

    async def _request(
        self, op: str, args: dict[str, Any], *, control: bool | None = None
    ) -> DeviceEvent:
        command = parse_command({"type": op, "params": args})
        await self._prepare(command, control)
        return await self._hub.submit(command, control=control).wait()

    async def _execute(self, command: ClientEvent | ClientEventParam) -> OperationResult:
        parsed = parse_command(command)
        event = await self._request(parsed.type, parsed.params)
        value = payload(event)
        return OperationResult(data=value.model_dump() if hasattr(value, "model_dump") else value)

    async def discover(self, *, refresh: bool = False) -> DeviceDiscovery:
        event = await self._hub.aggregate(QueryName.DISCOVER, refresh=refresh).wait()
        assert event.type == EventType.DISCOVERY_COMPLETED
        return event.result

    async def _resource_info(self, resource: int) -> ResourceInfo:
        event = await self._request(
            OperationName.RESOURCE_GET, {"resource": resource}, control=False
        )
        assert event.type == EventType.RESOURCE_GET_COMPLETED
        return event.result

    async def _close(self):
        self._closing = True
        original: BaseException | None = None
        try:
            async with asyncio.timeout(self._cleanup_timeout):
                await self._close_resources()
        except BaseException as exc:
            original = exc
            raise
        finally:
            try:
                await cleanup(self._core.close(), original, 6)
            finally:
                await asyncio.gather(*self._operations, return_exceptions=True)

    async def _close_resources(self):
        error: BaseException | None = None
        for resource in reversed(self._owned.copy()):
            try:
                await resource.close()
            except Exception as exc:  # noqa: BLE001 -- continue closing other owned resources
                if error is None:
                    error = exc
                else:
                    from ._lifecycle import record_cleanup

                    record_cleanup(error, exc)
        if error:
            raise error

    async def close(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(), name="limivia-board-close")
        await asyncio.shield(self._close_task)

    async def _exit(self, original: BaseException | None):
        await cleanup(self.close(), original, self._cleanup_timeout + 6)
