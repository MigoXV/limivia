"""资源对象拥有协议 ID、实例和生命周期；业务调用只接触业务参数。"""

from __future__ import annotations

import asyncio
import base64
import struct
from typing import TYPE_CHECKING, Any, Self, Unpack

from ._dispatch import Ticket, payload
from ._exceptions import (
    DeviceConnectionError,
    DeviceRejectedError,
    OperationError,
    ResourceCleanupError,
)
from ._lifecycle import cleanup
from .constants import (
    ErrorReason,
    EventType,
    GPIOMode,
    Level,
    OperationName,
    PeripheralKind,
    ResourceAction,
    ResourceState,
)
from .types import BinaryResult, ResourceInfo, ResourceKind
from .types.results import (
    ADCSample,
    GPIOConfig,
    OperationResult,
    PeripheralEvents,
    PWMConfig,
    UARTConfig,
)

if TYPE_CHECKING:
    from ._board import AsyncBoard


class AsyncResource:
    def __init__(
        self,
        board: AsyncBoard,
        kind: ResourceKind,
        pins: dict[str, int],
        config: dict[str, Any],
        *,
        parent: AsyncResource | None = None,
        controller: int | None = None,
    ):
        self._board = board
        self.kind = kind
        self._args: dict[str, Any] = {"kind": kind, "pins": pins, "config": config}
        self._parent = parent
        if controller is not None:
            self._args["controller"] = controller
        self._boot = board.identity.boot_id if board.identity else None
        self._info: ResourceInfo | None = None
        self._ticket: Ticket | None = None
        self._opening: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._closing = False
        self._entered = False

    @property
    def info(self) -> ResourceInfo | None:
        """高级诊断快照；业务方法无需读取其中的资源 ID。"""
        return self._info.model_copy(deep=True) if self._info else None

    def _identity(self):
        if self._board.identity is None or self._board.identity.boot_id != self._boot:
            raise DeviceConnectionError("资源所属连接/boot 已失效")

    async def _validate(self) -> ResourceInfo:
        self._identity()
        if self._info is None:
            raise DeviceConnectionError("资源尚未打开；请进入上下文或显式 open()")
        current = await self._board._resource_info(self._info.id)
        if current.instance != self._info.instance:
            raise DeviceConnectionError("资源实例已变化，旧句柄失效")
        return current

    async def _do_open(self):
        self._identity()
        if self._parent:
            if self._parent._board is not self._board:
                raise ValueError("父资源必须来自同一连接")
            info = await self._parent._validate()
            self._args["parent"] = info.id
        from .protocol import parse_command

        command = parse_command({"type": OperationName.RESOURCE_OPEN, "params": self._args})
        await self._board._prepare(command)
        self._ticket = self._board._hub.submit(command)
        event = await self._ticket.wait()
        if event.type != EventType.JOB_COMPLETED or not event.job.resource:
            raise DeviceConnectionError("资源打开响应缺少确认的资源身份")
        self._info = await self._board._resource_info(event.job.resource)
        if self._info.state != ResourceState.READY:
            raise DeviceConnectionError(f"资源未就绪：{self._info.state}")
        return self

    async def open(self) -> Self:
        if self._closed or self._closing or self._board._closing:
            raise DeviceConnectionError("资源或连接正在关闭")
        if self._opening is None:
            self._board._owned.append(self)
            self._opening = asyncio.create_task(self._do_open(), name="limivia-resource-open")
        try:
            await asyncio.shield(self._opening)
        except BaseException as exc:
            await cleanup(self.close(), exc, self._board._cleanup_timeout)
            raise
        return self

    def __await__(self):
        return self.open().__await__()

    async def __aenter__(self) -> Self:
        if self._entered:
            raise RuntimeError("资源上下文不能重复使用")
        self._entered = True
        return await self.open()

    async def __aexit__(self, exc_type, exc, tb):
        await cleanup(self.close(), exc, self._board._cleanup_timeout)

    async def call(
        self, action: str, *, timeout_ms: int | None = None, **args: Any
    ) -> OperationResult:
        async def perform():
            async with self._lock:
                if self._closed or self._closing or self._board._closing:
                    raise DeviceConnectionError("资源已关闭或正在关闭")
                info = await self._validate()
                if timeout_ms is not None:
                    args["timeout_ms"] = timeout_ms
                observer = action == ResourceAction.STATUS or (self.kind, action) in {
                    (PeripheralKind.GPIO, ResourceAction.READ),
                    (PeripheralKind.TEMPERATURE, ResourceAction.READ),
                    (PeripheralKind.TWAI, ResourceAction.INFO),
                }
                event = await self._board._request(
                    OperationName.RESOURCE_CALL,
                    {
                        "resource": info.id,
                        "action": action,
                        "args": args,
                    },
                    control=not observer,
                )
                return OperationResult(data=payload(event))

        # 锁由后台操作持有；取消调用者只取消等待，不允许 close 越过在途操作。
        task = asyncio.create_task(perform(), name="limivia-resource-call")
        self._board._operations.add(task)

        def finished(done):
            self._board._operations.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def status(self) -> OperationResult:
        return await self.call(ResourceAction.STATUS)

    async def _resolve_open(self):
        if self._opening is not None:
            try:
                await asyncio.shield(self._opening)
            except Exception:  # noqa: BLE001, S110 -- open failure is already owned by the caller
                pass
        if self._info is None and self._ticket and self._ticket.job:
            resource_id = self._ticket.job.resource
            if resource_id:
                self._info = await self._board._resource_info(resource_id)
        if self._info is None and self._ticket and self._ticket.terminal.done():
            event = self._ticket.terminal.result()
            if event.type == EventType.COMMAND_FAILED and event.error.may_have_executed:
                raise ResourceCleanupError(
                    "资源打开可能已执行但未获得资源身份，无法确认释放",
                    request_id=event.request_id,
                    error=event.error,
                    may_have_executed=True,
                )
        if self._info:
            while self._info.state == ResourceState.OPENING:
                await asyncio.sleep(self._board._core._poll)
                self._info = await self._board._resource_info(self._info.id)

    async def _close(self, cascade: bool, recover: bool):
        try:
            async with asyncio.timeout(self._board._cleanup_timeout):
                async with self._lock:
                    await self._resolve_open()
                    if self._info is not None:
                        await self._validate()
                        op = (
                            OperationName.RESOURCE_RECOVER
                            if recover
                            else OperationName.RESOURCE_CLOSE
                        )
                        args: dict[str, Any] = {"resource": self._info.id}
                        if cascade:
                            args["cascade"] = True
                        tree = [self._info]
                        if cascade:
                            snapshot = await self._board.state.snapshot()
                            ids = {self._info.id}
                            for _ in snapshot.resources:
                                ids.update(r.id for r in snapshot.resources if r.parent in ids)
                            tree = [r for r in snapshot.resources if r.id in ids]
                            if not tree:
                                tree = [self._info]
                        await self._board._request(op, args)
                        # cascade RPC 仅确认 closing；普通 close 也确认资源已删除。
                        for original in tree:
                            while True:
                                try:
                                    current = await self._board._resource_info(original.id)
                                except DeviceRejectedError as exc:
                                    if (
                                        exc.error
                                        and exc.error.reason == ErrorReason.RESOURCE_NOT_FOUND
                                    ):
                                        break
                                    raise
                                if current.instance != original.instance:
                                    break
                                if current.state == ResourceState.FAULT:
                                    error = ResourceCleanupError("资源关闭后进入 fault，仍保留占用")
                                    error.resource_info = current
                                    raise error
                                await asyncio.sleep(self._board._core._poll)
                        if cascade:
                            removed = {(r.id, r.instance) for r in tree}
                            for owned in self._board._owned.copy():
                                if (
                                    owned is not self
                                    and owned._info
                                    and (owned._info.id, owned._info.instance) in removed
                                ):
                                    owned._closed = True
                                    self._board._owned.remove(owned)
            self._closed = True
            if self in self._board._owned:
                self._board._owned.remove(self)
        except Exception as exc:
            if isinstance(exc, ResourceCleanupError):
                raise
            error = ResourceCleanupError(
                "资源释放未确认",
                request_id=getattr(exc, "request_id", None),
                error=getattr(exc, "error", None),
                job=getattr(exc, "job", None),
                may_have_executed=getattr(exc, "may_have_executed", False),
            )
            error.resource_info = self.info
            if self._info is not None and not self._board._core._closed:
                try:
                    error.resource_info = await self._board._resource_info(self._info.id)
                except (OperationError, DeviceConnectionError):
                    pass  # 原始清理错误保持权威；诊断查询也可能失败。
            raise error from exc

    async def close(self, *, cascade: bool = False) -> None:
        if self._closed:
            return
        if self._close_task is None:
            self._closing = True
            self._close_task = asyncio.create_task(self._close(cascade, False))
        await asyncio.shield(self._close_task)

    async def recover(self, *, cascade: bool = False) -> None:
        """显式重试清理，不重新打开；普通退出不重放失败的关闭。"""
        if self._closed:
            return
        if self._close_task and not self._close_task.done():
            await asyncio.shield(self._close_task)
            return
        self._close_task = asyncio.create_task(self._close(cascade, True))
        await asyncio.shield(self._close_task)


