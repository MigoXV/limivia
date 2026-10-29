"""使用协议模拟设备验证跨传输流程；不作为实机证据。"""

import secrets
from types import SimpleNamespace

import pytest
from typer import Exit

from examples.device import usb_wifi_websocket as example
from limivia import Limivia, ResultUnknownError
from tests.fakes import HELLO, FakeBackend, FakeTransport


class WifiTransport(FakeTransport):
    connected = True

    async def handle(self, wire):
        if wire["method"] == "job.get":
            params = wire["params"]
            args = params[1] if isinstance(params, list) else params["args"]
            job = self.jobs[args["job_id"]]
            if job["action"] == "wifi.status":
                job["result"] = {
                    "connected": self.connected,
                    "ip": "192.168.1.40" if self.connected else "0.0.0.0",
                }
        await super().handle(wire)


def setup_example(monkeypatch):
    usb = FakeBackend(WifiTransport())
    ws = FakeBackend()
    attempts = []
    password = secrets.token_urlsafe(18)

    class SwitchingBackend:
        async def discover(self, kind):
            return await usb.discover(kind)

        def transport(self, kind, target, options=None):
            if kind == "usb":
                assert usb.discovered, "Explicit USB targets require discovery first"
                return usb.transport(kind, target, options)
            assert usb.connection.closed, "WS must start after closing USB"
            assert usb.connection.control is None, "Release the old control lease first"
            return ws.transport(kind, target, options)

    def client():
        board_client = Limivia(backend=SwitchingBackend(), job_poll_interval=0.01)
        original_connect = board_client.devices.connect

        def connect(**kwargs):
            attempts.append(kwargs)
            return original_connect(**kwargs)

        board_client.devices.connect = connect
        return board_client

    monkeypatch.setattr(example, "Limivia", client)
    monkeypatch.setattr(
        example.typer, "prompt", lambda text, **kw: password if kw.get("hide_input") else "lab"
    )
    monkeypatch.setattr("builtins.input", lambda _: "")
    return usb, ws, attempts, password


@pytest.mark.parametrize("persist", [False, True])
def test_switches_transport_with_same_identity_and_releases_led(monkeypatch, capsys, persist):
    usb, ws, attempts, password = setup_example(monkeypatch)
    example.main(persist=persist)
    assert attempts[1]["target"] == "ws://192.168.1.40/v3"
    assert attempts[1]["expected_device_id"] == HELLO["device_id"]
    config = next(c["params"] for c in usb.connection.commands if c["op"] == "wifi.configure")
    assert config["persist"] is persist
    assert config["password"] == password
    calls = [c["params"] for c in ws.connection.commands if c["op"] == "resource.call"]
    assert [p["args"]["level"] for p in calls if p["action"] == "write"] == [1, 0]
    assert sum(p["action"] == "read" for p in calls) == 2
    assert ws.connection.closed and not ws.connection.resources
    output = capsys.readouterr()
    assert password not in output.out + output.err
    assert "读取电平 1" in output.out and "读取电平 0" in output.out


def test_wifi_timeout_closes_usb_without_starting_ws(monkeypatch, capsys):
    usb, _, attempts, password = setup_example(monkeypatch)
    usb.connection.connected = False
    now = [0.0]
    monkeypatch.setattr(example, "monotonic", lambda: now[0])
    monkeypatch.setattr(example, "sleep", lambda _: now.__setitem__(0, 21))
    with pytest.raises(Exit) as error:
        example.main()
    assert error.value.exit_code == 1
    assert len(attempts) == 1 and usb.connection.closed
    output = capsys.readouterr()
    assert password not in output.out + output.err


def test_unknown_configuration_result_is_not_replayed_or_printed(monkeypatch, capsys):
    _, _, attempts, password = setup_example(monkeypatch)

    class Board:
        identity = SimpleNamespace(device_id=HELLO["device_id"])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def configure(self, **kwargs):
            raise ResultUnknownError(password, may_have_executed=True)

        @property
        def wifi(self):
            return self

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @property
        def devices(self):
            return self

        def list(self, **kwargs):
            return []

        def connect(self, **kwargs):
            attempts.append(kwargs)
            return Board()

    monkeypatch.setattr(example, "Limivia", Client)
    with pytest.raises(Exit):
        example.main()
    assert len(attempts) == 1
    output = capsys.readouterr()
    assert password not in output.out + output.err
    assert "不要直接重发" in output.err
