"""协议v3包络、严格编解码与SDK事件映射；不复制板级资源政策。"""

from __future__ import annotations

import base64
import json
import math
import secrets
import time
from typing import Any, get_args

from pydantic import TypeAdapter, ValidationError

from ._exceptions import InvalidCommandError, ProtocolError
from ._schema import OPERATIONS, REQUIRED
from .constants import EventType, OperationName, ResourceAction
from .types import (
    ClientEvent,
    ClientEventParam,
    DeviceError,
    DeviceEvent,
    Operation,
    ResourceKind,
    ResponseEvent,
    RpcErrorEvent,
    UnknownEvent,
)

EVENT_ADAPTER: TypeAdapter[DeviceEvent] = TypeAdapter(DeviceEvent)  # type: ignore[arg-type]
RPC_MANAGEMENT = {OperationName.HELLO, OperationName.SESSION_PING, OperationName.JOB_GET}
MANAGEMENT = {
    OperationName.HELLO,
    OperationName.SESSION_PING,
    OperationName.JOB_GET,
    OperationName.CAPABILITIES,
    OperationName.STATE,
    OperationName.DIAGNOSTICS,
    OperationName.RESOURCE_GET,
    OperationName.FLOW_GET,
    OperationName.FLOW_LIST,
    OperationName.MUX_QUERY,
}
OBSERVERS = {
    OperationName.HELLO,
    OperationName.SESSION_PING,
    OperationName.EVENT_SUBSCRIBE,
    OperationName.EVENT_UNSUBSCRIBE,
    OperationName.CONTROL_ACQUIRE,
    OperationName.CAPABILITIES,
    OperationName.STATE,
    OperationName.DIAGNOSTICS,
    OperationName.MUX_QUERY,
    OperationName.MUX_PREFLIGHT,
    OperationName.RESOURCE_PREFLIGHT,
    OperationName.RESOURCE_GET,
    OperationName.FLOW_GET,
    OperationName.FLOW_LIST,
    OperationName.JOB_GET,
    OperationName.OUTPUTS_STOP,
    OperationName.GPIO_GROUP_READ,
}
CONTROL_REQUIRED = set(OPERATIONS) - OBSERVERS
# These return device jobs. Public job.get/cancel describe another job and aren't new jobs.
JOB_OPERATIONS = {
    op
    for op in OPERATIONS
    if op.startswith(("storage.", "ota.", "wifi.", "mqtt.", "espnow.", "power.", "system."))
} | {
    OperationName.FLOW_LOAD,
    OperationName.RESOURCE_OPEN,
    OperationName.RESOURCE_CALL,
    OperationName.RESOURCE_CLOSE,
    OperationName.RESOURCE_RECOVER,
    OperationName.GPIO_GROUP_READ,
    OperationName.GPIO_GROUP_WRITE,
    OperationName.RMT_SYNC,
    OperationName.OUTPUTS_STOP,
}


def control_required(command: ClientEvent) -> bool:
    if command.type == OperationName.RESOURCE_CALL:
        # Device remains authoritative for the kind-specific read operations.
        return command.params.get("action") not in (
            ResourceAction.STATUS,
            ResourceAction.READ,
            ResourceAction.INFO,
        )
    return command.type in CONTROL_REQUIRED


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON含重复字段")
        result[key] = value
    return result


def _json_value(value: Any, depth: int = 0) -> None:
    if isinstance(value, str):
        if "\0" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("JSON字符串无效")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON数值必须有限")
    elif isinstance(value, (list, dict)):
        if depth >= 16:
            raise ValueError("JSON嵌套超过16层")
        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(k, str):
                    raise TypeError("JSON字段名必须是字符串")
                _json_value(k, depth)
                _json_value(v, depth + 1)
        else:
            for v in value:
                _json_value(v, depth + 1)
    elif value is not None and type(value) not in (bool, int):
        raise ValueError("不是JSON值")


def load_json(text: str) -> Any:
    value = json.loads(text, object_pairs_hook=_unique_object)
    _json_value(value)
    return value


def _normalize(value: Any) -> Any:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _integer(value: Any, low=0, high=2147483647) -> bool:
    return type(value) is int and low <= value <= high


def canonical_binary(value: str) -> bytes:
    if not isinstance(value, str):
        raise TypeError("data必须为Base64字符串或bytes")
    result = base64.b64decode(value, validate=True)
    if base64.b64encode(result).decode() != value:
        raise ValueError("Base64非规范pad位")
    return result


