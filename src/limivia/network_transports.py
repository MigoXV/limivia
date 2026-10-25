"""有界消息传输适配；MQTT回调线程不直接触碰asyncio状态。"""

from __future__ import annotations

import asyncio
import ssl
import uuid
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

from paho.mqtt import client as mqtt
from websockets.asyncio.client import ClientConnection, connect

from .constants import MQTTProtocol
from .types import MQTTOptions, WebSocketOptions


def _url(target: str, schemes: tuple[str, ...]):
    value = urlsplit(target)
    if (
        value.scheme not in schemes
        or not value.hostname
        or value.username is not None
        or value.password is not None
        or value.fragment
    ):
        raise ValueError("需要无内嵌凭据的明确传输URL")
    # Validate the port before opening any socket.
    _ = value.port
    return value


def _tls(options: WebSocketOptions) -> ssl.SSLContext:
    if bool(options.certificate_file) != bool(options.private_key_file):
        raise ValueError("客户端证书与私钥必须成对提供")
    ctx = ssl.create_default_context(cafile=options.ca_file)
    if options.certificate_file:
        ctx.load_cert_chain(options.certificate_file, options.private_key_file)
    return ctx


def _frame(payload: str | bytes) -> bytes:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not data.endswith(b"\n"):
        data += b"\n"
    if len(data) > 8193 or b"\0" in data:
        raise ConnectionError("网络消息不符合单帧8192字节契约")
    return data


class WebSocketTransport:
    message_framed = True

    def __init__(self, target: str, options: WebSocketOptions):
        value = _url(target, ("ws", "wss"))
        if value.scheme == "ws" and any(
            (options.ca_file, options.certificate_file, options.private_key_file)
        ):
            raise ValueError("TLS选项需要wss://")
        self.target = target
        self.options = options
        self.connection: ClientConnection | None = None

    async def open(self) -> None:
        kwargs: dict[str, Any] = (
            {"ssl": _tls(self.options)} if self.target.startswith("wss://") else {}
        )
        self.connection = await connect(
            self.target,
            proxy=None,
            compression=None,
            max_size=8193,
            max_queue=16,
            open_timeout=10,
            close_timeout=3,
            **kwargs,
        )

    async def read(self) -> bytes:
        if self.connection is None:
            raise ConnectionError("WS未连接")
        text = await self.connection.recv()
        if not isinstance(text, str):
            raise ConnectionError("WS仅接受TEXT消息")
        return _frame(text)

    async def write(self, data: bytes) -> None:
        if self.connection is None:
            raise ConnectionError("WS未连接")
        await self.connection.send(data.decode("utf-8").removesuffix("\n"))

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None


class MQTTTransport:
    message_framed = True

    def __init__(self, target: str, options: MQTTOptions):
        self.url = _url(target, ("mqtt", "mqtts"))
        if self.url.path not in ("", "/") or self.url.query:
            raise ValueError("MQTT URL不包含路径或query；设备由device_id指定")
        if self.url.scheme == "mqtt" and any(
            (options.ca_file, options.certificate_file, options.private_key_file)
        ):
            raise ValueError("TLS选项需要mqtts://")
        self.options = options
        name = options.logical_client or uuid.uuid4().hex
        prefix = f"limivia/{options.device_id.replace(':', '')}"
        self.command_topic = f"{prefix}/command/{name}"
        self.reply_topic = f"{prefix}/reply/{name}"
        self.queue: asyncio.Queue[bytes | Exception] = asyncio.Queue(32)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ready: asyncio.Future[None] | None = None
        self.failed = False
        self.closed = False
        self._connect_task: asyncio.Task | None = None
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="lv-" + uuid.uuid4().hex[:20],
            protocol=mqtt.MQTTv5 if options.protocol == MQTTProtocol.V5 else mqtt.MQTTv311,
            clean_session=None if options.protocol == MQTTProtocol.V5 else True,
            reconnect_on_failure=False,
        )
        self.client.connect_timeout = 5
        self.client.max_queued_messages_set(8)
        if options.username is not None:
            self.client.username_pw_set(
                options.username.get_secret_value(),
                options.password.get_secret_value() if options.password else None,
            )
        elif options.password is not None:
            raise ValueError("password需要username")
        if self.url.scheme == "mqtts":
            self.client.tls_set_context(_tls(options))
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _dispatch(self, callback, *args):
        loop = self.loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(callback, *args)

    def _push(self, value: bytes | Exception) -> None:
        if self.closed or self.failed:
            return
        if self.queue.full():
            self.queue.get_nowait()
            value = ConnectionError("MQTT接收缓冲溢出")
        if isinstance(value, Exception):
            self.failed = True
        self.queue.put_nowait(value)

    def _ready_result(self, error: Exception | None = None) -> None:
        if self.ready and not self.ready.done():
            if error:
                self.ready.set_exception(error)
            else:
                self.ready.set_result(None)

    def _on_connect(self, client, userdata, flags, reason, properties) -> None:
        if reason.is_failure:
            self._dispatch(self._ready_result, ConnectionError("MQTT CONNACK拒绝"))
            return
        rc, _ = client.subscribe(self.reply_topic, qos=1)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            self._dispatch(self._ready_result, ConnectionError("MQTT订阅发送失败"))

    def _on_subscribe(self, client, userdata, mid, reasons, properties) -> None:
        error = (
            ConnectionError("MQTT SUBACK拒绝")
            if any(reason.is_failure for reason in reasons)
            else None
        )
        self._dispatch(self._ready_result, error)

    def _on_message(self, client, userdata, message) -> None:
        if message.topic != self.reply_topic or message.retain:
            return
        value: bytes | Exception
        try:
            value = _frame(bytes(message.payload))
        except (ConnectionError, UnicodeError, TypeError):
            value = ConnectionError("MQTT回复帧无效")
        self._dispatch(self._push, value)

    def _on_disconnect(self, client, userdata, flags, reason, properties) -> None:
        self._dispatch(self._ready_result, ConnectionError("MQTT订阅完成前断开"))
        self._dispatch(self._push, ConnectionError("MQTT已断开；不自动重连"))

    async def open(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.ready = self.loop.create_future()
        port = self.url.port or (8883 if self.url.scheme == "mqtts" else 1883)
        self._connect_task = asyncio.create_task(
            asyncio.to_thread(self.client.connect, self.url.hostname, port, 30)
        )
        await asyncio.shield(self._connect_task)
        self.client.loop_start()
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), timeout=10)
        except BaseException:
            await self.close()
            raise

    async def read(self) -> bytes:
        value = await self.queue.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def write(self, data: bytes) -> None:
        if self.closed or self.failed or not self.client.is_connected():
            raise ConnectionError("MQTT未连接")
        # QoS0 + no reconnect prevents the library from replaying control writes.
        result = self.client.publish(
            self.command_topic, data.removesuffix(b"\n"), qos=0, retain=False
        )
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("MQTT发布未准入；不重试")

    async def close(self) -> None:
        self.closed = True
        if self._connect_task:
            with suppress(Exception):
                await asyncio.shield(self._connect_task)
        self.client.disconnect()
        await asyncio.to_thread(self.client.loop_stop)
        if self.ready and not self.ready.done():
            self.ready.cancel()
        elif self.ready and not self.ready.cancelled():
            self.ready.exception()