class AsyncGPIOPin(AsyncResource):
    async def read(self) -> int:
        return (await self.call(ResourceAction.READ)).data["level"]

    async def write(self, value: int) -> None:
        await self.call(ResourceAction.WRITE, level=value)

    async def events(self) -> PeripheralEvents:
        return PeripheralEvents.model_validate((await self.call(ResourceAction.EVENTS)).data)


class AsyncPWMOutput(AsyncResource):
    async def set_duty(self, duty: float) -> None:
        await self.call(ResourceAction.DUTY, duty=duty)

    async def fade(self, duty: float, *, duration_ms: int) -> None:
        """等待驱动启动渐变；固件不提供渐变物理结束确认。"""
        await self.call(ResourceAction.FADE, duty=duty, duration_ms=duration_ms)


class AsyncADCInput(AsyncResource):
    async def read(self) -> ADCSample:
        return ADCSample.model_validate((await self.call(ResourceAction.READ)).data)

    async def events(self) -> list[ADCSample]:
        packet = PeripheralEvents.model_validate((await self.call(ResourceAction.EVENTS)).data)
        samples = []
        for event in packet.events:
            data = base64.b64decode(event.data, validate=True)
            if len(data) != 8 or base64.b64encode(data).decode() != event.data:
                from ._exceptions import ProtocolError

                raise ProtocolError("ADC 事件必须为规范 Base64 的 8 字节 raw/mV 记录")
            raw, mv = struct.unpack("<ii", data)
            samples.append(
                ADCSample(
                    raw=raw,
                    millivolts=None if mv < 0 else mv,
                    sequence=event.sequence,
                    time_us=getattr(event, "time_us", None),
                )
            )
        return samples