def parse_command(event: ClientEvent | ClientEventParam | dict[str, Any]) -> ClientEvent:
    raw = event.model_dump() if isinstance(event, ClientEvent) else event
    try:
        command = ClientEvent.model_validate(_normalize(raw))
        op, p = command.type, command.params
        _json_value(p)
        if set(p) - set(OPERATIONS[op]) or set(REQUIRED.get(op, [])) - set(p):
            raise ValueError("命令包含未知参数或缺少必填参数")
        for key, value in p.items():
            if key in {"resource", "parent", "job_id", "buffer_id", "upload_id", "flow_id"}:
                if not _integer(value, 1):
                    raise ValueError(f"{key}需要正整数")
            elif key in {
                "offset",
                "length",
                "size",
                "page",
                "revision",
                "duration_ms",
                "controller",
                "interval_ms",
                "limit_bytes",
            }:
                if not _integer(value):
                    raise ValueError(f"{key}需要非负整数")
            elif key in {
                "cascade",
                "reboot",
                "persist",
                "enable",
                "retain",
                "will_retain",
                "encrypt",
                "auto_light_sleep",
                "secret",
            }:
                if type(value) is not bool:
                    raise ValueError(f"{key}需要bool")
            elif key in {"pins", "config", "args"}:
                if type(value) is not dict:
                    raise ValueError(f"{key}需要对象")
            elif key in {"topics", "resources"}:
                if type(value) is not list:
                    raise ValueError(f"{key}需要数组")
            elif key not in {
                "json",
                "value",
                "protocol",
                "qos",
                "will_qos",
                "wake_pin",
                "wake_level",
                "timeout_ms",
            } and not isinstance(value, str):
                raise ValueError(f"{key}需要字符串")
        if "kind" in p and p["kind"] not in get_args(ResourceKind.__value__):
            raise ValueError("未知资源kind")
        if "pins" in p and any(
            not isinstance(k, str) or not _integer(v, 0, 21) for k, v in p["pins"].items()
        ):
            raise ValueError("pins需要GPIO整数映射")
        if (
            op in (OperationName.MQTT_PUBLISH, OperationName.ESPNOW_SEND)
            and sum(k in p for k in ("data", "buffer_id", "json")) != 1
        ):
            raise ValueError("必须且只能提供一种payload")
        payloads = (
            [p]
            if op
            in (
                OperationName.BUFFER_WRITE,
                OperationName.STORAGE_CHUNK,
                OperationName.OTA_CHUNK,
                OperationName.MQTT_PUBLISH,
                OperationName.ESPNOW_SEND,
            )
            else []
        )
        if op == OperationName.RESOURCE_CALL:
            args = p["args"]
            if "data" in args and "buffer_id" in args:
                raise ValueError("data和buffer_id互斥")
            if "timeout_ms" in args and not _integer(args["timeout_ms"], 0, 1000):
                raise ValueError("timeout_ms需要0..1000")
            payloads.append(args)
        if op in {
            OperationName.GPIO_GROUP_READ,
            OperationName.GPIO_GROUP_WRITE,
            OperationName.RMT_SYNC,
        }:
            allowed = {"resource"} | (
                {"level"}
                if op == OperationName.GPIO_GROUP_WRITE
                else {"data"}
                if op == OperationName.RMT_SYNC
                else set()
            )
            for item in p["resources"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != allowed
                    or not _integer(item.get("resource"), 1)
                ):
                    raise ValueError("resources需要资源对象数组")
                if op == OperationName.GPIO_GROUP_WRITE and not _integer(item["level"], 0, 1):
                    raise ValueError("level需要0或1")
        if op == OperationName.RMT_SYNC:
            payloads.extend(p["resources"])
        for payload in payloads:
            if "data" in payload:
                canonical_binary(payload["data"])
        return command
    except ValidationError:
        raise InvalidCommandError("命令字段或类型不符合v3契约") from None
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise InvalidCommandError(f"无效v3命令：{exc}") from None


class MissingId:
    """缺少id是通知；与显式null严格区分。"""


MISSING_ID = MissingId()
type RpcId = str | int | float | None


def valid_id(value: Any) -> bool:
    return (
        value is None
        or type(value) in (str, int)
        or (type(value) is float and math.isfinite(value))
    )


def command_object(
    command: ClientEvent,
    wire_id: RpcId | MissingId,
    *,
    session: str | None = None,
    control: str | None = None,
    seq: int = 1,
    client_nonce: str | None = None,
    positional: bool = False,
) -> dict[str, Any]:
    if not isinstance(wire_id, MissingId) and not valid_id(wire_id):
        raise InvalidCommandError("无效JSON-RPC ID")
    context: dict[str, Any] = {}
    if command.type == OperationName.HELLO:
        context["client_nonce"] = (
            client_nonce if client_nonce is not None else secrets.token_hex(16)
        )
    else:
        if not _integer(seq, 1):
            raise InvalidCommandError("seq需要1..2147483647")
        context["seq"] = seq
        if session is not None:
            context["session"] = session
        if control is not None:
            context["control"] = control
    result: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": command.type,
        "params": [context, command.params]
        if positional
        else {
            "context": context,
            "args": command.params,
        },
    }
    if not isinstance(wire_id, MissingId):
        result["id"] = wire_id
    return result


