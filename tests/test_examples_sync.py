import asyncio
import importlib
import logging
import threading
from types import SimpleNamespace

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from examples import (
    async_state,
    discover,
    sync_adc,
    sync_cleanup,
    sync_gpio,
    sync_pwm,
    sync_state,
    sync_timer,
)
from examples._common import select_device
from limivia import AsyncLimivia, Limivia
from limivia.types import DeviceInfo

from .example_fakes import ExampleBackend

MODULES = [
    "async_adc",
    "async_events",
    "discover",
    "sync_state",
    "async_state",
    "sync_gpio",
    "sync_pwm",
    "sync_adc",
    "sync_timer",
    "sync_cleanup",
]
RESOURCES = [
    (sync_gpio, {"duration": 0}, "gpio.set", "pin.release", 13),
    (sync_pwm, {"duration": 0}, "pwm.set", "pwm.stop", 13),
    (sync_adc, {}, "adc.read", "pin.release", 0),
    (sync_timer, {"duration": 0}, "timer.start", "timer.stop", 13),
]


@pytest.mark.parametrize("name", MODULES)
def test_help_without_device_access(name, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("--help 不应扫描或连接设备")

    monkeypatch.setattr("limivia.transports.DeviceBackend.discover", forbidden)
    module = importlib.import_module(f"examples.{name}")
    app = typer.Typer()
    app.command()(module.main)
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "--kind" in result.output


def test_select_device_requires_unambiguous_current_scan():
    one = DeviceInfo(id="a", name="设备 A")
    two = DeviceInfo(id="b", name="设备 B")
    assert select_device([one], None) == "a"
    assert select_device([one, two], "b") == "b"
    for candidates, target, message in [
        ([], None, "未发现设备"),
        ([one, two], None, "--target"),
        ([one], "missing", "设备 A"),
    ]:
        with pytest.raises(RuntimeError, match=message):
            select_device(candidates, target)


def test_discover_only_lists_and_state_examples_are_read_only(caplog):
    caplog.set_level(logging.INFO)
    backend = ExampleBackend()
    with Limivia(backend=backend) as client:
        discover.run(client, kind="usb")
    assert not backend.transports
    assert "设备 ID=test" in caplog.text
    with Limivia(backend=backend) as client:
        sync_state.run(client)

    async def run():
        async with AsyncLimivia(backend=backend) as client:
            await async_state.run(client)

    asyncio.run(run())
    for transport in backend.transports:
        assert [c["op"] for c in transport.commands] == ["hello", "hello", "state"]
        assert transport.closed


@pytest.mark.parametrize("module,params,start,stop,pin", RESOURCES)
def test_resource_success_releases_only_own_pin(module, params, start, stop, pin):
    backend = ExampleBackend()

    def configure(transport):
        transport.state["pins"][1]["mode"] = "output"  # 其他程序的 GPIO1。
        transport.before_reply[start] = [{"v": 1, "event": "changed", "revision": 2}]

    backend.configure = configure
    with Limivia(backend=backend) as client:
        module.run(client, **params)
    transport = backend.transports[-1]
    operations = [c["op"] for c in transport.commands]
    assert operations.count(start) == operations.count(stop) == 1
    assert operations[-1] == stop
    assert next(p for p in transport.state["pins"] if p["pin"] == pin)["mode"] == "idle"
    assert transport.state["pins"][1]["mode"] == "output"
    assert transport.closed
    assert not any(t.name == "limivia-sync" for t in threading.enumerate())


@pytest.mark.parametrize("module,params,start,stop,pin", RESOURCES)
@pytest.mark.parametrize("failure", ["busy", "refused", "uncertain", "disconnected"])
def test_resource_failures_do_not_retry_or_clear_foreign_resources(
    module,
    params,
    start,
    stop,
    pin,
    failure,
    caplog,
):
    backend = ExampleBackend()

    def configure(transport):
        if failure == "busy":
            next(p for p in transport.state["pins"] if p["pin"] == pin)["mode"] = "output"
        elif failure == "refused":
            transport.failures[start] = {"code": "pin_busy", "message": "已占用"}
        elif failure == "uncertain":
            transport.silent_op = start
        else:
            transport.disconnect_op = start

    backend.configure = configure
    with Limivia(backend=backend, timeout=0.03) as client:
        with pytest.raises(RuntimeError):
            module.run(client, **params)
    transport = backend.transports[-1]
    operations = [c["op"] for c in transport.commands]
    assert operations.count(start) <= 1
    if failure in ("busy", "refused"):
        assert stop not in operations
    elif failure == "uncertain":
        assert operations.count(stop) == 1
    else:
        assert "停止状态未确认" in caplog.text
    assert transport.closed


@pytest.mark.parametrize("module,params,start,stop,pin", [RESOURCES[0], RESOURCES[1], RESOURCES[3]])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_ctrl_c_cleans_up_and_preserves_original_interrupt(
    module,
    params,
    start,
    stop,
    pin,
    cleanup_fails,
    monkeypatch,
    caplog,
):
    def interrupt(_duration):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=interrupt))
    backend = ExampleBackend()
    if cleanup_fails:
        backend.configure = lambda t: t.failures.update(
            {stop: {"code": "hardware_error", "message": "停止失败"}}
        )
    with Limivia(backend=backend) as client:
        with pytest.raises(KeyboardInterrupt):
            module.run(client, **params)
    transport = backend.transports[-1]
    assert [c["op"] for c in transport.commands].count(stop) == 1
    assert transport.closed
    if cleanup_fails:
        assert "停止状态未确认" in caplog.text


