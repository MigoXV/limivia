"""用已安装wheel验收指定设备；OTA仅调用独立固件工具，始终finally恢复bus。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import limivia
from limivia import AsyncLimivia
from limivia.transports import DeviceBackend

PORT = "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_E4:B0:63:CA:B4:78-if00"
MAC = "e4:b0:63:ca:b4:78"
EXCLUDED = {10, 12}


def public(value):
    if isinstance(value, dict):
        return {
            k: (
                "sha256:" + hashlib.sha256(str(v).encode()).hexdigest()[:12]
                if k in {"session", "control", "client_nonce", "password", "key", "pmk"}
                else public(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [public(v) for v in value]
    return value


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        os.chmod(path, 0o600)
        json.dump(public(value), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class RecordingTransport:
    def __init__(self, transport, transcript):
        self.transport, self.transcript = transport, transcript
        self.partial = bytearray()

    async def open(self):
        await self.transport.open()

    async def read(self):
        data = await self.transport.read()
        self.partial.extend(data)
        while b"\n" in self.partial:
            line, _, tail = self.partial.partition(b"\n")
            self.partial = bytearray(tail)
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                value = {"invalid_frame_hex": line.hex()}
            self.transcript.append({"received": public(value), "monotonic": time.monotonic()})
        return data

    async def write(self, data):
        frame = json.loads(data)
        for item in frame if isinstance(frame, list) else [frame]:
            args = item.get("params", {}).get("args", {})
            assert not EXCLUDED.intersection(args.get("pins", {}).values()), "excluded GPIO"
        self.transcript.append({"sent": public(frame), "monotonic": time.monotonic()})
        await self.transport.write(data)

    async def close(self):
        await self.transport.close()


class Backend(DeviceBackend):
    def __init__(self, transcript):
        super().__init__()
        self.transcript = transcript

    def transport(self, kind, target, options=None):
        return RecordingTransport(super().transport(kind, target, options), self.transcript)


class Failed(RuntimeError):
    def __init__(self, event):
        self.event = event
        super().__init__(
            event.type + ":" + (event.error.reason if hasattr(event, "error") else "unknown")
        )


class Harness:
    def __init__(self, args, manifest, report, profile=None):
        self.args, self.manifest, self.report, self.profile = args, manifest, report, profile
        self.client = self.manager = self.connection = None
        self.backlog: dict[int, list] = {}
        self.buffers: set[int] = set()
        self.uploads = {"storage": set(), "ota": set()}
        self.last_boot = None
        self.report.setdefault("transcript", [])
        self.report.setdefault("events", [])
        self.report.setdefault("checks", [])
        self.report.setdefault("observations", {})
        self.prefix = args.prefix

    async def open(self):
        assert (
            Path(self.args.port).resolve() == Path(PORT).resolve()
            and self.args.expected_device == MAC
        )
        self.client = AsyncLimivia(
            backend=Backend(self.report["transcript"]),
            timeout=6,
            job_timeout=45,
            job_poll_interval=0.02,
            event_queue_size=2048,
        )
        await self.client.devices.list(kind="usb")
        self.manager = self.client.devices.connect(
            kind="usb", target=self.args.port, expected_device_id=self.args.expected_device
        )
        self.connection = (await self.manager.__aenter__()).raw
        identity = self.connection.identity
        assert identity.device_id == MAC and identity.contract == "limivia-v3-jsonrpc2"
        assert identity.board == "luatos-esp32c3-usb" and identity.jsonrpc == "2.0"
        expected = self.manifest["images"][identity.profile]
        assert identity.build_id == expected["build_id"]
        if self.profile:
            assert identity.profile == self.profile
        if self.last_boot is not None and identity.boot_id != self.last_boot:
            self.buffers.clear()
            for uploads in self.uploads.values():
                uploads.clear()
        self.last_boot = identity.boot_id
        self.report.setdefault("identities", []).append(identity.to_dict())
        return identity

    async def close(self):
        if self.manager:
            try:
                await self.manager.__aexit__(None, None, None)
            finally:
                self.manager = None
        if self.client:
            await self.client.close()
            self.client = None
        self.connection = None
        self.backlog.clear()

    async def reconnect(self, old_boot, *, changed):
        await self.close()
        deadline = time.monotonic() + 20
        attempts = self.report.setdefault("reconnect_attempts", [])
        while time.monotonic() < deadline:
            await asyncio.sleep(0.3)
            try:
                identity = await self.open()
                assert (identity.boot_id != old_boot) == changed
                attempts.append({"status": "ready", "boot_id": identity.boot_id})
                return identity
            except (OSError, TimeoutError, ConnectionError) as exc:
                attempts.append({"status": "not_ready", "error": type(exc).__name__})
                await self.close()
        raise TimeoutError("explicit link recovery failed; no write replay")

    async def wait(self, rid, *, accepted=False):
        async with asyncio.timeout(50):
            while True:
                queued = self.backlog.get(rid, [])
                event = queued.pop(0) if queued else await self.connection.recv()
                if not queued:
                    self.backlog.pop(rid, None)
                self.report["events"].append(public(event.to_dict()))
                request_id = getattr(event, "request_id", None)
                if request_id != rid:
                    if request_id is not None:
                        self.backlog.setdefault(request_id, []).append(event)
                    if event.type == "connection.closed":
                        raise Failed(event)
                    continue
                if event.type == "command.accepted" and not accepted:
                    continue
                return event

    async def rpc(self, method, params=None, *, accepted=False, failure=False):
        rid = await self.connection.send({"type": method, "params": params or {}})
        event = await self.wait(rid, accepted=accepted)
        if failure:
            assert event.type in {"command.failed", "job.failed"}, event.type
            return event
        if event.type in {"command.failed", "job.failed", "job.cancelled"}:
            raise Failed(event)
        if event.type in {"command.accepted", "job.completed"}:
            if accepted:
                return event.job
            value = event.job.result or {}
        else:
            value = event.result
        family, _, action = method.partition(".")
        if family in self.uploads:
            if action == "begin":
                self.uploads[family].add(value["upload_id"])
            elif action in {"commit", "abort"}:
                self.uploads[family].discard(params["upload_id"])
        return value

    async def opened(self, kind, pins, config=None, **extra):
        assert not EXCLUDED.intersection(pins.values())
        rid = await self.connection.resource.open(
            kind=kind, pins=pins, config=config or {}, **extra
        )
        event = await self.wait(rid)
        if event.type != "job.completed":
            raise Failed(event)
        assert event.job.resource > 0
        return event.job.resource

    async def call(self, resource, action, args=None):
        return await self.rpc(
            "resource.call", {"resource": resource, "action": action, "args": args or {}}
        )

    async def closed(self, resource):
        await self.rpc("resource.close", {"resource": resource})

    async def upload(self, name, data):
        started = await self.rpc(
            "storage.begin",
            {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        )
        for offset in range(0, len(data), 384):
            await self.rpc(
                "storage.chunk",
                {
                    "upload_id": started["upload_id"],
                    "offset": offset,
                    "data": data[offset : offset + 384],
                },
            )
        await self.rpc("storage.commit", {"upload_id": started["upload_id"]})

    async def snapshot(self):
        event = await self.wait(await self.connection.state.snapshot())
        assert event.type == "state.snapshot.completed", event.type
        return event.result

    async def files(self):
        files, page = [], 0
        while True:
            value = await self.rpc("storage.list", {"page": page})
            files.extend(value["files"])
            if not value["more"]:
                return files
            page += 1
            assert page < 256, "bounded storage enumeration"

    def passed(self, name, observation=None):
        self.report["checks"].append(name)
        if observation is not None:
            self.report["observations"][name] = public(observation)
        print(f"{self.profile or 'final'}: {name}", flush=True)

    async def cleanup(self):
        if self.connection is None or self.connection.identity is None:
            await self.close()
            await self.open()
        await self.rpc("outputs.stop")
        await self.rpc("control.acquire")
        for family, uploads in self.uploads.items():
            for upload_id in list(uploads):
                await self.rpc(family + ".abort", {"upload_id": upload_id})
        flows = await self.rpc("flow.list")
        for flow in flows["flows"]:
            if flow["name"].startswith(self.prefix):
                await self.rpc("flow.remove", {"flow_id": flow["flow_id"]})
        for item in await self.files():
            if item["name"].startswith(self.prefix):
                await self.rpc("storage.delete", {"name": item["name"]})
        for buffer in list(self.buffers):
            event = await self.wait(await self.connection.buffer.delete(buffer_id=buffer))
            if event.type == "command.failed":
                assert event.error.reason in {"buffer_not_found"}, event.error.reason
            self.buffers.discard(buffer)
        # No buffer enumeration exists; the contract's four slots are centrally checked here.
        probes = []
        try:
            for _ in range(4):
                created = await self.rpc("buffer.create", {"size": 1})
                probes.append(created["buffer_id"])
        finally:
            for buffer in probes:
                await self.rpc("buffer.delete", {"buffer_id": buffer})
        assert not [
            f for f in (await self.rpc("flow.list"))["flows"] if f["name"].startswith(self.prefix)
        ]
        assert not [f for f in await self.files() if f["name"].startswith(self.prefix)]
        # Last mutation is an explicitly confirmed stop; it also revokes cleanup control.
        stopped = await self.rpc("outputs.stop")
        state = await self.snapshot()
        assert not state.resources
        assert all(
            p.owner_endpoint == -1 and p.autostart_inhibited and not p.stopping for p in state.pages
        )
        diagnostics = await self.rpc("diagnostics")
        system = diagnostics.system
        self.report["cleanup"] = {
            "status": "confirmed",
            "stop_result": stopped,
            "state": state.to_dict(),
            "diagnostics": diagnostics.to_dict(),
            "buffer_slots_probed_and_deleted": len(probes),
        }
        assert not system.get("inhibit_pending", False), system
        for key in ("nvs_error", "filesystem_error", "checkpoint_error"):
            assert not system.get(key, 0), (key, system)


async def common(h):
    c = h.connection
    before = await h.snapshot()
    event = await h.wait(await c.discover())
    assert event.type == "discovery.completed"
    discovery = event.result
    assert len(discovery.raw_pages) == discovery.raw_pages[0].pages
    assert all(p.digital and p.adc1 for p in discovery.pins if p.pin in (0, 1, 3, 4))
    after = await h.snapshot()
    assert before.revision == after.revision
    assert before.pages[0].owner_endpoint == after.pages[0].owner_endpoint
    h.report["discovery"] = discovery.to_dict()
    h.passed("identity_complete_discovery_without_control")
    await h.rpc("outputs.stop")
    await h.rpc("control.acquire")
    h.report["initial_files"] = await h.files()
    unavailable = next(r.kind for r in discovery.resources if not r.available)
    pins = {"tx": 20, "rx": 21} if unavailable == "uart" else {"ch0": 0}
    rejected = await h.rpc(
        "resource.preflight", {"kind": unavailable, "pins": pins, "config": {}}, failure=True
    )
    assert rejected.error.reason == "feature_unavailable"
    await h.rpc(
        "event.subscribe", {"topics": ["job", "resource", "flow", "data"], "interval_ms": 10}
    )
    gpio = await h.opened("gpio", {"pin": 13}, {"mode": "output", "level": 0, "edge": "any"})
    conflict = await h.rpc(
        "resource.preflight", {"kind": "gpio", "pins": {"pin": 13}, "config": {}}, failure=True
    )
    assert conflict.error.reason == "pin_conflict"
    await h.call(gpio, "write", {"level": 1})
    assert (await h.call(gpio, "read"))["level"] == 1
    await h.rpc("gpio.group.write", {"resources": [{"resource": gpio, "level": 0}]})
    await h.rpc("gpio.group.read", {"resources": [{"resource": gpio}]})
    await h.closed(gpio)
    for pin in (0, 1, 3, 4):
        adc = await h.opened("adc", {"pin": pin}, {"interval_ms": 10})
        await asyncio.sleep(0.06)
        await h.call(adc, "read")
        conflict = await h.rpc(
            "mux.preflight", {"kind": "gpio", "pins": {"pin": pin}, "config": {}}, failure=True
        )
        assert conflict.error.reason == "pin_conflict"
        await h.closed(adc)
        digital = await h.opened("gpio", {"pin": pin}, {"mode": "input"})
        await h.call(digital, "read")
        await h.closed(digital)
    h.passed("gpio_internal_readback_adc_digital_reuse_and_conflicts")
    channels = [
        await h.opened("pwm", {"pin": pin}, {"frequency": 1000, "resolution": 10, "duty": 10})
        for pin in (0, 1, 3, 4, 5, 6)
    ]
    state = await h.snapshot()
    assert len({r.channel for r in state.resources}) == 6
    assert len({r.timer for r in state.resources}) == 1
    for resource in channels:
        await h.closed(resource)
    timer = await h.opened(
        "timer", {"pin": 13}, {"high_ms": 20, "low_ms": 20, "count": 2, "end_level": 0}
    )
    await asyncio.sleep(0.12)
    await h.call(timer, "status")
    await h.closed(timer)
    temperature = await h.opened("temperature", {})
    await h.call(temperature, "read")
    await h.closed(temperature)
    h.passed("pwm_shared_timer_local_timer_temperature_driver_lifecycle")
    data = bytes(range(256)) * 4
    buffer = (await h.rpc("buffer.create", {"size": len(data)}))["buffer_id"]
    h.buffers.add(buffer)
    for offset in range(0, len(data), 384):
        await h.rpc(
            "buffer.write",
            {"buffer_id": buffer, "offset": offset, "data": data[offset : offset + 384]},
        )
    read = await h.rpc("buffer.read", {"buffer_id": buffer, "offset": 0, "length": len(data)})
    assert base64.b64decode(read["data"]) == data
    await h.rpc("buffer.delete", {"buffer_id": buffer})
    h.buffers.remove(buffer)
    name = h.prefix + ".bin"
    await h.upload(name, data)
    read = await h.rpc("storage.read", {"name": name, "offset": 0, "length": len(data)})
    assert base64.b64decode(read["data"]) == data
    await h.rpc("storage.delete", {"name": name})
    h.passed("buffer_and_atomic_file_binary_integrity")
    ids = await c.batch(
        [
            {"type": "state", "params": {"page": 0}},
            {"type": "diagnostics", "params": {}},
            {"type": "system.time", "params": {}},
        ]
    )
    for rid, expected in zip(
        ids, ("state.completed", "diagnostics.completed", "job.completed"), strict=True
    ):
        assert (await h.wait(rid)).type == expected
    await h.rpc("session.ping")
    assert any(e["type"] == "data.available" for e in h.report["events"])
    h.passed("batch_per_request_jobs_and_real_device_notifications")
    await h.rpc("event.unsubscribe")
    ids = await c.batch(
        [
            {"type": "control.acquire", "params": {}},
            {"type": "outputs.stop", "params": {}},
            {"type": "buffer.create", "params": {"size": 1}},
            {"type": "state", "params": {"page": 0}},
        ]
    )
    for index in (0, 2):
        event = await h.wait(ids[index])
        assert event.type == "command.failed" and event.error.reason == "stop_in_progress"
    assert (await h.wait(ids[1])).type == "job.completed"
    assert (await h.wait(ids[3])).type == "state.completed"
    assert all(p.owner_endpoint == -1 for p in (await h.snapshot()).pages)
    h.passed("batch_stop_barrier_and_original_stop_job")
    await h.rpc("control.acquire")
    # Observe capability-driven selection while retaining all profile interfaces.
    available = {r.kind for r in discovery.resources if r.available}
    if "uart" in available:
        uart = await h.opened("uart", {"tx": 20, "rx": 21}, {"baud": 115200, "loopback": True})
        payload = b"SDK\x00\xff\x01"
        await h.call(uart, "write", {"data": payload})
        await h.call(uart, "drain")
        read = await h.call(uart, "read", {"length": len(payload)})
        assert base64.b64decode(read["data"]) == payload
        read_id = await c.resource.call(
            resource=uart, action="read", args={"length": 1, "timeout_ms": 1000}
        )
        accepted = await h.wait(read_id, accepted=True)
        assert accepted.type == "command.accepted"
        await h.rpc("job.cancel", {"job_id": accepted.job.job_id})
        assert (await h.wait(read_id)).type == "job.cancelled"
        await h.closed(uart)
        h.passed("uart_internal_loopback")
    if "i2c.master" in available:
        bus = await h.opened("i2c.master", {"sda": 0, "scl": 1}, {"pullup": True})
        device = await h.opened("i2c.device", {}, {"address": 80, "frequency": 100000}, parent=bus)
        nack = await h.rpc(
            "resource.call",
            {"resource": device, "action": "read", "args": {"length": 1, "timeout_ms": 20}},
            failure=True,
        )
        assert nack.type == "job.failed" and nack.job.driver_error and nack.error.reason == "nack"
        await h.call(bus, "recover")
        await h.closed(device)
        await h.closed(bus)
        h.passed("i2c_master_child_and_real_nack")
    if "spi.master" in available:
        bus = await h.opened("spi.master", {"sclk": 6, "mosi": 7, "miso": 5})
        device = await h.opened("spi.device", {"cs": 13}, parent=bus)
        transfer = await h.call(device, "transfer", {"data": b"\x01\x02\x03\x04", "rx_length": 4})
        assert transfer["length"] == 4
        await h.closed(device)
        await h.closed(bus)
        h.passed("spi_master_driver_transaction_without_external_slave")
    if "i2c.slave" in available:
        slave = await h.opened("i2c.slave", {"sda": 0, "scl": 1}, {"address": 42, "pullup": True})
        assert (await h.call(slave, "preload", {"data": b"1234"}))["written"] == 4
        await h.call(slave, "clear_tx")
        await h.closed(slave)
        slave = await h.opened("spi.slave", {"sclk": 6, "mosi": 7, "miso": 5, "cs": 13, "ready": 4})
        await h.call(slave, "queue", {"data": b"1234", "rx_length": 4})
        await h.closed(slave)
        h.passed("i2c_spi_slave_driver_preload_and_pending_close")
    if "twai" in available:
        can = await h.opened("twai", {"tx": 4, "rx": 5}, {"mode": "self_test"})
        await h.call(can, "info")
        await h.closed(can)
        h.passed("twai_controller_lifecycle_without_transceiver")
    first, second = await h.opened("rmt.tx", {"pin": 13}), await h.opened("rmt.tx", {"pin": 6})
    symbol = struct.pack("<I", 1000 | (1 << 15) | (1000 << 16))
    await h.rpc(
        "rmt.sync",
        {
            "resources": [
                {"resource": first, "data": base64.b64encode(symbol).decode()},
                {"resource": second, "data": base64.b64encode(symbol).decode()},
            ]
        },
    )
    await h.call(first, "transmit", {"data": symbol, "loops": -1})
    await h.closed(first)
    await h.closed(second)
    rx = await h.opened("rmt.rx", {"pin": 0})
    await h.call(rx, "capture", {"max_ns": 1000000})
    await h.call(rx, "abort")
    await h.closed(rx)
    h.passed("rmt_sync_tx_abort_rx_lifecycle_without_measurement")
    if "adc.continuous" in available:
        adc = await h.opened("adc.continuous", {"ch0": 0, "ch1": 1}, {"sample_rate": 10000})
        await h.call(adc, "start")
        await asyncio.sleep(0.15)
        await h.call(adc, "stop")
        await h.call(adc, "read")
        events = await h.call(adc, "events")
        words = [
            x[0]
            for e in events["events"]
            for x in struct.iter_unpack("<I", base64.b64decode(e["data"]))
        ]
        assert words and {((w >> 13) & 7) for w in words} == {0, 1}
        assert all(not (w & (1 << 16)) for w in words)
        await h.closed(adc)
        for mode in ("standard", "tdm", "pdm"):
            pins = {"bclk": 4, "dout": 6}
            if mode != "pdm":
                pins["ws"] = 5
            i2s = await h.opened(
                "i2s", pins, {"mode": mode, "direction": "tx", "sample_rate": 16000}
            )
            await h.call(i2s, "play", {"data": bytes(256)})
            await h.call(i2s, "stop")
            await h.closed(i2s)
        sigma = await h.opened("sigma_delta", {"pin": 13})
        await h.call(sigma, "density", {"density": 32})
        await h.closed(sigma)
        h.passed("signal_adc_type2_i2s_std_tdm_pdm_and_sigma_delta")
    await flow_test(h)
    await ota_abort_test(h)


async def flow_test(h):
    name = h.prefix + ".manual.flow.json"
    definition = {
        "version": 1,
        "profile": h.profile,
        "resources": [],
        "variables": {"x": 0},
        "steps": [
            {"op": "set", "variable": "x", "value": 1},
            {"op": "delay", "ms": 200},
            {"op": "add", "variable": "x", "value": 1},
            {"op": "end"},
        ],
    }
    await h.upload(name, json.dumps(definition, separators=(",", ":")).encode())
    flow_id = (await h.rpc("flow.load", {"name": name}))["flow_id"]
    await h.rpc("flow.start", {"flow_id": flow_id})
    await h.rpc("flow.pause", {"flow_id": flow_id})
    await h.rpc("flow.resume", {"flow_id": flow_id})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = await h.rpc("flow.get", {"flow_id": flow_id})
        if state["state"] == "completed":
            break
        await asyncio.sleep(0.03)
    assert state["state"] == "completed" and state["variables"]["x"] == 2
    await h.rpc("flow.stop", {"flow_id": flow_id})
    await h.rpc("flow.remove", {"flow_id": flow_id})
    await h.rpc("storage.delete", {"name": name})
    h.passed("manual_flow_load_start_pause_resume_complete_remove")


async def ota_abort_test(h):
    await h.rpc("outputs.stop")
    await h.rpc("control.acquire")
    await h.rpc("ota.status")
    manifest = h.manifest["images"][h.profile]
    started = await h.rpc(
        "ota.begin", {k: manifest[k] for k in ("board", "protocol", "profile", "size", "sha256")}
    )
    image = Path(h.args.firmware_root) / h.profile / f"limivia-{h.profile}-v3rpc.bin"
    await h.rpc(
        "ota.chunk",
        {"upload_id": started["upload_id"], "offset": 0, "data": image.read_bytes()[:384]},
    )
    await h.rpc("ota.abort", {"upload_id": started["upload_id"]})
    h.passed("sdk_ota_status_begin_chunk_abort_without_activation")


async def iot(h):
    await h.rpc("power.configure", {"auto_light_sleep": False, "modem_sleep": "none"})
    await h.rpc("wifi.status")
    scan = await h.rpc("wifi.scan")
    h.report["observations"]["wifi_scan_count"] = len(scan["networks"])
    await h.rpc("espnow.start")
    await h.rpc("espnow.status")
    await h.rpc("espnow.peer", {"mac": "ff:ff:ff:ff:ff:ff", "encrypt": False})
    await h.rpc("espnow.remove", {"mac": "ff:ff:ff:ff:ff:ff"})
    await h.rpc("espnow.stop")
    await h.rpc("wifi.maintenance", {"enable": True})
    assert (await h.rpc("wifi.status"))["maintenance_ap"]
    await h.rpc("wifi.maintenance", {"enable": False})
    for protocol in ("3.1.1", "5.0"):
        await h.rpc(
            "mqtt.configure",
            {"uri": "mqtt://127.0.0.1:1883", "protocol": protocol, "persist": False},
        )
        status = await h.rpc("mqtt.status")
        assert status["configured"] and not status["connected"]
        await h.rpc("mqtt.stop")
    h.passed("iot_network_driver_lifecycle_no_broker_or_peer_interop")
    # Capture the original job before closing a USB link that may be interrupted by sleep.
    before = h.connection.identity.boot_id
    accepted = await h.rpc("power.sleep", {"mode": "light", "duration_ms": 200}, accepted=True)
    assert accepted.state == "accepted"
    h.report["observations"]["light_sleep_original_job_id"] = accepted.job_id
    await h.close()
    await asyncio.sleep(0.7)
    identity = await h.reconnect(before, changed=False)
    slept = await h.rpc("job.get", {"job_id": accepted.job_id})
    assert slept["state"] == "completed" and identity.boot_id == before
    h.passed("light_sleep_explicit_reconnect_original_job_query", slept)
    await h.rpc("control.acquire")
    log_name, flow_name = h.prefix + ".sleep.jsonl", h.prefix + ".sleep.flow.json"
    definition = {
        "version": 1,
        "profile": "iot",
        "resources": [],
        "variables": {"x": 0},
        "steps": [
            {"op": "set", "variable": "x", "value": 7},
            {
                "op": "service",
                "action": "storage.append",
                "timeout_ms": 1000,
                "args": {
                    "name": log_name,
                    "value": {"phase": "before", "x": {"$var": "x"}},
                    "limit_bytes": 4096,
                },
            },
            {"op": "sleep", "duration_ms": 1000},
            {"op": "add", "variable": "x", "value": 1},
            {
                "op": "service",
                "action": "storage.append",
                "timeout_ms": 1000,
                "args": {
                    "name": log_name,
                    "value": {"phase": "after", "x": {"$var": "x"}},
                    "limit_bytes": 4096,
                },
            },
            {"op": "end"},
        ],
    }
    await h.upload(flow_name, json.dumps(definition, separators=(",", ":")).encode())
    loaded = await h.rpc("flow.load", {"name": flow_name})
    before = h.connection.identity.boot_id
    await h.rpc("flow.start", {"flow_id": loaded["flow_id"]})
    await h.close()
    await asyncio.sleep(1.7)
    await h.reconnect(before, changed=True)
    await h.rpc("control.acquire")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        data = await h.rpc("storage.read", {"name": log_name, "offset": 0, "length": 4096})
        records = [json.loads(row) for row in base64.b64decode(data["data"]).splitlines()]
        if len(records) == 2:
            break
        await asyncio.sleep(0.1)
    assert records == [{"phase": "before", "x": 7}, {"phase": "after", "x": 8}]
    h.passed("iot_planned_deep_sleep_checkpoint_resume", records)
    # The global cleanup removes the resumed flow and both files, then persists inhibition.


async def run_profile(args, manifest, profile):
    report: dict[str, Any] = {"profile": profile, "cleanup": {"status": "not_attempted"}}
    h = Harness(args, manifest, report, profile)
    try:
        await h.open()
        await common(h)
        if profile == "iot":
            await iot(h)
        report["status"] = "passed"
    except BaseException as exc:  # noqa: BLE001 -- preserve original failure and cleanup
        report["status"] = "failed"
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        try:
            await h.cleanup()
        except BaseException as exc:  # noqa: BLE001 -- cleanup is independently reported
            report["cleanup"] = {"status": "unknown", "error": type(exc).__name__ + ": " + str(exc)}
        try:
            await h.close()
        except BaseException as exc:  # noqa: BLE001
            report["close_error"] = type(exc).__name__ + ": " + str(exc)
        save(args.output / f"{profile}-sdk.json", report)
    return report


async def probe(args, manifest, report):
    h = Harness(args, manifest, report)
    try:
        return (await h.open()).to_dict()
    finally:
        await h.close()


async def final_cleanup(args, manifest):
    report = {"profile": "bus", "cleanup": {"status": "not_attempted"}}
    h = Harness(args, manifest, report, "bus")
    try:
        await h.open()
        await h.cleanup()
        # Explicit reboot checks that global inhibition survives NVS reload.
        before = h.connection.identity.boot_id
        await h.rpc("control.acquire")
        accepted = await h.rpc("system.restart", accepted=True)
        report["restart_original_job_id"] = accepted.job_id
        await h.close()
        await asyncio.sleep(2)
        await h.reconnect(before, changed=True)
        state = await h.snapshot()
        assert state.pages[0].autostart_inhibited and state.pages[0].owner_endpoint == -1
        await h.cleanup()
        report["status"] = "confirmed"
        report["final_identity"] = h.connection.identity.to_dict()
    except BaseException as exc:  # noqa: BLE001 -- never claim restoration without confirmation
        report["status"] = "unknown"
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        await h.close()
        save(args.output / "final-bus-sdk.json", report)
    return report


def validate_images(args):
    root = Path(args.firmware_root)
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["contract"] == "limivia-v3-jsonrpc2"
    for profile, expected in manifest["images"].items():
        image = root / profile / f"limivia-{profile}-v3rpc.bin"
        data = image.read_bytes()
        assert len(data) == expected["size"]
        assert hashlib.sha256(data).hexdigest() == expected["sha256"]
        assert data[176:208].hex() == expected["build_id"]
        elf = root / profile / f"limivia-{profile}-v3rpc.elf"
        assert hashlib.sha256(elf.read_bytes()).hexdigest() == expected["build_id"]
    return manifest


def ota(args, profile, label):
    image = Path(args.firmware_root) / profile / f"limivia-{profile}-v3rpc.bin"
    environment = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "VIRTUAL_ENV",
            "POETRY_ACTIVE",
            "PYTHONHOME",
            "PYTHONPATH",
        }
    }
    command = [
        "poetry",
        "run",
        "limivia-esp32",
        "ota",
        "--port",
        args.port,
        "--expected-device",
        args.expected_device,
        "--image",
        str(image),
        "--output",
        str(args.output / f"{label}-ota-{profile}.json"),
    ]
    print(f"OTA {label} -> {profile}", flush=True)
    with (args.output / f"{label}-ota-{profile}.log").open("x") as log:
        result = subprocess.run(
            command,
            cwd=args.firmware_repo,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=1200,
            check=False,
        )
    assert result.returncode == 0, f"OTA failed: {label}/{profile}, see original log"


def execute(args, manifest, report):
    try:
        for profile in getattr(args, "profiles", ("bus", "signal", "iot")):
            preflight = {}
            identity = asyncio.run(probe(args, manifest, preflight))
            save(args.output / f"{profile}-before.json", preflight)
            if (
                identity["profile"] != profile
                or identity["build_id"] != manifest["images"][profile]["build_id"]
            ):
                ota(args, profile, "switch")
            result = asyncio.run(run_profile(args, manifest, profile))
            report["profiles"].append(
                {k: v for k, v in result.items() if k not in {"transcript", "events", "discovery"}}
            )
            if result["cleanup"]["status"] != "confirmed":
                raise RuntimeError("profile cleanup unknown; aborting remaining tests")
    except BaseException as exc:  # noqa: BLE001 -- global finally must restore bus
        report["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        try:
            preflight = {}
            identity = None
            try:
                identity = asyncio.run(probe(args, manifest, preflight))
            except BaseException as probe_error:  # noqa: BLE001 -- firmware OTA independently checks MAC
                preflight["error"] = type(probe_error).__name__ + ": " + str(probe_error)
            save(args.output / "restore-before.json", preflight)
            if identity is None or (
                identity["profile"] != "bus"
                or identity["build_id"] != manifest["images"]["bus"]["build_id"]
            ):
                ota(args, "bus", "restore")
            report["restore"] = asyncio.run(final_cleanup(args, manifest))
        except BaseException as exc:  # noqa: BLE001 -- report original and restoration errors separately
            report["restore"] = {"status": "unknown", "error": type(exc).__name__ + ": " + str(exc)}
        save(args.output / "summary.json", report)
    print(
        json.dumps(
            {
                "profiles": [(p["profile"], p.get("status")) for p in report["profiles"]],
                "restore": report["restore"]["status"],
                "evidence": str(args.output),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return (
        0
        if not report.get("error")
        and report["restore"]["status"] == "confirmed"
        and all(p.get("status") == "passed" for p in report["profiles"])
        else 1
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles", nargs="+", choices=["bus", "signal", "iot"], default=["bus", "signal", "iot"]
    )
    parser.add_argument("--port", required=True)
    parser.add_argument("--expected-device", required=True)
    parser.add_argument("--firmware-repo", type=Path, required=True)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    args.prefix = "sdk-" + uuid.uuid4().hex[:8]
    repo = Path(__file__).resolve().parents[1]
    imported = Path(limivia.__file__).resolve()
    assert not imported.is_relative_to(repo), (
        "acceptance must import the installed wheel outside repo"
    )
    assert sys.version_info[:2] == (3, 12)
    assert args.port == PORT and args.expected_device == MAC
    manifest = validate_images(args)
    report = {
        "interpreter": sys.executable,
        "prefix": sys.prefix,
        "sdk_import": str(imported),
        "sdk_version": limivia.__version__,
        "wheel": str(args.wheel),
        "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        "contract": manifest["contract"],
        "image_source_commit": manifest["source_commit"],
        "test_prefix": args.prefix,
        "excluded_gpio": sorted(EXCLUDED),
        "profiles": [],
        "boundaries": {
            "physical_transport": "USB only",
            "external_peripherals": "unverified",
            "BLE_WS_MQTT_hardware": "unverified: no usable link fixture",
            "broker_ESP_NOW_peer_interop": "unverified",
            "physical_measurements": "unverified",
        },
    }
    return execute(args, manifest, report)


if __name__ == "__main__":
    raise SystemExit(main())