def encode_frame(value: Any, *, maximum: int = 1024) -> bytes:
    try:
        _json_value(value)
        data = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise InvalidCommandError("无法编码JSON-RPC帧") from exc
    if len(data) > min(maximum, 1024):
        raise InvalidCommandError("命令整帧超过1024 bytes；请使用显式buffer或chunk接口")
    return data + b"\n"


def encode_command(
    command: ClientEvent,
    request_id: RpcId | MissingId,
    *,
    session: str | None = None,
    control: str | None = None,
    seq: int = 1,
    client_nonce: str | None = None,
    positional: bool = False,
    maximum: int = 1024,
) -> bytes:
    return encode_frame(
        command_object(
            command,
            request_id,
            session=session,
            control=control,
            seq=seq,
            client_nonce=client_nonce,
            positional=positional,
        ),
        maximum=maximum,
    )


def parse_wire_command(text: str) -> tuple[RpcId | MissingId, ClientEvent]:
    try:
        if len(text.removesuffix("\n").encode()) > 1024:
            raise ValueError("请求过长")
        value = load_json(text)
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise ValueError("需要JSON-RPC2.0")
        rid = value.get("id", MISSING_ID)
        if not isinstance(rid, MissingId) and not valid_id(rid):
            raise ValueError("错误ID")
        params = value.get("params", {})
        if isinstance(params, list):
            if len(params) > 2:
                raise ValueError("多余位置参数")
            context, args = (params + [{}, {}])[:2]
        elif isinstance(params, dict) and not set(params) - {"context", "args"}:
            context, args = params.get("context", {}), params.get("args", {})
        else:
            raise ValueError("错误params")
        if not isinstance(context, dict) or set(context) - {
            "session",
            "seq",
            "control",
            "client_nonce",
        }:
            raise ValueError("错误context")
        command = parse_command({"type": value["method"], "params": args})
        if command.type == OperationName.HELLO:
            nonce = context.get("client_nonce", "")
            if (
                set(context) != {"client_nonce"}
                or not isinstance(nonce, str)
                or (len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce))
            ):
                raise ValueError("错误nonce")
        elif not isinstance(context.get("session"), str) or not _integer(context.get("seq"), 1):
            raise ValueError("缺少会话或seq")
        if "control" in context and not isinstance(context["control"], str):
            raise ValueError("错误control")
        return rid, command
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise ProtocolError("无效JSON-RPC请求") from exc


def response_context(message: dict[str, Any]) -> dict[str, Any]:
    body = message.get("result", {})
    if "error" in message:
        body = message["error"].get("data", {})
    context = body.get("context", {})
    if not isinstance(context, dict):
        raise ProtocolError("响应context需要对象")
    return context


def decode_message(
    message: dict[str, Any],
    op: Operation | None = None,
    *,
    request_id: int | None = None,
) -> DeviceEvent:
    try:
        if message.get("jsonrpc") != "2.0":
            raise ValueError("设备需要JSON-RPC2.0契约")
        if "method" in message:
            if "id" in message or ResourceAction.RESULT in message or "error" in message:
                raise ValueError("通知包络无效")
            name = message["method"]
            params = message.get("params", {})
            if isinstance(params, list):
                if len(params) > 2:
                    raise ValueError("通知位置参数过多")
                context, args = (params + [{}, {}])[:2]
            else:
                context, args = params.get("context", {}), params.get("args", {})
            value = (
                {"type": name, **context, **args}
                if name
                in (EventType.JOB_FINISHED, EventType.STATE_CHANGED, EventType.DATA_AVAILABLE)
                else {"type": EventType.UNKNOWN, "raw": message}
            )
        else:
            if "id" not in message or not valid_id(message["id"]):
                raise ValueError("响应需要ID")
            if (ResourceAction.RESULT in message) == ("error" in message):
                raise ValueError("result/error必须互斥")
            context = response_context(message)
            if request_id is None and type(message["id"]) is int and message["id"] > 0:
                request_id = message["id"]
            error = None
            if "error" in message:
                raw = message["error"]
                if type(raw["code"]) is not int or not isinstance(raw["message"], str):
                    raise ValueError("错误码需要整数")
                data = raw.get("data", {})
                error = DeviceError(
                    code=raw["code"],
                    reason=data["reason"],
                    message=raw["message"],
                    data=data,
                    external_effect_possible=data.get("external_effect_possible", False),
                    may_have_executed=data.get("external_effect_possible", False),
                )
            if op is None or request_id is None:
                if error is not None:
                    return RpcErrorEvent(wire_id=message["id"], error=error)
                return UnknownEvent(raw=message)
            meta = {"request_id": request_id, "op": op, **context}
            if error is not None:
                jid = error.data.get("job_id")
                value = {
                    "type": EventType.COMMAND_FAILED,
                    **meta,
                    "error": error,
                    "job_id": jid if _integer(jid, 1) else None,
                }
            else:
                result = message["result"]["value"]
                if not isinstance(result, dict):
                    raise ValueError("value需要对象")
                if op in JOB_OPERATIONS and "job_id" in result:
                    value = {"type": EventType.COMMAND_ACCEPTED, **meta, "job": result}
                else:
                    name = (
                        f"{op}.completed"
                        if op
                        in (
                            OperationName.HELLO,
                            OperationName.STATE,
                            OperationName.CAPABILITIES,
                            OperationName.RESOURCE_GET,
                            OperationName.DIAGNOSTICS,
                        )
                        else EventType.COMMAND_COMPLETED
                    )
                    value = {"type": name, **meta, "result": result}
        return EVENT_ADAPTER.validate_python(value)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        # Do not include Pydantic input values (possibly credentials) in diagnostics.
        raise ProtocolError("设备JSON-RPC响应字段无效") from exc