class AsyncUARTPort(AsyncResource):
    async def write(self, data: bytes, *, timeout_ms: int | None = None) -> int:
        return (await self.call(ResourceAction.WRITE, data=data, timeout_ms=timeout_ms)).data[
            "written"
        ]

    async def read(self, length: int, *, timeout_ms: int | None = None) -> bytes:
        result = await self.call(ResourceAction.READ, length=length, timeout_ms=timeout_ms)
        return BinaryResult.model_validate(result.data).to_bytes()

    async def drain(self, *, timeout_ms: int | None = None) -> None:
        await self.call(ResourceAction.DRAIN, timeout_ms=timeout_ms)

    async def clear(self) -> None:
        await self.call(ResourceAction.CLEAR)

    async def errors(self) -> OperationResult:
        return await self.call(ResourceAction.ERRORS)

    async def events(self) -> PeripheralEvents:
        return PeripheralEvents.model_validate((await self.call(ResourceAction.EVENTS)).data)

    async def send_break(self, data: bytes, *, bits: int) -> None:
        await self.call(ResourceAction.BREAK, data=data, bits=bits)


class AsyncResources:
    def __init__(self, board: AsyncBoard):
        self.board = board

    def open(
        self,
        kind: ResourceKind,
        *,
        pins: dict[str, int],
        config: dict[str, Any],
        parent: AsyncResource | None = None,
        controller: int | None = None,
    ) -> AsyncResource:
        return AsyncResource(self.board, kind, pins, config, parent=parent, controller=controller)


class AsyncGPIO:
    def __init__(self, board: AsyncBoard):
        self.board = board

    def output(
        self,
        pin: int,
        *,
        value: int = Level.LOW,
        open_drain: bool = False,
        **config: Unpack[GPIOConfig],
    ) -> AsyncGPIOPin:
        return AsyncGPIOPin(
            self.board,
            PeripheralKind.GPIO,
            {"pin": pin},
            {
                **config,
                "mode": GPIOMode.OPEN_DRAIN if open_drain else GPIOMode.OUTPUT,
                "level": value,
            },
        )

    def input(self, pin: int, **config: Unpack[GPIOConfig]) -> AsyncGPIOPin:
        return AsyncGPIOPin(
            self.board, PeripheralKind.GPIO, {"pin": pin}, {**config, "mode": GPIOMode.INPUT}
        )


class AsyncPWM:
    def __init__(self, board: AsyncBoard):
        self.board = board

    def open(
        self,
        pin: int,
        *,
        frequency: int,
        duty: float = 0,
        resolution: int = 10,
        **config: Unpack[PWMConfig],
    ) -> AsyncPWMOutput:
        return AsyncPWMOutput(
            self.board,
            PeripheralKind.PWM,
            {"pin": pin},
            {
                **config,
                "frequency": frequency,
                "duty": duty,
                "resolution": resolution,
            },
        )


class AsyncADC:
    def __init__(self, board: AsyncBoard):
        self.board = board

    def open(self, pin: int, *, attenuation: int = 0, interval_ms: int = 0) -> AsyncADCInput:
        return AsyncADCInput(
            self.board,
            PeripheralKind.ADC,
            {"pin": pin},
            {
                "attenuation": attenuation,
                "interval_ms": interval_ms,
            },
        )


class AsyncUART:
    def __init__(self, board: AsyncBoard):
        self.board = board

    def open(
        self,
        *,
        tx: int | None = None,
        rx: int | None = None,
        rts: int | None = None,
        cts: int | None = None,
        baud: int = 115200,
        controller: int | None = None,
        **config: Unpack[UARTConfig],
    ) -> AsyncUARTPort:
        pins = {
            k: v for k, v in {"tx": tx, "rx": rx, "rts": rts, "cts": cts}.items() if v is not None
        }
        return AsyncUARTPort(
            self.board, PeripheralKind.UART, pins, {**config, "baud": baud}, controller=controller
        )
