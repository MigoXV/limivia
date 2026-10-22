"""设备 v1 编解码。SDK 事件名称与固件字段之间的唯一映射。"""

from __future__ import annotations

import codecs
import json
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from ._exceptions import InvalidCommandError, ProtocolError
from .types import ClientEvent, ClientEventParam, DeviceEvent, Operation

COMMAND_ADAPTER: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)  # type: ignore[arg-type]  # PEP 695 alias
EVENT_ADAPTER: TypeAdapter[DeviceEvent] = TypeAdapter(DeviceEvent)  # type: ignore[arg-type]  # PEP 695 alias
OPERATIONS = {
    "hello",
    "state",
    "gpio.set",
    "gpio.read",
    "pwm.set",
    "pwm.stop",
    "adc.read",
    "adc.start",
    "adc.stop",
    "timer.start",
    "timer.stop",
    "pin.release",
    "outputs.stop",
}


def parse_command(event: ClientEvent | ClientEventParam | dict[str, Any]) -> ClientEvent:
    value = event.model_dump() if isinstance(event, BaseModel) else event
    try:
        command = COMMAND_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise InvalidCommandError(str(exc)) from exc
    if command.type == "gpio.set":
        params = command.params
        if params["mode"] == "output" and params["pull"] != "none":
            raise InvalidCommandError("输出模式必须使用 pull=none。")
    if command.type == "pwm.set":
        breath = command.params.get("breath_ms", 0)
        if 0 < breath < 200:
            raise InvalidCommandError("breath_ms 必须为 0 或 200–60000。")
    return command


def encode_command(command: ClientEvent, request_id: int) -> bytes:
    frame = {"v": 1, "id": request_id, "op": command.type, "params": command.params}
    data = (
        json.dumps(frame, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode()
    if len(data) > 1025:
        raise InvalidCommandError("命令内容不得超过 1024 bytes。")
    return data


def parse_wire_command(text: str) -> tuple[int, ClientEvent]:
    if len(text.encode()) > 1025 or not text.endswith("\n") or "\n" in text[:-1] or "\0" in text:
        raise ProtocolError("命令须为单行 JSON，内容不得超过 1024 bytes。")
    try:
        value = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("命令 JSON 格式无效。") from exc
    if (
        not isinstance(value, dict)
        or type(value.get("v")) is not int
        or value["v"] != 1
        or type(value.get("id")) is not int
        or not 1 <= value["id"] <= 2147483647
        or not isinstance(value.get("op"), str)
        or not value["op"]
        or not isinstance(value.get("params"), dict)
    ):
        raise ProtocolError("命令必须包含协议 v=1、有效 id、op 和 params。")
    if value["op"] not in OPERATIONS:
        raise InvalidCommandError(
            "当前 SDK 不支持此操作。", code="unknown_operation", request_id=value["id"]
        )
    try:
        return value["id"], parse_command({"type": value["op"], "params": value["params"]})
    except InvalidCommandError as exc:
        exc.request_id = value["id"]
        raise


def decode_message(message: dict[str, Any], op: Operation | None = None) -> DeviceEvent:
    if type(message.get("v")) is not int or message["v"] != 1:
        raise ProtocolError("设备协议版本无效。")
    event = message.get("event")
    if event == "changed":
        value = {"type": "state.changed", "revision": message.get("revision")}
    elif event == "adc":
        value = {"type": "adc.sample", "data": message.get("data")}
    elif event is not None:
        value = {"type": "unknown", "raw": message}
    elif op is not None and type(message.get("id")) is int:
        if message.get("ok") is True:
            value = {
                "type": f"{op}.completed",
                "op": op,
                "request_id": message["id"],
                "result": message.get("result"),
            }
        elif message.get("ok") is False:
            value = {
                "type": "command.failed",
                "op": op,
                "request_id": message["id"],
                "error": message.get("error"),
            }
        else:
            raise ProtocolError("设备响应缺少 ok。")
    else:
        raise ProtocolError("设备返回无请求 ID 的错误或无法关联的应答。")
    try:
        return EVENT_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ProtocolError(f"设备响应字段无效：{exc}") from exc


def event_to_wire(event: DeviceEvent, request_id: int | None = None) -> str | None:
    """桥接时由调用方提供浏览器请求 ID；SDK 内部 ID 不泄漏给浏览器。"""
    value: dict[str, Any]
    if event.type == "state.changed":
        value = {"v": 1, "event": "changed", "revision": event.revision}
    elif event.type == "adc.sample":
        value = {"v": 1, "event": "adc", "data": event.data.to_dict()}
    elif event.type == "unknown":
        value = event.raw
    elif event.type == "command.failed":
        if request_id is None:
            return None
        value = {
            "v": 1,
            "id": request_id,
            "ok": False,
            "error": {"code": event.error.code, "message": event.error.message},
        }
    elif event.type == "connection.closed" or event.type == "protocol.error":
        return None
    else:
        if request_id is None:
            return None
        value = {"v": 1, "id": request_id, "ok": True, "result": event.result.to_dict()}
    return json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"


class LineReader:
    """UTF-8 分片重组；超长行丢弃至 LF 后恢复，不无限累积设备输出。"""

    def __init__(self, max_length: int = 8192):
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.buffer = ""
        self.dropping = False
        self.max_length = max_length

    def feed(self, data: bytes) -> list[str | ProtocolError]:
        lines: list[str | ProtocolError] = []
        for char in self.decoder.decode(data):
            if char == "\n":
                if self.buffer.strip() and not self.dropping:
                    lines.append(self.buffer)
                self.buffer = ""
                self.dropping = False
            elif not self.dropping:
                self.buffer += char
                if len(self.buffer) > self.max_length:
                    self.buffer = ""
                    self.dropping = True
                    lines.append(ProtocolError("设备帧超过 8192 characters，已丢弃至换行。"))
        return lines