def event_to_wire(event: DeviceEvent, request_id: RpcId | MissingId = MISSING_ID) -> str | None:
    """重编码RPC/通知；job查询终态和SDK聚合结果不伪造设备RPC响应。"""
    if event.type == EventType.UNKNOWN:
        value = event.raw
    elif event.type in (EventType.JOB_FINISHED, EventType.STATE_CHANGED, EventType.DATA_AVAILABLE):
        args = event.model_dump(exclude={"type", "boot_id", "session"})
        value = {
            "jsonrpc": "2.0",
            "method": event.type,
            "params": {
                "context": {"boot_id": event.boot_id, "session": event.session},
                "args": args,
            },
        }
    elif (
        isinstance(event, ResponseEvent)
        and event.type
        in (
            EventType.HELLO_COMPLETED,
            EventType.STATE_COMPLETED,
            EventType.CAPABILITIES_COMPLETED,
            EventType.RESOURCE_GET_COMPLETED,
            EventType.DIAGNOSTICS_COMPLETED,
            EventType.COMMAND_COMPLETED,
            EventType.COMMAND_ACCEPTED,
            EventType.COMMAND_FAILED,
        )
        and not isinstance(request_id, MissingId)
    ):
        context = {"boot_id": event.boot_id, "session": event.session}
        value = {"jsonrpc": "2.0", "id": request_id}
        if event.type == EventType.COMMAND_FAILED:
            if event.error.source == "sdk":
                return None
            value["error"] = {
                "code": event.error.code,
                "message": event.error.message,
                "data": {**event.error.data, "reason": event.error.reason, "context": context},
            }
        else:
            result = (
                event.job.to_dict()
                if event.type == EventType.COMMAND_ACCEPTED
                else event.to_dict()["result"]
            )
            value["result"] = {"context": context, "value": result}
    elif event.type == EventType.RPC_ERROR:
        value = {
            "jsonrpc": "2.0",
            "id": event.wire_id,
            "error": {
                "code": event.error.code,
                "message": event.error.message,
                "data": event.error.data,
            },
        }
    else:
        return None
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"


class LineReader:
    """有界UTF8重组；坏帧丢弃至下一LF恢复。"""

    def __init__(self, max_length: int = 8192):
        self.buffer = bytearray()
        self.dropping = False
        self.max_length = max_length
        self.started: float | None = None

    def expire(self, now: float | None = None) -> list[ProtocolError]:
        if (
            self.started is not None
            and (time.monotonic() if now is None else now) - self.started >= 3
        ):
            self.buffer.clear()
            self.started = None
            self.dropping = True
            return [ProtocolError("设备残帧超过3秒，丢弃至下一LF")]
        return []

    def feed(self, data: bytes) -> list[str | ProtocolError]:
        lines: list[str | ProtocolError] = list(self.expire())
        for char in data:
            if char == 10:
                if self.buffer and not self.dropping:
                    try:
                        lines.append(self.buffer.decode("utf-8", errors="strict"))
                    except UnicodeError:
                        lines.append(ProtocolError("设备帧不是有效UTF8"))
                self.buffer.clear()
                self.dropping = False
                self.started = None
            elif not self.dropping:
                if not self.buffer:
                    self.started = time.monotonic()
                self.buffer.append(char)
                if len(self.buffer) > self.max_length:
                    self.buffer.clear()
                    self.dropping = True
                    self.started = None
                    lines.append(ProtocolError("设备帧超过8192字节"))
        return lines
