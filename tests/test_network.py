"""真实客户端库+loopback套接字；测试报文夹具不代表真实broker或板上无线互通。"""

import asyncio
import json
import ssl
import subprocess
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from websockets.asyncio.server import serve

from limivia import AsyncLimivia
from limivia.network_transports import MQTTTransport, WebSocketTransport, _frame
from limivia.types import MQTTOptions, WebSocketOptions
from tests.fakes import HELLO, FakeTransport, result


def packet(kind, body):
    size = len(body)
    encoded = bytearray([kind])
    while True:
        byte = size % 128
        size //= 128
        encoded.append(byte | (128 if size else 0))
        if not size:
            break
    return bytes(encoded) + body


def field(text):
    data = text.encode()
    return len(data).to_bytes(2, "big") + data


async def read_packet(reader):
    header = (await reader.readexactly(1))[0]
    size = 0
    mult = 1
    for _ in range(4):
        byte = (await reader.readexactly(1))[0]
        size += (byte & 127) * mult
        if not byte & 128:
            break
        mult *= 128
    else:
        raise ValueError("MQTT malformed length")
    return header, await reader.readexactly(size)


async def device_reply(fake, data):
    await fake.write(data)
    output = bytearray()
    while not output.endswith(b"\n"):
        output.extend(await fake.read())
    return bytes(output)


class Broker:
    def __init__(self, retained=False):
        self.events = []
        self.retained = retained
        self.tasks = set()
        self.writers = set()
        self.fake = None

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        fake = FakeTransport()
        self.fake = fake
        await fake.open()
        level = 4
        topic = ""
        try:
            while True:
                header, body = await read_packet(reader)
                kind = header >> 4
                self.events.append(kind)
                if kind == 1:
                    level = body[6]
                    writer.write(packet(0x20, b"\0\0\0" if level == 5 else b"\0\0"))
                elif kind == 8:
                    offset = 3 if level == 5 else 2
                    size = int.from_bytes(body[offset : offset + 2], "big")
                    topic = body[offset + 2 : offset + 2 + size].decode()
                    writer.write(packet(0x90, body[:2] + (b"\0" if level == 5 else b"") + b"\1"))
                elif kind == 3:
                    assert header & 7 == 0, "control publish must be QoS0 and non-retained"
                    size = int.from_bytes(body[:2], "big")
                    payload = body[2 + size + (1 if level == 5 else 0) :]
                    command = json.loads(payload)
                    if self.retained and command["method"] == "hello":
                        wrong = {
                            "v": 2,
                            "id": command["id"],
                            "op": "hello",
                            "ok": True,
                            "result": {},
                        }
                        writer.write(
                            packet(
                                0x31,
                                field(topic)
                                + (b"\0" if level == 5 else b"")
                                + json.dumps(wrong).encode(),
                            )
                        )
                    reply = await device_reply(fake, payload)
                    writer.write(
                        packet(0x30, field(topic) + (b"\0" if level == 5 else b"") + reply)
                    )
                elif kind == 12:
                    writer.write(packet(0xD0, b""))
                elif kind == 14:
                    break
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.writers.discard(writer)
            self.tasks.discard(task)


@asynccontextmanager
async def broker(*, retained=False, context=None):
    fixture = Broker(retained)
    server = await asyncio.start_server(fixture.handle, "127.0.0.1", 0, ssl=context)
    try:
        yield f"127.0.0.1:{server.sockets[0].getsockname()[1]}", fixture
    finally:
        server.close()
        await server.wait_closed()
        for writer in list(fixture.writers):
            writer.close()
        if fixture.tasks:
            await asyncio.gather(*fixture.tasks, return_exceptions=True)


@pytest.mark.parametrize("protocol", ["3.1.1", "5.0"])
def test_mqtt_actual_library_handshake_subscribe_order_and_jobs(protocol):
    async def run():
        before = {t.ident for t in threading.enumerate()}
        async with broker(retained=True) as (address, b):
            async with AsyncLimivia(job_poll_interval=0.01) as client:
                options = MQTTOptions(device_id=HELLO["device_id"], protocol=protocol)
                async with client.devices.connect(
                    kind="mqtt", target=f"mqtt://{address}", options=options
                ) as c:
                    assert (await c.recv()).type == "hello.completed"
                    assert (await result(c, await c.system.time())).type == "job.completed"
                    assert b.events[:3] == [1, 8, 3]
                    assert (
                        b.fake is not None and sum(v["op"] == "hello" for v in b.fake.commands) == 1
                    )
        assert not any(
            t.name.startswith("paho-mqtt-client-") and t.ident not in before
            for t in threading.enumerate()
        )

    asyncio.run(run())


