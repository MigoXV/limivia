from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass

from anyio import CancelScope

from ._exceptions import DeviceConnectionError, ProtocolError, QueueFullError
from .protocol import LineReader, decode_message, encode_command, parse_command
from .resources import (
    ADCResource,
    GPIOResource,
    OutputsResource,
    PinResource,
    PWMResource,
    StateResource,
    TimerResource,
)
from .transports import Transport
from .types import (
    ClientEvent,
    ClientEventParam,
    CommandFailedEvent,
    ConnectionClosedEvent,
    DeviceError,
    DeviceEvent,
    HelloCommand,
    HelloCompletedEvent,
    ProtocolErrorEvent,
)

logger = logging.getLogger(__name__)


@dataclass
class _Request:
    id: int
    command: ClientEvent
    data: bytes
    done: asyncio.Event
    sent: bool = False


class AsyncConnection:
    """一个读循环、一个写循环；事件消费不会负责推进命令或超时。"""

    def __init__(
        self, transport: Transport, *, timeout: float, connect_timeout: float, event_queue_size: int
    ):
        self._transport = transport
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._event_limit = event_queue_size
        self._outgoing: asyncio.Queue[_Request] = asyncio.Queue(maxsize=8)
        self._pending: dict[int, _Request] = {}
        self._events: deque[DeviceEvent] = deque()
        # 终态另存，缓冲溢出时也能交付已完成命令及至多九个待处理命令的失败。
        self._terminal: deque[DeviceEvent] = deque()
        self._wake = asyncio.Event()
        self._receiving = False
        self._opened = False
        self._closed = False
        self._sequence = 0
        self._tasks: list[asyncio.Task[None]] = []
        self._cleanup_task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.handshake_request_id = 0
        self.state = StateResource(self.send)
        self.gpio = GPIOResource(self.send)
        self.pwm = PWMResource(self.send)
        self.adc = ADCResource(self.send)
        self.timer = TimerResource(self.send)
        self.pin = PinResource(self.send)
        self.outputs = OutputsResource(self.send)

    async def _open(self) -> None:
        try:
            async with asyncio.timeout(self._connect_timeout):
                await self._transport.open()
                if self._closed:
                    raise DeviceConnectionError("连接已关闭。")
                self._opened = True
                self._tasks = [
                    asyncio.create_task(self._read(), name="limivia-reader"),
                    asyncio.create_task(self._write(), name="limivia-writer"),
                ]
                self.handshake_request_id = await self.hello()
                await self._ready
                if self._closed:
                    raise DeviceConnectionError("设备在握手结束时断开，请重新连接。")
        except BaseException:
            await self.close()
            raise

    async def hello(self) -> int:
        return await self.send(HelloCommand())

    async def send(self, event: ClientEvent | ClientEventParam) -> int:
        """校验并原子入队后返回 ID；执行结果只通过事件流交付。"""
        if not self._opened or self._closed:
            raise DeviceConnectionError("设备连接已关闭，请重新连接。")
        command = parse_command(event)
        if self._sequence >= 2147483647:
            raise DeviceConnectionError("请求 ID 已耗尽，请重新连接。")
        request_id = self._sequence + 1
        data = encode_command(command, request_id)
        request = _Request(request_id, command, data, asyncio.Event())
        try:
            self._outgoing.put_nowait(request)
        except asyncio.QueueFull as exc:
            raise QueueFullError("已有八个等待命令，请消费结果后再发送。") from exc
        # 此方法无挂起点；返回后桥接可在下次 await 前注册外部请求 ID。
        self._sequence = request_id
        self._pending[request_id] = request
        return request_id

    def __aiter__(self) -> AsyncConnection:
        return self

    async def __anext__(self) -> DeviceEvent:
        return await self.recv()

    async def recv(self) -> DeviceEvent:
        """每个连接仅一个消费者；取消等待不会丢失事件。"""
        if self._receiving:
            raise RuntimeError("一个连接只能有一个事件消费者。")
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
            # 当前已经完成的命令不能因溢出丢失。
            if hasattr(event, "request_id"):
                self._terminal.append(event)
            self._terminate(
                DeviceError(
                    code="event_buffer_overflow",
                    message="事件缓冲区已满，请重连后查询状态。",
                    source="sdk",
                )
            )
            return
        self._events.append(event)
        self._wake.set()

    def _complete(self, request: _Request, event: DeviceEvent) -> None:
        if self._pending.pop(request.id, None) is None:
            return
        request.done.set()
        if request.id == self.handshake_request_id and not self._ready.done():
            if isinstance(event, HelloCompletedEvent):
                if event.result.protocol == 1 and event.result.board == "luatos-esp32c3-usb":
                    self._ready.set_result(None)
                else:
                    event = self._failure(
                        request,
                        "incompatible_device",
                        "设备固件或协议不兼容，请安装本工程专用固件。",
                    )
                    self._ready.set_exception(DeviceConnectionError(event.error.message))
                    self._ready.exception()
            else:
                message = (
                    event.error.message if isinstance(event, CommandFailedEvent) else "握手失败。"
                )
                self._ready.set_exception(DeviceConnectionError(message))
                self._ready.exception()
        self._publish(event)

    @staticmethod
    def _failure(request: _Request, code: str, message: str) -> CommandFailedEvent:
        return CommandFailedEvent(
            request_id=request.id,
            op=request.command.type,
            error=DeviceError(
                code=code, message=message, source="sdk", may_have_executed=request.sent
            ),
        )

    async def _write(self) -> None:
        try:
            while not self._closed:
                request = await self._outgoing.get()
                deadline = asyncio.get_running_loop().time() + self._timeout
                request.sent = True
                try:
                    await asyncio.wait_for(
                        self._transport.write(request.data), timeout=min(5, self._timeout)
                    )
                except TimeoutError:
                    # 半帧写入不能继续复用通道，否则下一条命令会拼接到旧帧。
                    self._terminate(
                        DeviceError(
                            code="write_timeout",
                            message="设备写入超时；操作可能已执行，请重连查询状态。",
                            source="sdk",
                        )
                    )
                    return
                try:
                    remaining = max(0, deadline - asyncio.get_running_loop().time())
                    await asyncio.wait_for(request.done.wait(), timeout=remaining)
                except TimeoutError:
                    # 超时不重试。后续 state 请求仍可用于恢复实际状态。
                    self._complete(
                        request,
                        self._failure(
                            request, "timeout", "设备响应超时；操作可能已执行，请查询状态。"
                        ),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("设备通信中断: %s", exc, exc_info=True)
            self._terminate(DeviceError(code="connection_lost", message=str(exc), source="sdk"))

    async def _read(self) -> None:
        reader = LineReader()
        try:
            while not self._closed:
                data = await self._transport.read()
                if not data:
                    raise DeviceConnectionError("设备连接已断开，请重新连接。")
                for line in reader.feed(data):
                    if self._closed:
                        break
                    if isinstance(line, ProtocolError):
                        self._publish(ProtocolErrorEvent(message=str(line)))
                        continue
                    try:
                        message = json.loads(line)
                    except (ValueError, RecursionError):
                        # USB 上可能混有固件启动日志；看起来像 JSON 的坏帧显式报告。
                        if line.lstrip().startswith(("{", "[")):
                            self._publish(ProtocolErrorEvent(message="设备 JSON 帧无效。"))
                        else:
                            logger.debug("设备日志: %.240s", line)
                        continue
                    if not isinstance(message, dict):
                        self._publish(ProtocolErrorEvent(message="设备帧必须为 JSON 对象。"))
                        continue
                    request = None
                    if "event" not in message and type(message.get("id")) is int:
                        request = self._pending.get(message["id"])
                        if request is None or not request.sent:
                            logger.debug("忽略迟到或未知响应: %s", message.get("id"))
                            continue
                    try:
                        event = decode_message(message, request.command.type if request else None)
                    except ProtocolError as exc:
                        if request:
                            self._complete(
                                request, self._failure(request, "invalid_response", str(exc))
                            )
                        else:
                            self._publish(ProtocolErrorEvent(message=str(exc)))
                        continue
                    if request:
                        self._complete(request, event)
                    else:
                        self._publish(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("设备通信中断: %s", exc, exc_info=True)
            self._terminate(DeviceError(code="connection_lost", message=str(exc), source="sdk"))

    def _terminate(self, error: DeviceError | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._ready.done():
            self._ready.set_exception(
                DeviceConnectionError(error.message if error else "连接在握手完成前关闭。")
            )
            self._ready.exception()
        for request in self._pending.values():
            self._terminal.append(
                self._failure(
                    request,
                    error.code if error else "cancelled",
                    error.message if error else "连接已关闭，未完成命令已取消。",
                )
            )
            request.done.set()
        self._pending.clear()
        self._terminal.append(ConnectionClosedEvent(error=error))
        self._wake.set()
        self._cleanup_task = asyncio.create_task(self._cleanup(), name="limivia-cleanup")

    async def _cleanup(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(self._transport.close(), timeout=5)
        except Exception as exc:
            logger.exception("设备资源释放失败")
            for event in self._terminal:
                if isinstance(event, ConnectionClosedEvent) and event.error is None:
                    event.error = DeviceError(code="close_failed", message=str(exc), source="sdk")

    async def close(self) -> None:
        self._terminate()
        assert self._cleanup_task is not None
        with CancelScope(shield=True):
            try:
                await asyncio.shield(self._cleanup_task)
            except asyncio.CancelledError:
                await asyncio.shield(self._cleanup_task)
                raise
