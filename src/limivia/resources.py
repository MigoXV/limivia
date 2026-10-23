"""同步/异步复用的v3命令门面；方法只提交并返回请求ID。"""

from collections.abc import Callable
from typing import Any, Literal

from .types.commands import ClientEvent, ClientEventParam
from .types.models import ResourceKind


class Resource[T]:
    def __init__(self, send: Callable[[ClientEvent | ClientEventParam], T]):
        self._send = send


class SessionResource[T](Resource[T]):
    def ping(self) -> T:
        return self._send({"type": "session.ping", "params": {}})


class EventsResource[T](Resource[T]):
    def subscribe(
        self,
        *,
        topics: list[Literal["job", "resource", "flow", "data"]],
        interval_ms: int | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["topics"] = topics
        if interval_ms is not None:
            params["interval_ms"] = interval_ms
        return self._send({"type": "event.subscribe", "params": params})

    def unsubscribe(self) -> T:
        return self._send({"type": "event.unsubscribe", "params": {}})


class ControlResource[T](Resource[T]):
    def acquire(self) -> T:
        return self._send({"type": "control.acquire", "params": {}})

    def release(self) -> T:
        return self._send({"type": "control.release", "params": {}})


class OutputsResource[T](Resource[T]):
    def stop(self) -> T:
        return self._send({"type": "outputs.stop", "params": {}})


class CapabilitiesResource[T](Resource[T]):
    def retrieve(self, *, page: int | None = None) -> T:
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        return self._send({"type": "capabilities", "params": params})


class StateResource[T](Resource[T]):
    def __init__(
        self,
        send: Callable[[ClientEvent | ClientEventParam], T],
        snapshot: Callable[[], T] | None = None,
    ):
        super().__init__(send)
        self._snapshot = snapshot

    def snapshot(self) -> T:
        if self._snapshot is None:
            raise RuntimeError("此门面未连接状态聚合器")
        return self._snapshot()

    def retrieve(self, *, page: int | None = None, revision: int | None = None) -> T:
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        if revision is not None:
            params["revision"] = revision
        return self._send({"type": "state", "params": params})


class DiagnosticsResource[T](Resource[T]):
    def retrieve(self) -> T:
        return self._send({"type": "diagnostics", "params": {}})


class MuxResource[T](Resource[T]):
    def query(self, *, page: int | None = None, revision: int | None = None) -> T:
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        if revision is not None:
            params["revision"] = revision
        return self._send({"type": "mux.query", "params": params})

    def preflight(
        self,
        *,
        kind: ResourceKind,
        pins: dict[str, int],
        config: dict[str, Any],
        parent: int | None = None,
        controller: int | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["kind"] = kind
        params["pins"] = pins
        params["config"] = config
        if parent is not None:
            params["parent"] = parent
        if controller is not None:
            params["controller"] = controller
        return self._send({"type": "mux.preflight", "params": params})


class ResourceResource[T](Resource[T]):
    def preflight(
        self,
        *,
        kind: ResourceKind,
        pins: dict[str, int],
        config: dict[str, Any],
        parent: int | None = None,
        controller: int | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["kind"] = kind
        params["pins"] = pins
        params["config"] = config
        if parent is not None:
            params["parent"] = parent
        if controller is not None:
            params["controller"] = controller
        return self._send({"type": "resource.preflight", "params": params})

    def open(
        self,
        *,
        kind: ResourceKind,
        pins: dict[str, int],
        config: dict[str, Any],
        parent: int | None = None,
        controller: int | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["kind"] = kind
        params["pins"] = pins
        params["config"] = config
        if parent is not None:
            params["parent"] = parent
        if controller is not None:
            params["controller"] = controller
        return self._send({"type": "resource.open", "params": params})

    def get(self, *, resource: int) -> T:
        params: dict[str, Any] = {}
        params["resource"] = resource
        return self._send({"type": "resource.get", "params": params})

    def close(self, *, resource: int, cascade: bool | None = None) -> T:
        params: dict[str, Any] = {}
        params["resource"] = resource
        if cascade is not None:
            params["cascade"] = cascade
        return self._send({"type": "resource.close", "params": params})

    def recover(self, *, resource: int, cascade: bool | None = None) -> T:
        params: dict[str, Any] = {}
        params["resource"] = resource
        if cascade is not None:
            params["cascade"] = cascade
        return self._send({"type": "resource.recover", "params": params})

    def call(self, *, resource: int, action: str, args: dict[str, Any]) -> T:
        params: dict[str, Any] = {}
        params["resource"] = resource
        params["action"] = action
        params["args"] = args
        return self._send({"type": "resource.call", "params": params})


class JobResource[T](Resource[T]):
    def get(self, *, job_id: int) -> T:
        params: dict[str, Any] = {}
        params["job_id"] = job_id
        return self._send({"type": "job.get", "params": params})

    def cancel(self, *, job_id: int) -> T:
        params: dict[str, Any] = {}
        params["job_id"] = job_id
        return self._send({"type": "job.cancel", "params": params})


class GpioResource[T](Resource[T]):
    def group_read(self, *, resources: list[int]) -> T:
        params: dict[str, Any] = {}
        params["resources"] = [{"resource": resource} for resource in resources]
        return self._send({"type": "gpio.group.read", "params": params})

    def group_write(self, *, resources: list[dict[str, Any]]) -> T:
        params: dict[str, Any] = {}
        params["resources"] = resources
        return self._send({"type": "gpio.group.write", "params": params})


class RmtResource[T](Resource[T]):
    def sync(self, *, resources: list[dict[str, Any]], timeout_ms: int | None = None) -> T:
        params: dict[str, Any] = {}
        params["resources"] = resources
        if timeout_ms is not None:
            params["timeout_ms"] = timeout_ms
        return self._send({"type": "rmt.sync", "params": params})


class BufferResource[T](Resource[T]):
    def create(self, *, size: int) -> T:
        params: dict[str, Any] = {}
        params["size"] = size
        return self._send({"type": "buffer.create", "params": params})

    def write(self, *, buffer_id: int, offset: int, data: str | bytes) -> T:
        params: dict[str, Any] = {}
        params["buffer_id"] = buffer_id
        params["offset"] = offset
        params["data"] = data
        return self._send({"type": "buffer.write", "params": params})

    def read(self, *, buffer_id: int, offset: int, length: int) -> T:
        params: dict[str, Any] = {}
        params["buffer_id"] = buffer_id
        params["offset"] = offset
        params["length"] = length
        return self._send({"type": "buffer.read", "params": params})

    def delete(self, *, buffer_id: int) -> T:
        params: dict[str, Any] = {}
        params["buffer_id"] = buffer_id
        return self._send({"type": "buffer.delete", "params": params})


class StorageResource[T](Resource[T]):
    def status(self) -> T:
        return self._send({"type": "storage.status", "params": {}})

    def list(self, *, page: int | None = None) -> T:
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        return self._send({"type": "storage.list", "params": params})

    def format(self, *, confirm: str) -> T:
        params: dict[str, Any] = {}
        params["confirm"] = confirm
        return self._send({"type": "storage.format", "params": params})

    def begin(self, *, name: str, size: int, sha256: str, secret: bool | None = None) -> T:
        params: dict[str, Any] = {}
        params["name"] = name
        params["size"] = size
        params["sha256"] = sha256
        if secret is not None:
            params["secret"] = secret
        return self._send({"type": "storage.begin", "params": params})

    def chunk(self, *, upload_id: int, offset: int, data: str | bytes) -> T:
        params: dict[str, Any] = {}
        params["upload_id"] = upload_id
        params["offset"] = offset
        params["data"] = data
        return self._send({"type": "storage.chunk", "params": params})

    def commit(self, *, upload_id: int) -> T:
        params: dict[str, Any] = {}
        params["upload_id"] = upload_id
        return self._send({"type": "storage.commit", "params": params})

    def abort(self, *, upload_id: int) -> T:
        params: dict[str, Any] = {}
        params["upload_id"] = upload_id
        return self._send({"type": "storage.abort", "params": params})

    def read(self, *, name: str, offset: int, length: int) -> T:
        params: dict[str, Any] = {}
        params["name"] = name
        params["offset"] = offset
        params["length"] = length
        return self._send({"type": "storage.read", "params": params})

    def delete(self, *, name: str, secret: bool | None = None) -> T:
        params: dict[str, Any] = {}
        params["name"] = name
        if secret is not None:
            params["secret"] = secret
        return self._send({"type": "storage.delete", "params": params})

    def record(self, *, name: str, value: Any) -> T:
        params: dict[str, Any] = {}
        params["name"] = name
        params["value"] = value
        return self._send({"type": "storage.record", "params": params})

    def append(self, *, name: str, value: Any, limit_bytes: int) -> T:
        params: dict[str, Any] = {}
        params["name"] = name
        params["value"] = value
        params["limit_bytes"] = limit_bytes
        return self._send({"type": "storage.append", "params": params})


class OtaResource[T](Resource[T]):
    def status(self) -> T:
        return self._send({"type": "ota.status", "params": {}})

    def begin(self, *, board: str, protocol: int, profile: str, size: int, sha256: str) -> T:
        params: dict[str, Any] = {}
        params["board"] = board
        params["protocol"] = protocol
        params["profile"] = profile
        params["size"] = size
        params["sha256"] = sha256
        return self._send({"type": "ota.begin", "params": params})

    def chunk(self, *, upload_id: int, offset: int, data: str | bytes) -> T:
        params: dict[str, Any] = {}
        params["upload_id"] = upload_id
        params["offset"] = offset
        params["data"] = data
        return self._send({"type": "ota.chunk", "params": params})

    def commit(self, *, upload_id: int, reboot: bool | None = None) -> T:
        params: dict[str, Any] = {}
        params["upload_id"] = upload_id
        if reboot is not None:
            params["reboot"] = reboot
        return self._send({"type": "ota.commit", "params": params})

    def abort(self, *, upload_id: int) -> T:
        params: dict[str, Any] = {}
        params["upload_id"] = upload_id
        return self._send({"type": "ota.abort", "params": params})


class WifiResource[T](Resource[T]):
    def status(self) -> T:
        return self._send({"type": "wifi.status", "params": {}})

    def configure(self, *, ssid: str, password: str, persist: bool | None = None) -> T:
        params: dict[str, Any] = {}
        params["ssid"] = ssid
        params["password"] = password
        if persist is not None:
            params["persist"] = persist
        return self._send({"type": "wifi.configure", "params": params})

    def scan(self) -> T:
        return self._send({"type": "wifi.scan", "params": {}})

    def maintenance(self, *, enable: bool) -> T:
        params: dict[str, Any] = {}
        params["enable"] = enable
        return self._send({"type": "wifi.maintenance", "params": params})

    def disconnect(self) -> T:
        return self._send({"type": "wifi.disconnect", "params": {}})


class MqttResource[T](Resource[T]):
    def status(self) -> T:
        return self._send({"type": "mqtt.status", "params": {}})

    def configure(
        self,
        *,
        uri: str,
        protocol: Literal["3.1.1", "5.0"] | None = None,
        username: str | None = None,
        password: str | None = None,
        ca_pem: str | None = None,
        ca_file: str | None = None,
        certificate_file: str | None = None,
        private_key_file: str | None = None,
        will_topic: str | None = None,
        will: str | None = None,
        will_qos: int | None = None,
        will_retain: bool | None = None,
        persist: bool | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["uri"] = uri
        if protocol is not None:
            params["protocol"] = protocol
        if username is not None:
            params["username"] = username
        if password is not None:
            params["password"] = password
        if ca_pem is not None:
            params["ca_pem"] = ca_pem
        if ca_file is not None:
            params["ca_file"] = ca_file
        if certificate_file is not None:
            params["certificate_file"] = certificate_file
        if private_key_file is not None:
            params["private_key_file"] = private_key_file
        if will_topic is not None:
            params["will_topic"] = will_topic
        if will is not None:
            params["will"] = will
        if will_qos is not None:
            params["will_qos"] = will_qos
        if will_retain is not None:
            params["will_retain"] = will_retain
        if persist is not None:
            params["persist"] = persist
        return self._send({"type": "mqtt.configure", "params": params})

    def publish(
        self,
        *,
        topic: str,
        data: str | bytes | None = None,
        buffer_id: int | None = None,
        json: Any | None = None,
        qos: int | None = None,
        retain: bool | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["topic"] = topic
        if data is not None:
            params["data"] = data
        if buffer_id is not None:
            params["buffer_id"] = buffer_id
        if json is not None:
            params["json"] = json
        if qos is not None:
            params["qos"] = qos
        if retain is not None:
            params["retain"] = retain
        return self._send({"type": "mqtt.publish", "params": params})

    def subscribe(self, *, topic: str, qos: int | None = None) -> T:
        params: dict[str, Any] = {}
        params["topic"] = topic
        if qos is not None:
            params["qos"] = qos
        return self._send({"type": "mqtt.subscribe", "params": params})

    def unsubscribe(self, *, topic: str) -> T:
        params: dict[str, Any] = {}
        params["topic"] = topic
        return self._send({"type": "mqtt.unsubscribe", "params": params})

    def receive(self) -> T:
        return self._send({"type": "mqtt.receive", "params": {}})

    def stop(self) -> T:
        return self._send({"type": "mqtt.stop", "params": {}})


class EspnowResource[T](Resource[T]):
    def status(self) -> T:
        return self._send({"type": "espnow.status", "params": {}})

    def start(self, *, pmk: str | bytes | None = None) -> T:
        params: dict[str, Any] = {}
        if pmk is not None:
            params["pmk"] = pmk
        return self._send({"type": "espnow.start", "params": params})

    def stop(self) -> T:
        return self._send({"type": "espnow.stop", "params": {}})

    def peer(self, *, mac: str, encrypt: bool | None = None, key: str | bytes | None = None) -> T:
        params: dict[str, Any] = {}
        params["mac"] = mac
        if encrypt is not None:
            params["encrypt"] = encrypt
        if key is not None:
            params["key"] = key
        return self._send({"type": "espnow.peer", "params": params})

    def remove(self, *, mac: str) -> T:
        params: dict[str, Any] = {}
        params["mac"] = mac
        return self._send({"type": "espnow.remove", "params": params})

    def send(
        self,
        *,
        mac: str,
        data: str | bytes | None = None,
        buffer_id: int | None = None,
        timeout_ms: int | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["mac"] = mac
        if data is not None:
            params["data"] = data
        if buffer_id is not None:
            params["buffer_id"] = buffer_id
        if timeout_ms is not None:
            params["timeout_ms"] = timeout_ms
        return self._send({"type": "espnow.send", "params": params})

    def receive(self) -> T:
        return self._send({"type": "espnow.receive", "params": {}})


class PowerResource[T](Resource[T]):
    def configure(
        self, *, auto_light_sleep: bool | None = None, modem_sleep: str | None = None
    ) -> T:
        params: dict[str, Any] = {}
        if auto_light_sleep is not None:
            params["auto_light_sleep"] = auto_light_sleep
        if modem_sleep is not None:
            params["modem_sleep"] = modem_sleep
        return self._send({"type": "power.configure", "params": params})

    def sleep(
        self,
        *,
        mode: str,
        duration_ms: int,
        wake_pin: int | None = None,
        wake_level: int | None = None,
    ) -> T:
        params: dict[str, Any] = {}
        params["mode"] = mode
        params["duration_ms"] = duration_ms
        if wake_pin is not None:
            params["wake_pin"] = wake_pin
        if wake_level is not None:
            params["wake_level"] = wake_level
        return self._send({"type": "power.sleep", "params": params})


class SystemResource[T](Resource[T]):
    def info(self) -> T:
        return self._send({"type": "system.info", "params": {}})

    def time(self) -> T:
        return self._send({"type": "system.time", "params": {}})

    def restart(self) -> T:
        return self._send({"type": "system.restart", "params": {}})

    def nvs_format(self, *, confirm: str) -> T:
        params: dict[str, Any] = {}
        params["confirm"] = confirm
        return self._send({"type": "system.nvs_format", "params": params})


class FlowResource[T](Resource[T]):
    def load(self, *, name: str) -> T:
        params: dict[str, Any] = {}
        params["name"] = name
        return self._send({"type": "flow.load", "params": params})

    def list(self) -> T:
        return self._send({"type": "flow.list", "params": {}})

    def get(self, *, flow_id: int) -> T:
        params: dict[str, Any] = {}
        params["flow_id"] = flow_id
        return self._send({"type": "flow.get", "params": params})

    def start(self, *, flow_id: int) -> T:
        params: dict[str, Any] = {}
        params["flow_id"] = flow_id
        return self._send({"type": "flow.start", "params": params})

    def pause(self, *, flow_id: int) -> T:
        params: dict[str, Any] = {}
        params["flow_id"] = flow_id
        return self._send({"type": "flow.pause", "params": params})

    def resume(self, *, flow_id: int) -> T:
        params: dict[str, Any] = {}
        params["flow_id"] = flow_id
        return self._send({"type": "flow.resume", "params": params})

    def stop(self, *, flow_id: int) -> T:
        params: dict[str, Any] = {}
        params["flow_id"] = flow_id
        return self._send({"type": "flow.stop", "params": params})

    def remove(self, *, flow_id: int) -> T:
        params: dict[str, Any] = {}
        params["flow_id"] = flow_id
        return self._send({"type": "flow.remove", "params": params})


class Resources[T]:
    def __init__(
        self,
        send: Callable[[ClientEvent | ClientEventParam], T],
        *,
        snapshot: Callable[[], T] | None = None,
    ):
        self.session = SessionResource(send)
        self.events = EventsResource(send)
        self.control = ControlResource(send)
        self.outputs = OutputsResource(send)
        self.capabilities = CapabilitiesResource(send)
        self.state = StateResource(send, snapshot)
        self.diagnostics = DiagnosticsResource(send)
        self.mux = MuxResource(send)
        self.resource = ResourceResource(send)
        self.job = JobResource(send)
        self.gpio = GpioResource(send)
        self.rmt = RmtResource(send)
        self.buffer = BufferResource(send)
        self.storage = StorageResource(send)
        self.ota = OtaResource(send)
        self.wifi = WifiResource(send)
        self.mqtt = MqttResource(send)
        self.espnow = EspnowResource(send)
        self.power = PowerResource(send)
        self.system = SystemResource(send)
        self.flow = FlowResource(send)
