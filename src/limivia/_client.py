from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager
from functools import partial
from typing import Protocol, Self

from anyio.from_thread import BlockingPortal, start_blocking_portal

from ._connection import AsyncConnection
from ._exceptions import DeviceConnectionError
from .resources import (
    ADCResource,
    GPIOResource,
    OutputsResource,
    PinResource,
    PWMResource,
    StateResource,
    TimerResource,
)
from .transports import DeviceBackend, Transport
from .types import ClientEvent, ClientEventParam, DeviceEvent, DeviceInfo, LinkKind


class Backend(Protocol):
    async def discover(self, kind: LinkKind) -> list[dict[str, str]]: ...
    def transport(self, kind: LinkKind, target: str) -> Transport: ...


class AsyncDevices:
    def __init__(self, client: AsyncLimivia):
        self._client = client

    async def list(self, *, kind: LinkKind = "ble") -> list[DeviceInfo]:
        client = self._client
        client._check()
        if kind not in ("ble", "usb"):
            raise ValueError("kind 必须为 ble 或 usb。")
        if client._active is not None or client._scanning:
            raise DeviceConnectionError("正在连接设备或搜索设备，请先断开或等待搜索结束。")
        client._scanning = asyncio.current_task()
        try:
            devices = await asyncio.wait_for(client._backend.discover(kind), timeout=12)
            return [DeviceInfo.model_validate(device) for device in devices]
        finally:
            client._scanning = None

    def connect(self, *, kind: LinkKind = "ble", target: str) -> AsyncConnectionManager:
        return AsyncConnectionManager(self._client, kind, target)


class AsyncConnectionManager:
    def __init__(self, client: AsyncLimivia, kind: LinkKind, target: str):
        self._client = client
        self._kind = kind
        self._target = target
        self._connection: AsyncConnection | None = None
        self._entered = False

    async def __aenter__(self) -> AsyncConnection:
        client = self._client
        client._check()
        if self._entered:
            raise DeviceConnectionError("连接上下文不能重复使用。")
        self._entered = True
        if self._kind not in ("ble", "usb"):
            raise ValueError("kind 必须为 ble 或 usb。")
        if client._active is not None or client._scanning:
            raise DeviceConnectionError("已有活动连接或正在扫描，请先结束当前会话。")
        connection = AsyncConnection(
            client._backend.transport(self._kind, self._target),
            timeout=client.timeout,
            connect_timeout=client.connect_timeout,
            event_queue_size=client.event_queue_size,
        )
        self._connection = connection
        client._active = connection
        client._opening = asyncio.current_task()
        try:
            await connection._open()
        except BaseException:
            client._active = None
            raise
        finally:
            client._opening = None
        return connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._connection is not None:
            try:
                await self._connection.close()
            finally:
                if self._client._active is self._connection:
                    self._client._active = None


class AsyncLimivia:
    def __init__(
        self,
        *,
        timeout: float = 6,
        connect_timeout: float = 20,
        event_queue_size: int = 256,
        backend: Backend | None = None,
    ):
        if timeout <= 0 or connect_timeout <= 0 or event_queue_size < 1:
            raise ValueError("超时和事件缓冲大小必须大于零。")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.event_queue_size = event_queue_size
        self._backend = backend if backend is not None else DeviceBackend()
        self._active: AsyncConnection | None = None
        self._scanning: asyncio.Task | None = None
        self._opening: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self.devices = AsyncDevices(self)

    def _check(self) -> None:
        if self._closed:
            raise DeviceConnectionError("客户端已关闭。")
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise DeviceConnectionError("同一个 AsyncLimivia 必须始终在同一事件循环使用。")
        self._loop = loop

    async def __aenter__(self) -> Self:
        self._check()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._check()
        self._closed = True
        if self._scanning and self._scanning is not asyncio.current_task():
            self._scanning.cancel()
            await asyncio.gather(self._scanning, return_exceptions=True)
        if self._opening and self._opening is not asyncio.current_task():
            self._opening.cancel()
            await asyncio.gather(self._opening, return_exceptions=True)
        if self._active:
            await self._active.close()
            self._active = None


class Connection:
    def __init__(self, connection: AsyncConnection, portal: BlockingPortal):
        self._connection = connection
        self._portal = portal
        self.handshake_request_id = connection.handshake_request_id
        self.state = StateResource(self.send)
        self.gpio = GPIOResource(self.send)
        self.pwm = PWMResource(self.send)
        self.adc = ADCResource(self.send)
        self.timer = TimerResource(self.send)
        self.pin = PinResource(self.send)
        self.outputs = OutputsResource(self.send)

    def send(self, event: ClientEvent | ClientEventParam) -> int:
        return self._portal.call(self._connection.send, event)

    def hello(self) -> int:
        return self._portal.call(self._connection.hello)

    def recv(self) -> DeviceEvent:
        try:
            return self._portal.call(self._connection.recv)
        except StopAsyncIteration:
            raise StopIteration from None

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> DeviceEvent:
        return self.recv()

    def close(self) -> None:
        self._portal.call(self._connection.close)


class ConnectionManager:
    def __init__(self, client: Limivia, kind: LinkKind, target: str):
        self._client = client
        self._kind = kind
        self._target = target
        self._manager: AsyncConnectionManager | None = None
        self._entered = False

    def __enter__(self) -> Connection:
        if self._entered:
            raise DeviceConnectionError("连接上下文不能重复使用。")
        self._entered = True
        portal, client = self._client._ensure()
        self._manager = client.devices.connect(kind=self._kind, target=self._target)
        return Connection(portal.call(self._manager.__aenter__), portal)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._manager is not None and self._client._portal is not None:
            self._client._portal.call(self._manager.__aexit__, exc_type, exc, tb)


class Devices:
    def __init__(self, client: Limivia):
        self._client = client

    def list(self, *, kind: LinkKind = "ble") -> list[DeviceInfo]:
        portal, client = self._client._ensure()
        return portal.call(partial(client.devices.list, kind=kind))

    def connect(self, *, kind: LinkKind = "ble", target: str) -> ConnectionManager:
        return ConnectionManager(self._client, kind, target)


class Limivia:
    """同步门面；后台 asyncio 循环在整个客户端生命周期内持续运行。"""

    def __init__(
        self,
        *,
        timeout: float = 6,
        connect_timeout: float = 20,
        event_queue_size: int = 256,
        backend: Backend | None = None,
    ):
        self._factory = partial(
            AsyncLimivia,
            timeout=timeout,
            connect_timeout=connect_timeout,
            event_queue_size=event_queue_size,
            backend=backend,
        )
        self._portal_context: AbstractContextManager[BlockingPortal] | None = None
        self._portal: BlockingPortal | None = None
        self._client: AsyncLimivia | None = None
        self._closed = False
        self.devices = Devices(self)

    def _ensure(self) -> tuple[BlockingPortal, AsyncLimivia]:
        if self._closed:
            raise DeviceConnectionError("客户端已关闭。")
        if self._portal is None:
            self._portal_context = start_blocking_portal(backend="asyncio", name="limivia-sync")
            self._portal = self._portal_context.__enter__()
            try:
                self._client = self._portal.call(self._factory)
            except BaseException:
                self._portal_context.__exit__(None, None, None)
                self._portal = None
                raise
        assert self._client is not None
        return self._portal, self._client

    def __enter__(self) -> Self:
        self._ensure()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._portal is not None:
            try:
                assert self._client is not None
                self._portal.call(self._client.close)
            finally:
                assert self._portal_context is not None
                self._portal_context.__exit__(None, None, None)
                self._portal = None