def test_invalid_submission_does_not_release_and_nullable_adc_is_explicit(caplog):
    backend = ExampleBackend()
    with Limivia(backend=backend) as client:
        with pytest.raises(ValidationError):
            sync_pwm.run(client, frequency=1)
    assert [c["op"] for c in backend.transports[-1].commands] == ["hello"]
    backend.configure = lambda t: t.sample.update(millivolts=None, calibrated=False)
    caplog.set_level(logging.INFO)
    with Limivia(backend=backend) as client:
        sync_adc.run(client)
    assert "未校准／无电压值" in caplog.text


@pytest.mark.parametrize("params", [{"pin": 13}, {"all_outputs": True}])
def test_explicit_cleanup_is_acknowledged(params, caplog):
    caplog.set_level(logging.INFO)
    backend = ExampleBackend()
    backend.configure = lambda t: t.state["pins"][-1].update(mode="output", level=1)
    with Limivia(backend=backend) as client:
        sync_cleanup.run(client, **params)
    assert backend.transports[-1].state["pins"][-1]["mode"] == "idle"
    assert "已确认清理" in caplog.text


@pytest.mark.parametrize("args", [[], ["--all", "--pin", "13"]])
def test_cleanup_requires_explicit_exclusive_target(args):
    app = typer.Typer()
    app.command()(sync_cleanup.main)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert "必须且只能选择" in result.output


@pytest.mark.parametrize("pattern,count", [("pulse", 0), ("blink", 1)])
@pytest.mark.parametrize("finish_before", [None, "state", "cleanup"])
def test_finite_timer_release_handles_natural_completion_and_query_race(
    pattern,
    count,
    finish_before,
):
    backend = ExampleBackend()
    backend.configure = lambda t: setattr(t, "finish_timer_before", finish_before)
    with Limivia(backend=backend) as client:
        sync_timer.run(client, pattern=pattern, count=count, duration=0)
    transport = backend.transports[0]
    assert [c["op"] for c in transport.commands] == [
        "hello",
        "timer.start",
        "state",
        "pin.release",
    ]
    assert transport.state["pins"][-1]["mode"] == "idle"
    assert transport.state["timers"] == []
    assert transport.closed
