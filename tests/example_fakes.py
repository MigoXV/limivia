"""示例流程测试用传输；复用分片与队列，仅模拟这些示例涉及的资源状态。"""

import asyncio
import json
from copy import deepcopy

from .fakes import HELLO, SAMPLE, FakeBackend, FakeTransport


class ExampleTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.hello = deepcopy(HELLO)
        self.state = self.hello["state"]
        self.state["pins"] = [
            {"pin": pin, "mode": "idle", "pull": "none", "level": None} for pin in (0, 1, 3, 4, 13)
        ]
        self.sample = deepcopy(SAMPLE)
        self.failures = {}
        self.before_reply = {}
        self.after_reply = {}
        self.reply_delay = {}
        self.finish_timer_before = None
        self.started = asyncio.Event()
        self.stopping = asyncio.Event()

    async def write(self, data):
        command = json.loads(data)
        self.commands.append(command)
        op, params = command["op"], command["params"]
        if op == self.disconnect_op:
            await self.queue.put(ConnectionError("模拟设备断线"))
            return
        if op in self.failures:
            await self.emit({"v": 1, "id": command["id"], "ok": False, "error": self.failures[op]})
            return

        pin = next((p for p in self.state["pins"] if p["pin"] == params.get("pin")), None)
        if self.finish_timer_before == op or (
            self.finish_timer_before == "cleanup" and op in ("timer.stop", "pin.release")
        ):
            for timer in self.state["timers"]:
                timer_pin = next(p for p in self.state["pins"] if p["pin"] == timer["pin"])
                timer_pin.update(mode="output", level=0)
            self.state["timers"] = []
        # BLE 实机发现：自然结束后的 output 不接受 timer.stop，必须 pin.release。
        if op == "timer.stop" and pin["mode"] == "output":
            await self.emit(
                {
                    "v": 1,
                    "id": command["id"],
                    "ok": False,
                    "error": {
                        "code": "pin_busy",
                        "message": "Release the pin before changing its function",
                    },
                }
            )
            return
        result = self.state
        if op == "hello":
            result = self.hello
        elif op == "gpio.set":
            pin.update(mode=params["mode"], pull=params["pull"], level=params["level"])
        elif op == "gpio.read":
            result = {"pin": pin["pin"], "level": pin["level"] or 0}
        elif op == "pwm.set":
            pin.update(mode="pwm", level=None)
            self.state["pwm"] = [{**params, "resolution": 10}]
        elif op == "timer.start":
            pin.update(mode="timer", level=1)
            self.state["timers"] = [{**params, "id": 1, "elapsed_ms": 0}]
        elif op in ("adc.read", "adc.start"):
            pin.update(mode="adc", level=None)
            result = {**self.sample, "pin": params["pin"]}
            if op == "adc.start":
                self.state["streams"] = [params.copy()]
                self.started.set()
        elif op in ("pin.release", "pwm.stop", "timer.stop", "adc.stop", "outputs.stop"):
            self.stopping.set()
            for item in self.state["pins"]:
                if op == "outputs.stop" or item is pin:
                    item.update(mode="idle", pull="none", level=None)
            for name in ("pwm", "timers", "streams"):
                self.state[name] = [
                    item
                    for item in self.state[name]
                    if op != "outputs.stop" and item["pin"] != params["pin"]
                ]

        # silent_op 可模拟设备已执行、但应答丢失的情况。
        if op == self.silent_op:
            return
        for notification in self.before_reply.get(op, []):
            await self.emit(notification)
        await asyncio.sleep(self.reply_delay.get(op, 0))
        await self.emit({"v": 1, "id": command["id"], "ok": True, "result": result})
        for notification in self.after_reply.get(op, []):
            await self.emit(notification)


class ExampleBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.devices = [{"id": "test", "name": "模拟示例设备"}]
        self.scans = []

    async def discover(self, kind):
        self.scans.append(kind)
        return self.devices

    def transport(self, kind, target):
        assert self.scans and target in {device["id"] for device in self.devices}
        transport = ExampleTransport()
        self.configure(transport)
        self.transports.append(transport)
        return transport
