from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

import serial
from bleak import BleakClient, BleakScanner
from serial.tools import list_ports

from .types import LinkKind

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
        self.port.dtr = False
        self.port.rts = False
        self.port.port = port

    async def open(self) -> None:
        await serial_call(self.port.open)

    async def read(self) -> bytes:
        while self.port.is_open:
            data = await serial_call(self.port.read, 4096)
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
    def __init__(self, device):
        self.queue: asyncio.Queue[bytes | Exception] = asyncio.Queue(maxsize=256)
        self.failed = False
        self.client = BleakClient(device, disconnected_callback=self._disconnected, timeout=15)

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
        self._push(ConnectionError("蓝牙连接已断开，请检查距离、蓝牙状态与设备供电。"))

    async def open(self) -> None:
        await self.client.connect()
        await self.client.start_notify(TX, lambda _characteristic, data: self._push(bytes(data)))

    async def read(self) -> bytes:
        item = await self.queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def write(self, data: bytes) -> None:
        for offset in range(0, len(data), 20):
            await self.client.write_gatt_char(RX, data[offset : offset + 20], response=True)

    async def close(self) -> None:
        await self.client.disconnect()


class DeviceBackend:
    """只开放扫描到的候选；板型最终仍由 hello 握手确认。"""

    def __init__(self):
        self.targets: dict[tuple[LinkKind, str], object] = {}

    async def discover(self, kind: LinkKind) -> list[dict[str, str]]:
        self.targets = {key: value for key, value in self.targets.items() if key[0] != kind}
        if kind == "usb":
            ports = await asyncio.to_thread(list_ports.comports)
            devices = []
            for port in ports:
                if port.vid == 0x303A and port.pid == 0x1001:
                    self.targets[(kind, port.device)] = port.device
                    devices.append(
                        {"id": port.device, "name": f"{port.description} · {port.device}"}
                    )
            return devices
        found = await BleakScanner.discover(timeout=5, return_adv=True, service_uuids=[SERVICE])
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

    def transport(self, kind: LinkKind, target: str) -> Transport:
        candidate = self.targets.get((kind, target))
        if candidate is None:
            raise ValueError("设备不在最近搜索结果中，请重新搜索并选择设备。")
        return SerialTransport(str(candidate)) if kind == "usb" else BluetoothTransport(candidate)
