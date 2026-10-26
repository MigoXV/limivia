from __future__ import annotations

import asyncio
import math
from contextlib import AbstractContextManager
from functools import partial
from typing import Protocol, Self

from anyio.from_thread import BlockingPortal, start_blocking_portal

from ._board import AsyncBoard, AsyncRaw
from ._connection import AsyncConnection
from ._exceptions import DeviceConnectionError, DeviceSelectionError
from ._sync import Connection, RawEventStream
from .constants import TransportKind
from .resources import Resources
from .transports import DeviceBackend, Transport
from .types import (
    ClientEvent,
    ClientEventParam,
    ConnectionOptions,
    DeviceEvent,
    DeviceIdentity,
    DeviceInfo,
    LinkKind,
    MQTTOptions,
)


class Backend(Protocol):
    async def discover(self, kind: LinkKind) -> list[dict[str, str]]: ...
    def transport(
        self, kind: LinkKind, target: str, options: ConnectionOptions | None = None
    ) -> Transport: ...


class AsyncDevices:
    def __init__(self, client: AsyncLimivia):
        self._client = client

    async def list(self, *, kind: LinkKind = TransportKind.BLE) -> list[DeviceInfo]:
        client = self._client
        client._check()
        if kind not in (TransportKind.BLE, TransportKind.USB):
            raise ValueError("kind 必须为 ble 或 usb。")
        if client._active is not None or client._scanning:
            raise DeviceConnectionError("正在连接设备或搜索设备，请先断开或等待搜索结束。")
        client._scanning = asyncio.current_task()
        try:
            devices = await asyncio.wait_for(client._backend.discover(kind), timeout=12)
            return [DeviceInfo.model_validate(device) for device in devices]
        finally:
            client._scanning = None

    def connect(
        self,
        *,
        kind: LinkKind = TransportKind.BLE,
        target: str | None = None,
        options: ConnectionOptions | None = None,
        expected_device_id: str | None = None,
    ) -> AsyncConnectionManager:
        return AsyncConnectionManager(self._client, kind, target, options, expected_device_id)


class AsyncConnectionManager:
    def __init__(
        self,
        client: AsyncLimivia,
        kind: LinkKind,
        target: str | None,
        options: ConnectionOptions | None,
        expected_device_id: str | None,
    ):
        self._client = client
        self._kind = kind
        self._target = target
        self._options = options
        self._expected = expected_device_id
        self._connection: AsyncBoard | None = None
        self._entered = False
        self._owned_client = False

    async def __aenter__(self) -> AsyncBoard:
        try:
            return await self._enter()
        except BaseException:
            if self._owned_client:
                await self._client.close()
            raise

    async def _enter(self) -> AsyncBoard:
        client = self._client
        client._check()
        if self._entered:
            raise DeviceConnectionError("连接上下文不能重复使用。")
        self._entered = True
        if self._kind not in (
            TransportKind.BLE,
            TransportKind.USB,
            TransportKind.WS,
            TransportKind.MQTT,
        ):
            raise ValueError("kind 必须为 ble/usb/ws/mqtt")
        if self._target is None:
            if self._kind not in (TransportKind.USB, TransportKind.BLE):
                raise ValueError("网络连接需要明确 target URL")
            candidates = await client.devices.list(kind=self._kind)
            if len(candidates) != 1:
                raise DeviceSelectionError(f"发现 {len(candidates)} 台候选设备，请明确指定 target")
            self._target = candidates[0].id
        if self._kind == TransportKind.MQTT:
            if not isinstance(self._options, MQTTOptions):
                raise ValueError("MQTT连接需要MQTTOptions/device_id")
            if self._expected and self._expected.lower() != self._options.device_id:
                raise ValueError("MQTT目标与expected_device_id不一致")
            self._expected = self._options.device_id
        if client._active is not None or client._scanning:
            raise DeviceConnectionError("已有活动连接或正在扫描，请先结束当前会话。")
        connection = AsyncConnection(
            client._backend.transport(self._kind, self._target, self._options),
            timeout=client.timeout,
            connect_timeout=client.connect_timeout,
            event_queue_size=client.event_queue_size,
            job_timeout=client.job_timeout,
            job_poll_interval=client.job_poll_interval,
            expected_device_id=self._expected,
        )
        client._active = connection
        client._opening = asyncio.current_task()
        try:
            await connection._open()
        except BaseException:
            client._active = None
            raise
        finally:
            client._opening = None
        self._connection = AsyncBoard(connection)
        client._board = self._connection
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self._connection is not None:
                try:
                    await self._connection._exit(exc)
                finally:
                    self._client._active = None
                    self._client._board = None
        finally:
            if self._owned_client:
                await self._client.close()


