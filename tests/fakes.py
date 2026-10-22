import asyncio
import json

STATE = {
    "revision": 1,
    "uptime_ms": 10,
    "ble_connected": True,
    "usb_active": False,
    "pins": [{"pin": 13, "mode": "idle", "pull": "none", "level": None}],
    "pwm": [],
    "timers": [],
    "streams": [],
}
SAMPLE = {"pin": 0, "raw": 1234, "calibrated": True, "millivolts": 900, "uptime_ms": 10}
HELLO = {
    "name": "设备",
    "board": "luatos-esp32c3-usb",
    "firmware": "0.1.0",
    "device_id": "test",
    "protocol": 1,
    "state": STATE,
    "capabilities": {
        "features": ["gpio", "pwm", "adc", "timer"],
        "max_pwm": 4,
        "max_timers": 4,
        "status_led": 12,
        "demo_led": 13,
        "adc_max_mv": 2500,
        "adc_calibrated": True,
    },
}


class FakeTransport:
    def __init__(self):
        self.closed = False
        self.commands = []
        self.respond = True
        self.refuse = False
        self.silent_op = None
        self.disconnect_op = None
        self.hello = HELLO.copy()
        self.close_delay = 0
        self.loops = []

    async def open(self):
        self.loops.append(asyncio.get_running_loop())
        self.queue = asyncio.Queue()

    async def emit(self, value):
        data = (json.dumps(value, ensure_ascii=False) + "\n").encode()
        for n in range(0, len(data), 7):
            await self.queue.put(data[n : n + 7])

    async def read(self):
        item = await self.queue.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def write(self, data):
        self.loops.append(asyncio.get_running_loop())
        command = json.loads(data)
        self.commands.append(command)
        op = command["op"]
        if op == self.disconnect_op:
            await self.queue.put(ConnectionError("模拟设备断线"))
            return
        if op == "hello":
            result = self.hello
        elif not self.respond or op == self.silent_op:
            return
        elif self.refuse:
            await self.emit(
                {
                    "v": 1,
                    "id": command["id"],
                    "ok": False,
                    "error": {"code": "pin_busy", "message": "引脚已占用"},
                }
            )
            return
        elif op in ("adc.read", "adc.start"):
            result = SAMPLE
        elif op == "gpio.read":
            result = {"pin": command["params"]["pin"], "level": 1}
        else:
            result = STATE
        await self.emit({"v": 1, "id": command["id"], "ok": True, "result": result})

    async def close(self):
        await asyncio.sleep(self.close_delay)
        self.loops.append(asyncio.get_running_loop())
        self.closed = True


class FakeBackend:
    def __init__(self):
        self.transports = []
        self.configure = lambda transport: None
        self.loops = []

    async def discover(self, kind):
        self.loops.append(asyncio.get_running_loop())
        return [{"id": "test", "name": f"{kind} 设备"}]

    def transport(self, kind, target):
        if target != "test":
            raise ValueError("请重新搜索设备")
        transport = FakeTransport()
        self.configure(transport)
        self.transports.append(transport)
        return transport
