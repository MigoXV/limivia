import asyncio
import base64
import json
import struct
import sys
from functools import partial
from types import SimpleNamespace

from examples._common import run
from examples.peripherals import async_adc, async_gpio_blink
from limivia import AsyncLimivia
from tests.fakes import FakeBackend, FakeTransport


def use_backend(monkeypatch, module, backend, **asyncio_functions):
    monkeypatch.setattr(
        module,
        "AsyncLimivia",
        SimpleNamespace(
            connect=partial(AsyncLimivia.connect, backend=backend, job_poll_interval=0.01),
        ),
    )

    async def sleep(delay):
        await asyncio.sleep(0)

    monkeypatch.setattr(module, "asyncio", SimpleNamespace(sleep=sleep, **asyncio_functions))


def test_async_blink_runs_five_cycles_and_releases(monkeypatch):
    backend = FakeBackend()
    use_backend(monkeypatch, async_gpio_blink, backend)
    monkeypatch.setattr(sys, "argv", ["async_gpio_blink"])
    run(async_gpio_blink.main)
    writes = [
        command["params"]["args"]["level"]
        for command in backend.connection.commands
        if command["op"] == "resource.call" and command["params"]["action"] == "write"
    ]
    assert writes == [1, 0] * 5
    assert backend.connection.closed and not backend.connection.resources


def test_async_adc_prints_only_three_decoded_samples(monkeypatch, capsys):
    class Sampling(FakeTransport):
        async def handle(self, wire):
            await super().handle(wire)
            if wire["method"] == "resource.call" and wire["params"]["args"]["action"] == "events":
                for job in self.jobs.values():
                    if job["action"] == "events":
                        job["result"]["events"] = [
                            {
                                "sequence": index,
                                "time_us": float(index * 100000),
                                "data": base64.b64encode(
                                    struct.pack("<ii", 100 + index, -1)
                                ).decode(),
                            }
                            for index in range(4)
                        ]

    backend = FakeBackend(Sampling())
    use_backend(monkeypatch, async_adc, backend, timeout=asyncio.timeout)
    asyncio.run(async_adc.main())
    samples = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [sample["raw"] for sample in samples] == [100, 101, 102]
    assert all(sample["millivolts"] is None for sample in samples)
    assert backend.connection.closed and not backend.connection.resources