def test_websocket_actual_library_uses_text_message_and_typed_responses():
    async def run():
        fake = FakeTransport()
        await fake.open()

        async def handle(ws):
            assert ws.request.path == "/v3"
            async for text in ws:
                assert isinstance(text, str)
                await ws.send((await device_reply(fake, text.encode())).decode())

        async with serve(handle, "127.0.0.1", 0) as server:
            async with AsyncLimivia(job_poll_interval=0.01) as client:
                async with client.devices.connect(
                    kind="ws", target=f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/v3"
                ) as c:
                    assert (await result(c, await c.state.retrieve())).type == "state.completed"
                    assert (await result(c, await c.system.time())).type == "job.completed"

    asyncio.run(run())


@pytest.fixture
def certificates(tmp_path):
    key = tmp_path / "server.key"
    cert = tmp_path / "server.crt"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, str(cert)


@pytest.mark.parametrize("trust", [True, False])
def test_mqtt_tls_verifies_server_certificate(certificates, trust):
    async def run():
        context, ca = certificates
        async with broker(context=context) as (address, _b):
            async with AsyncLimivia(connect_timeout=3) as client:
                options = MQTTOptions(device_id=HELLO["device_id"], ca_file=ca if trust else None)
                if trust:
                    async with client.devices.connect(
                        kind="mqtt", target=f"mqtts://{address}", options=options
                    ) as c:
                        assert (await c.recv()).type == "hello.completed"
                else:
                    with pytest.raises(ssl.SSLError):
                        async with client.devices.connect(
                            kind="mqtt", target=f"mqtts://{address}", options=options
                        ):
                            pass

    asyncio.run(run())


@pytest.mark.parametrize("trust", [True, False])
def test_websocket_tls_verifies_server_certificate(certificates, trust):
    async def run():
        context, ca = certificates
        fake = FakeTransport()
        await fake.open()

        async def handle(ws):
            async for text in ws:
                await ws.send((await device_reply(fake, text.encode())).decode())

        async with serve(handle, "127.0.0.1", 0, ssl=context) as server:
            async with AsyncLimivia(connect_timeout=3) as client:
                manager = client.devices.connect(
                    kind="ws",
                    target=f"wss://127.0.0.1:{server.sockets[0].getsockname()[1]}/v3",
                    options=WebSocketOptions(ca_file=ca if trust else None),
                )
                if trust:
                    async with manager as c:
                        assert (await c.recv()).type == "hello.completed"
                else:
                    with pytest.raises(ssl.SSLError):
                        async with manager:
                            pass

    asyncio.run(run())


@pytest.mark.parametrize("payload", [b"{}", "x" * 8193])
def test_network_frames_reject_binary_or_oversize_or_multiline(payload):
    if isinstance(payload, bytes):
        assert _frame(payload) == b"{}\n"
    else:
        with pytest.raises(ConnectionError):
            _frame(payload)


def test_network_urls_and_secrets():
    options = MQTTOptions(device_id=HELLO["device_id"], username="user", password="never-log-me")
    assert "never-log-me" not in repr(options)
    with pytest.raises(ValueError):
        MQTTTransport("mqtt://user:secret@localhost", options)
    with pytest.raises(ValueError):
        MQTTTransport("mqtt://localhost/topic", options)
    with pytest.raises(ValueError):
        WebSocketTransport("http://localhost", WebSocketOptions())
    with pytest.raises(ValueError):
        MQTTOptions(device_id="not a mac")
    with pytest.raises(ValueError):
        MQTTOptions(device_id=HELLO["device_id"], logical_client="bad/#")


def test_mqtt_callback_queue_is_bounded_and_ignores_retained_and_other_topics():
    async def run():
        t = MQTTTransport("mqtt://localhost", MQTTOptions(device_id=HELLO["device_id"]))
        t.loop = asyncio.get_running_loop()
        t._on_message(None, None, SimpleNamespace(topic=t.reply_topic, retain=True, payload=b"bad"))
        await asyncio.sleep(0)
        assert t.queue.empty()
        for _ in range(33):
            t._push(b"{}\n")
        assert t.queue.qsize() == 32 and t.failed
        items = [await t.queue.get() for _ in range(32)]
        assert isinstance(items[-1], ConnectionError)
        await t.close()

    asyncio.run(run())
