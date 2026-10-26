from __future__ import annotations

import asyncio
import re
import sys
from collections import deque
from contextlib import suppress
from typing import Protocol

import serial
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from serial.tools import list_ports

from ._ble_wire import Reader, pack
from ._exceptions import DeviceConnectionError
from .constants import TransportKind
from .types import ConnectionOptions, LinkKind, MQTTOptions, WebSocketOptions

SERVICE = "7b9d0001-7a21-4c9b-8b30-69e5ce1d0001"
RX = "7b9d0002-7a21-4c9b-8b30-69e5ce1d0001"
TX = "7b9d0003-7a21-4c9b-8b30-69e5ce1d0001"


async def serial_call(function, *args):
    # to_thread 的取消不会停止工作线程；清理句柄前必须等待串口操作退出。
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with suppress(Exception):
            await task
        raise


class Transport(Protocol):
    async def open(self) -> None: ...
    async def read(self) -> bytes: ...
    async def write(self, data: bytes) -> None: ...
    async def close(self) -> None: ...


class SerialTransport:
    def __init__(self, port: str):
        self.port = serial.Serial(baudrate=115200, timeout=0.2, write_timeout=2)
        # 原生 USB 板沿用 pySerial 默认线状态；显式拉低会触发该板复位。
        self.port.port = port

    async def open(self) -> None:
        await serial_call(self.port.open)

    async def read(self) -> bytes:
        while self.port.is_open:
            data = await serial_call(self.port.read, min(4096, self.port.in_waiting) or 1)
            if data:
                return data
        raise ConnectionError("USB 连接已关闭，请检查数据线、串口占用与设备供电。")

    async def write(self, data: bytes) -> None:
        written = await serial_call(self.port.write, data)
        if written != len(data):
            raise ConnectionError("USB 写入未完成；操作可能已执行，请重连后查询状态。")

    async def close(self) -> None:
        # 等待正在执行的有限超时读写结束，由 pySerial 释放系统句柄。
        await serial_call(self.port.close)


class BluetoothTransport:
    def __init__(self, device, *, binary: bool = False, ble_adapter: str | None = None):
        self.binary = binary
        self._wire = Reader()
        self._decoded: deque[bytes] = deque()
        self.queue: asyncio.Queue[bytes | Exception] = asyncio.Queue(maxsize=256)
        self.failed = False
        self._rx: BleakGATTCharacteristic | None = None
        self.client = BleakClient(
            device,
            disconnected_callback=self._disconnected,
            timeout=15,
            bluez={"adapter": ble_adapter} if ble_adapter else {},
        )

    def _push(self, data: bytes | Exception) -> None:
        if self.failed:
            return
        if self.queue.full():
            self.queue.get_nowait()
            data = ConnectionError("BLE 接收缓冲区已满，请重新连接并刷新设备状态。")
        if isinstance(data, Exception):
            self.failed = True
        self.queue.put_nowait(data)

    def _disconnected(self, _client) -> None:
        self._push(ConnectionError("蓝牙连接已断开，请检查适配器、设备供电与系统蓝牙日志。"))

    async def open(self) -> None:
        try:
            await self.client.connect()
        except TimeoutError as exc:
            raise DeviceConnectionError(
                "BLE GATT 建连超时（尚未发送业务请求），请检查适配器和系统蓝牙日志。"
            ) from exc
        except Exception as exc:
            raise DeviceConnectionError(
                f"BLE GATT 建连失败（尚未发送业务请求）：{type(exc).__name__}: {str(exc)[:512]}"
            ) from exc
        self._rx = self.client.services.get_characteristic(RX)
        if self._rx is None:
            raise ConnectionError("设备未提供 BLE RX 特征")
        await self.client.start_notify(TX, lambda _characteristic, data: self._push(bytes(data)))

    async def read(self) -> bytes:
        while True:
            if self._decoded:
                return self._decoded.popleft()
            item = await self.queue.get()
            if isinstance(item, Exception):
                raise item
            if not self.binary:
                return item
            self._decoded.extend(self._wire.feed(item))

    async def write(self, data: bytes) -> None:
        # This public characteristic property reflects ATT MTU-3 on BlueZ (the
        # client.mtu_size property can still report 23). Keep acknowledged writes;
        # the peripheral receives at most 512 bytes per ATT write. Read each frame
        # again because MTU exchange may finish after service discovery.
        if self.binary:
            data = pack(data)
        payload = min(512, self._rx.max_write_without_response_size) if self._rx else 20
        if payload < 20:
            raise ConnectionError("BLE RX 分片容量无效")
        for offset in range(0, len(data), payload):
            await self.client.write_gatt_char(RX, data[offset : offset + payload], response=True)

    async def close(self) -> None:
        await self.client.disconnect()


class DeviceBackend:
    """只开放扫描到的候选；板型最终仍由 hello 握手确认。"""

    def __init__(self, *, ble_adapter: str | None = None):
        if ble_adapter is not None and (
            sys.platform != "linux" or not re.fullmatch(r"hci[0-9]+", ble_adapter)
        ):
            raise ValueError("ble_adapter 仅支持 Linux 的 hciN 名称")
        self.ble_adapter = ble_adapter
        self.targets: dict[tuple[LinkKind, str], object] = {}

    async def discover(self, kind: LinkKind) -> list[dict[str, str]]:
        if kind not in (TransportKind.USB, TransportKind.BLE):
            raise ValueError("WS/MQTT使用明确地址，不支持扫描")
        self.targets = {key: value for key, value in self.targets.items() if key[0] != kind}
        if kind == TransportKind.USB:
            ports = await asyncio.to_thread(list_ports.comports)
            devices = []
            for port in ports:
                if port.vid == 0x303A and port.pid == 0x1001:
                    self.targets[(kind, port.device)] = port.device
                    devices.append(
                        {"id": port.device, "name": f"{port.description} · {port.device}"}
                    )
            return devices
        found = await BleakScanner.discover(
            timeout=5,
            return_adv=True,
            service_uuids=[SERVICE],
            bluez={"adapter": self.ble_adapter} if self.ble_adapter else {},
        )
        devices = []
        for device, advertisement in found.values():
            if SERVICE not in [uuid.lower() for uuid in advertisement.service_uuids]:
                continue
            self.targets[(kind, device.address)] = device
            devices.append(
                {
                    "id": device.address,
                    "name": advertisement.local_name or device.name or device.address,
                }
            )
        return devices

    def transport(
        self, kind: LinkKind, target: str, options: ConnectionOptions | None = None
    ) -> Transport:
        if kind in (TransportKind.WS, TransportKind.MQTT):
            from .network_transports import MQTTTransport, WebSocketTransport

            if kind == TransportKind.MQTT:
                if not isinstance(options, MQTTOptions):
                    raise ValueError("MQTT需要MQTTOptions")
                return MQTTTransport(target, options)
            if isinstance(options, MQTTOptions):
                raise ValueError("WS不能使用MQTTOptions")
            return WebSocketTransport(target, options or WebSocketOptions())
        if options is not None:
            raise ValueError("USB/BLE不使用网络选项")
        candidate = self.targets.get((kind, target))
        if (
            candidate is None
            and kind == TransportKind.USB
            and target.startswith("/dev/serial/by-id/")
        ):
            import os

            candidate = self.targets.get((kind, os.path.realpath(target)))
        if candidate is None:
            raise ValueError("设备不在最近搜索结果中，请重新搜索并选择设备。")
        return (
            SerialTransport(str(candidate))
            if kind == TransportKind.USB
            else BluetoothTransport(candidate, ble_adapter=self.ble_adapter)
        )
