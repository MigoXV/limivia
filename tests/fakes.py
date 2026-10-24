"""测试侧v3设备：控制响应/断线/作业，不能作为真实硬件证据。"""

import asyncio
import base64
import copy
import json

HELLO = {
    "protocol": 3,
    "jsonrpc": "2.0",
    "contract": "limivia-v3-jsonrpc2",
    "batch_max": 8,
    "sequence_window": 64,
    "sequence_high": 0,
    "board": "luatos-esp32c3-usb",
    "device_id": "e4:b0:63:ca:b4:78",
    "firmware": "0.3.0-dev",
    "boot_id": "0123456789abcdef",
    "build_id": "a" * 64,
    "session": "session-test",
    "profile": "bus",
    "request_max": 1024,
    "response_max": 8192,
    "session_timeout_ms": 5000,
    "capability_pages": 28,
    "auth_mode": "open",
    "resources_max": 24,
    "job_history": 16,
    "buffer_max": 4096,
}
STATE = {
    "revision": 1,
    "epoch": 1,
    "page": 0,
    "pages": 6,
    "uptime_ms": 10,
    "stopping": False,
    "autostart_inhibited": True,
    "owner_endpoint": -1,
    "resources": [],
}


class FakeTransport:
    def __init__(self):
        self.closed = False
        self.commands = []
        self.frames = []
        self.nonce = None
        self.capture = None
        self.hello = copy.deepcopy(HELLO)
        self.jobs = {}
        self.resources = {}
        self.uart_data = {}
        self.next_id = 1
        self.control = None
        self.silent_op = None
        self.disconnect_op = None
        self.refuse = False
        self.reject_op = None
        self.reject_reason = "test_refusal"
        self.hold_jobs = False
        self.job_state = "completed"
        self.result_expired = False
        self.close_delay = 0
        self.write_delay = 0
        self.partial = False
        self.loops = []
        self.respond = True
        self.bad_response = None

    async def open(self):
        self.loops.append(asyncio.get_running_loop())
        self.queue = asyncio.Queue()

    async def emit(self, value):
        """测试用业务结果构造器；实际链路始终传输JSON-RPC。"""
        value = dict(value)
        context = {
            "boot_id": value.pop("boot_id", self.hello["boot_id"]),
            "session": value.pop("session", self.hello["session"]),
        }
        if "jsonrpc" in value:
            wire = value
        elif "event" in value:
            wire = {
                "jsonrpc": "2.0",
                "method": value.pop("event"),
                "params": {"context": context, "args": value},
            }
        elif value.get("ok", True):
            wire = {
                "jsonrpc": "2.0",
                "id": value["id"],
                "result": {"context": context, "value": value.get("result", {})},
            }
        else:
            error = value["error"]
            reason = error.get("reason", error.get("code", "test_refusal"))
            code = error["code"] if type(error.get("code")) is int else 1000
            wire = {
                "jsonrpc": "2.0",
                "id": value["id"],
                "error": {
                    "code": code,
                    "message": "Operation rejected",
                    "data": {"reason": reason, "context": context},
                },
            }
        if self.capture is not None:
            self.capture.append(wire)
            return
        await self.emit_wire(wire)

    async def emit_wire(self, wire):
        data = (json.dumps(wire) + "\n").encode()
        for offset in range(0, len(data), 7):
            await self.queue.put(data[offset : offset + 7])

    async def read(self):
        item = await self.queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def write(self, data):
        self.loops.append(asyncio.get_running_loop())
        if self.write_delay:
            await asyncio.sleep(self.write_delay)
        if self.partial:
            raise ConnectionError("partial write")
        frame = json.loads(data)
        self.frames.append(frame)
        if isinstance(frame, list):
            self.capture = []
            for command in sorted(frame, key=lambda c: c["method"] != "outputs.stop"):
                await self.handle(command)
            messages = list(reversed(self.capture))
            self.capture = None
            await self.emit_wire(messages)
        else:
            await self.handle(frame)

    async def handle(self, wire):
        assert wire["jsonrpc"] == "2.0" and "v" not in wire
        context, p = (
            wire["params"]
            if isinstance(wire["params"], list)
            else (wire["params"].get("context", {}), wire["params"].get("args", {}))
        )
        op = wire["method"]
        command = {"id": wire.get("id"), "op": op, "params": p, "context": context}
        self.commands.append(command)
        if op != "hello":
            assert type(context["seq"]) is int
            self.hello["sequence_high"] = max(self.hello["sequence_high"], context["seq"])
        if self.disconnect_op == op:
            await self.queue.put(ConnectionError("test disconnect"))
            return
        if op == self.silent_op or not self.respond:
            return
        if (self.refuse or op == self.reject_op) and op != "hello":
            await self.emit(
                {"id": command["id"], "ok": False, "error": {"code": self.reject_reason}}
            )
            return
        if op == "hello":
            nonce = context["client_nonce"]
            if self.nonce is not None and nonce != self.nonce:
                self.hello["session"] += "-new"
                self.hello["sequence_high"] = 0
                self.control = None
            self.nonce = nonce
            result = self.hello
        elif op == "control.acquire":
            self.control = "control-test"
            result = {"control": self.control}
        elif op == "control.release":
            self.control = None
            result = {}
        elif op == "state":
            result = {
                **STATE,
                "page": p.get("page", 0),
                "resources": list(self.resources.values())[
                    p.get("page", 0) * 4 : p.get("page", 0) * 4 + 4
                ],
                "owner_endpoint": 0 if self.control else -1,
            }
        elif op == "capabilities":
            result = {"page": p.get("page", 0), "pages": 28, "items": []}
        elif op == "diagnostics":
            result = {
                "rejected": 0,
                "stale_completions": 0,
                "lost_notifications": 0,
                "timing": "software_monotonic",
                "system": {},
            }
        elif op == "job.get":
            result = copy.deepcopy(self.jobs[p["job_id"]])
            if not self.hold_jobs:
                result["state"] = self.job_state
            result["result_expired"] = self.result_expired
            resource = self.resources.get(result["resource"])
            if resource and result["state"] != "accepted":
                if result["state"] == "completed" and result["action"] == "close":
                    self.resources.pop(result["resource"], None)
                elif result["action"] in ("open", "close"):
                    resource["state"] = "ready" if result["state"] == "completed" else "fault"
        elif op == "job.cancel":
            self.job_state = "cancelled"
            result = copy.deepcopy(self.jobs[p["job_id"]])
            result["cancel_requested"] = True
        elif op == "resource.get":
            if p["resource"] not in self.resources:
                await self.emit(
                    {"id": command["id"], "ok": False, "error": {"reason": "resource_not_found"}}
                )
                return
            result = self.resources[p["resource"]]
        elif (
            op.startswith(
                (
                    "resource.open",
                    "resource.call",
                    "resource.close",
                    "resource.recover",
                    "storage.",
                    "ota.",
                    "wifi.",
                    "mqtt.",
                    "espnow.",
                    "power.",
                    "system.",
                )
            )
            or op == "outputs.stop"
        ):
            resource = 0
            action = op
            if op == "resource.open":
                resource = self.next_id
                self.next_id += 1
                action = "open"
                self.resources[resource] = {
                    "id": resource,
                    "instance": resource,
                    "kind": p["kind"],
                    "state": "opening",
                    "pin_mask": sum(1 << v for v in p["pins"].values()),
                    "definition": p,
                    "parent": p.get("parent", 0),
                }
            elif op == "resource.call":
                resource = p["resource"]
                action = p["action"]
            elif op in ("resource.close", "resource.recover"):
                resource = p["resource"]
                if resource in self.resources:
                    self.resources[resource]["state"] = "closing"
                action = "close"
            elif op == "outputs.stop":
                self.control = None
                self.resources.clear()
            result = {
                "job_id": self.next_id,
                "resource": resource,
                "state": "accepted",
                "action": action,
                "driver_error": 0,
                "external_effect_possible": False,
                "result_expired": False,
                "cancel_requested": False,
            }
            self.next_id += 1
            self.jobs[result["job_id"]] = copy.deepcopy(result)
            if op == "resource.call" and resource in self.resources:
                info = self.resources[resource]
                config = info["definition"]["config"]
                reply = {}
                if info["kind"] == "gpio":
                    if action == "write":
                        config["level"] = p["args"]["level"]
                    elif action == "read":
                        reply = {"level": config.get("level", 0)}
                elif info["kind"] == "adc" and action == "read":
                    reply = {"raw": 1234, "millivolts": None}
                elif info["kind"] == "uart":
                    if action == "write":
                        self.uart_data[resource] = base64.b64decode(p["args"]["data"])
                        reply = {"written": len(self.uart_data[resource])}
                    elif action == "read":
                        data = self.uart_data.get(resource, b"")[: p["args"]["length"]]
                        reply = {"length": len(data), "data": base64.b64encode(data).decode()}
                if action == "events":
                    reply = {"events": []}
                self.jobs[result["job_id"]]["result"] = reply
            if op == "outputs.stop":
                self.jobs[result["job_id"]]["result"] = {
                    "cleanup_faults": 0,
                    "persist_error": 0,
                    "autostart_inhibited": True,
                }
        else:
            result = {}
        response = {"id": command["id"], "ok": True, "result": result}
        if self.bad_response:
            response = self.bad_response(response)
        await self.emit(response)

    async def close(self):
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        self.closed = True


class FakeBackend:
    def __init__(self, transport=None):
        self.connection = transport or FakeTransport()
        self.discovered = False

    async def discover(self, kind):
        self.discovered = True
        return [{"id": "test", "name": "LIMIVIA-test"}]

    def transport(self, kind, target, options=None):
        return self.connection


async def result(connection, request_id, *, accepted=False):
    async with asyncio.timeout(2):
        while True:
            event = await connection.recv()
            if getattr(event, "request_id", None) == request_id:
                if event.type == "command.accepted" and not accepted:
                    continue
                return event
