import asyncio
from types import SimpleNamespace

import pytest

from limivia.transports import RX, SERVICE, TX, BluetoothTransport, DeviceBackend

COMMAND = '{"v":1,"id":1,"op":"hello","params":{}}\n'


def test_ble_transport_subscribes_fragments_and_surfaces_disconnect(monkeypatch):
    class Client:
        def __init__(self, device, disconnected_callback, **kwargs):
            self.disconnected = disconnected_callback
            self.writes = []
            self.notifications = None
            self.connected = False

        async def connect(self):
            self.connected = True

        async def start_notify(self, uuid, callback):
            assert uuid == TX
            self.notifications = callback

        async def write_gatt_char(self, uuid, data, response):
            assert self.notifications is not None
            assert uuid == RX and response is True
            self.writes.append(data)

        async def disconnect(self):
            self.connected = False

    monkeypatch.setattr("limivia.transports.BleakClient", Client)

    async def run():
        transport = BluetoothTransport("test")
        await transport.open()
        payload = b"x" * 51
        await transport.write(payload)
        assert list(map(len, transport.client.writes)) == [20, 20, 11]
        assert b"".join(transport.client.writes) == payload
        transport.client.notifications(None, bytearray(b"data"))
        assert await transport.read() == b"data"
        transport.client.disconnected(None)
        with pytest.raises(ConnectionError, match="蓝牙连接已断开"):
            await transport.read()
        await transport.close()
        assert not transport.client.connected

    asyncio.run(run())


def test_discovery_filters_candidates_and_refuses_arbitrary_targets(monkeypatch):
    async def discover(**kwargs):
        assert kwargs["service_uuids"] == [SERVICE]
        return {
            "one": (
                SimpleNamespace(address="one", name="board"),
                SimpleNamespace(local_name="LIMIVIA", service_uuids=[SERVICE]),
            ),
            "two": (
                SimpleNamespace(address="two", name="other"),
                SimpleNamespace(local_name="other", service_uuids=[]),
            ),
        }

    monkeypatch.setattr("limivia.transports.BleakScanner.discover", discover)
    monkeypatch.setattr(
        "limivia.transports.list_ports.comports",
        lambda: [
            SimpleNamespace(vid=0x303A, pid=0x1001, device="/dev/test", description="ESP32"),
            SimpleNamespace(vid=1, pid=2, device="/dev/other", description="other"),
        ],
    )

    async def run():
        backend = DeviceBackend()
        assert await backend.discover("ble") == [{"id": "one", "name": "LIMIVIA"}]
        assert len(await backend.discover("usb")) == 1
        with pytest.raises(ValueError, match="搜索"):
            backend.transport("usb", "/etc/passwd")

    asyncio.run(run())


def test_serial_transport_preserves_bytes_and_does_not_toggle_reset(monkeypatch):
    from limivia.transports import SerialTransport

    class Port:
        def __init__(self, **kwargs):
            assert kwargs == {"baudrate": 115200, "timeout": 0.2, "write_timeout": 2}
            self.is_open = False
            self.writes = []

        def open(self):
            assert self.dtr is False and self.rts is False
            assert self.port == "/dev/test"
            self.is_open = True

        def read(self, size):
            return b"response\n"

        def write(self, data):
            self.writes.append(data)
            return len(data)

        def close(self):
            self.is_open = False

    monkeypatch.setattr("limivia.transports.serial.Serial", Port)

    async def run():
        transport = SerialTransport("/dev/test")
        await transport.open()
        await transport.write(COMMAND.encode())
        assert await transport.read() == b"response\n"
        assert transport.port.writes == [COMMAND.encode()]
        await transport.close()
        assert not transport.port.is_open

    asyncio.run(run())