class AsyncLimivia:
    def __init__(
        self,
        *,
        timeout: float = 6,
        connect_timeout: float = 20,
        event_queue_size: int = 256,
        job_timeout: float = 30,
        job_poll_interval: float = 0.1,
        backend: Backend | None = None,
        ble_adapter: str | None = None,
    ):
        if (
            any(
                not math.isfinite(v) or v <= 0
                for v in (timeout, connect_timeout, job_timeout, job_poll_interval)
            )
            or type(event_queue_size) is not int
            or event_queue_size < 1
            or job_poll_interval < 0.01
        ):
            raise ValueError("超时必须有限且大于零，事件缓冲需要正整数，轮询间隔至少10ms")
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.event_queue_size = event_queue_size
        self.job_timeout = job_timeout
        self.job_poll_interval = job_poll_interval
        if backend is not None and ble_adapter is not None:
            raise ValueError("自定义 backend 与 ble_adapter 不能同时指定")
        self._backend = backend if backend is not None else DeviceBackend(ble_adapter=ble_adapter)
        self._active: AsyncConnection | None = None
        self._board: AsyncBoard | None = None
        self._scanning: asyncio.Task | None = None
        self._opening: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self.devices = AsyncDevices(self)

    @classmethod
    def connect(
        cls,
        *,
        kind: LinkKind = TransportKind.USB,
        target: str | None = None,
        options: ConnectionOptions | None = None,
        expected_device_id: str | None = None,
        **client_options,
    ) -> AsyncConnectionManager:
        client = cls(**client_options)
        manager = client.devices.connect(
            kind=kind, target=target, options=options, expected_device_id=expected_device_id
        )
        manager._owned_client = True
        return manager

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
            try:
                if self._board:
                    await self._board._exit(None)
                else:
                    await self._active.close()
            finally:
                self._active = None
                self._board = None


class RawConnection(Resources[int]):
    def __init__(self, connection: AsyncRaw, portal: BlockingPortal):
        self._connection = connection
        self._portal = portal
        self.handshake_request_id = connection.handshake_request_id
        super().__init__(
            self.send, snapshot=lambda: self._portal.call(self._connection._state_snapshot)
        )

    def send(self, event: ClientEvent | ClientEventParam) -> int:
        return self._portal.call(self._connection.send, event)

    def hello(self, *, client_nonce: str | None = None) -> int:
        return self._portal.call(lambda: self._connection.hello(client_nonce=client_nonce))

    @property
    def identity(self) -> DeviceIdentity | None:
        return self._portal.call(lambda: self._connection.identity)

    def discover(self, *, refresh: bool = False) -> int:
        return self._portal.call(lambda: self._connection.discover(refresh=refresh))

    def batch(self, commands: list[ClientEvent | ClientEventParam]) -> list[int]:
        return self._portal.call(self._connection.batch, commands)

    def subscribe(self, *, queue_size: int | None = None) -> RawEventStream:
        stream = self._portal.call(partial(self._connection.subscribe, queue_size=queue_size))
        return RawEventStream(stream, self._portal)

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
    def __init__(
        self,
        client: Limivia,
        kind: LinkKind,
        target: str | None,
        options: ConnectionOptions | None,
        expected_device_id: str | None,
    ):
        self._client = client
        self._kind = kind
        self._target = target
        self._options = options
        self._expected = expected_device_id
        self._manager: AsyncConnectionManager | None = None
        self._entered = False
        self._owned_client = False

    def __enter__(self) -> Connection:
        if self._entered:
            raise DeviceConnectionError("连接上下文不能重复使用。")
        self._entered = True
        try:
            portal, client = self._client._ensure()
            self._manager = client.devices.connect(
                kind=self._kind,
                target=self._target,
                options=self._options,
                expected_device_id=self._expected,
            )
            return Connection(portal.call(self._manager.__aenter__), portal)
        except BaseException:
            if self._owned_client:
                self._client.close()
            raise

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._manager is not None and self._client._portal is not None:
                self._client._portal.call(self._manager.__aexit__, exc_type, exc, tb)
        finally:
            if self._owned_client:
                self._client.close()


class Devices:
    def __init__(self, client: Limivia):
        self._client = client

    def list(self, *, kind: LinkKind = TransportKind.BLE) -> list[DeviceInfo]:
        portal, client = self._client._ensure()
        return portal.call(partial(client.devices.list, kind=kind))

    def connect(
        self,
        *,
        kind: LinkKind = TransportKind.BLE,
        target: str | None = None,
        options: ConnectionOptions | None = None,
        expected_device_id: str | None = None,
    ) -> ConnectionManager:
        return ConnectionManager(self._client, kind, target, options, expected_device_id)


class Limivia:
    """同步门面；后台 asyncio 循环在整个客户端生命周期内持续运行。"""

    def __init__(
        self,
        *,
        timeout: float = 6,
        connect_timeout: float = 20,
        event_queue_size: int = 256,
        job_timeout: float = 30,
        job_poll_interval: float = 0.1,
        backend: Backend | None = None,
        ble_adapter: str | None = None,
    ):
        self._factory = partial(
            AsyncLimivia,
            timeout=timeout,
            connect_timeout=connect_timeout,
            event_queue_size=event_queue_size,
            job_timeout=job_timeout,
            job_poll_interval=job_poll_interval,
            backend=backend,
            ble_adapter=ble_adapter,
        )
        self._portal_context: AbstractContextManager[BlockingPortal] | None = None
        self._portal: BlockingPortal | None = None
        self._client: AsyncLimivia | None = None
        self._closed = False
        self.devices = Devices(self)

    @classmethod
    def connect(
        cls,
        *,
        kind: LinkKind = TransportKind.USB,
        target: str | None = None,
        options: ConnectionOptions | None = None,
        expected_device_id: str | None = None,
        **client_options,
    ) -> ConnectionManager:
        manager = ConnectionManager(
            cls(**client_options), kind, target, options, expected_device_id
        )
        manager._owned_client = True
        return manager

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
