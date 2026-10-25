"""v3公开提交模型；所有命令通过同一验证与编码路径。"""

from typing import Any, Literal, TypedDict

from pydantic import ConfigDict, Field

from .._models import Model

type Operation = Literal[
    "hello",
    "session.ping",
    "event.subscribe",
    "event.unsubscribe",
    "control.acquire",
    "control.release",
    "outputs.stop",
    "capabilities",
    "state",
    "diagnostics",
    "mux.query",
    "mux.preflight",
    "resource.preflight",
    "resource.open",
    "resource.get",
    "resource.close",
    "resource.recover",
    "resource.call",
    "job.get",
    "job.cancel",
    "gpio.group.read",
    "gpio.group.write",
    "rmt.sync",
    "buffer.create",
    "buffer.write",
    "buffer.read",
    "buffer.delete",
    "storage.status",
    "storage.list",
    "storage.format",
    "storage.begin",
    "storage.chunk",
    "storage.commit",
    "storage.abort",
    "storage.read",
    "storage.delete",
    "storage.record",
    "storage.append",
    "ota.status",
    "ota.begin",
    "ota.chunk",
    "ota.commit",
    "ota.abort",
    "wifi.status",
    "wifi.configure",
    "wifi.scan",
    "wifi.maintenance",
    "wifi.disconnect",
    "mqtt.status",
    "mqtt.configure",
    "mqtt.publish",
    "mqtt.subscribe",
    "mqtt.unsubscribe",
    "mqtt.receive",
    "mqtt.stop",
    "espnow.status",
    "espnow.start",
    "espnow.stop",
    "espnow.peer",
    "espnow.remove",
    "espnow.send",
    "espnow.receive",
    "power.configure",
    "power.sleep",
    "system.info",
    "system.time",
    "system.restart",
    "system.nvs_format",
    "flow.load",
    "flow.list",
    "flow.get",
    "flow.start",
    "flow.pause",
    "flow.resume",
    "flow.stop",
    "flow.remove",
]


class ClientEventParam(TypedDict):
    type: Operation
    params: dict[str, Any]


class ClientEvent(Model):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Operation
    params: dict[str, Any] = Field(default_factory=dict)
