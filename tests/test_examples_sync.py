import sys
from functools import partial
from types import SimpleNamespace

import pytest

from examples._common import run
from examples.peripherals import (
    adc,
    gpio,
    gpio_blink,
    pwm,
    timer,
    uart,
)
from limivia import Limivia, ResourceCleanupError
from tests.fakes import FakeBackend


def use_backend(monkeypatch, module, backend):
    monkeypatch.setattr(
        module,
        "Limivia",
        SimpleNamespace(
            connect=partial(Limivia.connect, backend=backend, job_poll_interval=0.01),
        ),
    )


def writes(backend):
    return [
        command["params"]["args"]["level"]
        for command in backend.connection.commands
        if command["op"] == "resource.call" and command["params"]["action"] == "write"
    ]


def test_gpio_example_lights_until_input_then_releases(monkeypatch):
    backend = FakeBackend()
    use_backend(monkeypatch, gpio, backend)

    def finish(prompt):
        assert "按回车" in prompt
        assert (
            next(iter(backend.connection.resources.values()))["definition"]["config"]["level"] == 1
        )
        return ""

    monkeypatch.setattr("builtins.input", finish)
    gpio.main()
    assert writes(backend) == [0]
    assert backend.connection.closed and not backend.connection.resources
    assert sum(c["op"] == "resource.close" for c in backend.connection.commands) == 1


def test_blink_example_performs_five_cycles_without_real_sleep(monkeypatch):
    backend = FakeBackend()
    use_backend(monkeypatch, gpio_blink, backend)
    sleeps = []
    monkeypatch.setattr(gpio_blink, "sleep", sleeps.append)
    monkeypatch.setattr(sys, "argv", ["gpio_blink"])
    run(gpio_blink.main)
    assert writes(backend) == [1, 0] * 5
    assert sleeps == [0.5] * 10
    assert backend.connection.closed and not backend.connection.resources


@pytest.mark.parametrize("module", [adc, uart, pwm, timer])
def test_peripheral_example_runs_and_releases_owned_resources(module, monkeypatch):
    backend = FakeBackend()
    use_backend(monkeypatch, module, backend)
    if hasattr(module, "sleep"):
        monkeypatch.setattr(module, "sleep", lambda _: None)
    module.main()
    assert backend.connection.closed and not backend.connection.resources


def test_input_error_stays_primary_when_resource_cleanup_also_fails(monkeypatch):
    backend = FakeBackend()
    use_backend(monkeypatch, gpio, backend)
    original = ValueError("input failed")

    def fail(prompt):
        backend.connection.reject_op = "resource.close"
        raise original

    monkeypatch.setattr("builtins.input", fail)
    with pytest.raises(ValueError) as caught:
        gpio.main()
    assert caught.value is original
    assert any(isinstance(error, ResourceCleanupError) for error in original.cleanup_errors)
    assert backend.connection.closed


@pytest.mark.parametrize("module_name", ["storage", "flow"])
def test_upload_failure_aborts_and_preserves_original_if_abort_fails(module_name, monkeypatch):
    import importlib

    from limivia import DeviceRejectedError
    from tests.fakes import FakeTransport

    class UploadFails(FakeTransport):
        async def handle(self, wire):
            if wire["method"] == "storage.abort":
                self.commands.append({"op": "storage.abort"})
                await self.emit(
                    {"id": wire["id"], "ok": False, "error": {"reason": "abort_failed"}}
                )
                return
            await super().handle(wire)
            for job in self.jobs.values():
                if job["action"] == "storage.begin":
                    job["result"] = {"upload_id": 1}

    backend = FakeBackend(UploadFails())
    backend.connection.reject_op = "storage.chunk"
    module = importlib.import_module(f"examples.workflows.{module_name}")
    use_backend(monkeypatch, module, backend)
    with pytest.raises(DeviceRejectedError) as caught:
        module.main()
    assert caught.value.op == "storage.chunk"
    assert any("abort_failed" in note for note in caught.value.__notes__)
    assert sum(c["op"] == "storage.abort" for c in backend.connection.commands) == 1
    assert backend.connection.closed
