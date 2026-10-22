import asyncio
import logging

import pytest

from examples import async_adc, async_events
from limivia import AsyncLimivia

from .example_fakes import ExampleBackend
from .fakes import SAMPLE


def sample_event(*, pin=0, raw=1234):
    return {"v": 1, "event": "adc", "data": {**SAMPLE, "pin": pin, "raw": raw}}


def assert_no_background_tasks():
    assert not [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and task.get_name().startswith(("limivia-", "example-"))
    ]


def test_adc_exact_count_filters_pin_and_late_samples(caplog):
    caplog.set_level(logging.INFO)
    backend = ExampleBackend()

    def configure(transport):
        transport.before_reply["adc.start"] = [sample_event(raw=999)]
        transport.after_reply["adc.start"] = [
            sample_event(pin=1, raw=888),
            sample_event(raw=111),
            sample_event(raw=222),
            sample_event(raw=333),
        ]
        transport.before_reply["adc.stop"] = [sample_event(raw=444)]

    backend.configure = configure

    async def run():
        async with AsyncLimivia(backend=backend) as client:
            await async_adc.run(client, samples=3)
        assert_no_background_tasks()

    asyncio.run(run())
    transport = backend.transports[-1]
    assert [c["op"] for c in transport.commands] == ["hello", "adc.start", "adc.stop"]
    samples = [r.message for r in caplog.records if r.message.startswith("样本 ")]
    assert len(samples) == 3
    assert all(f"raw={raw}" in line for raw, line in zip([1234, 111, 222], samples, strict=True))
    assert transport.state["streams"] == []
    assert transport.closed
    assert "ADC 已确认停止" in caplog.text


def test_single_uncalibrated_sample_needs_no_notification(caplog):
    caplog.set_level(logging.INFO)
    backend = ExampleBackend()
    backend.configure = lambda t: t.sample.update(calibrated=False, millivolts=None)

    async def run():
        async with AsyncLimivia(backend=backend) as client:
            await async_adc.run(client, samples=1)
        assert_no_background_tasks()

    asyncio.run(run())
    assert "样本 1/1" in caplog.text
    assert "未校准／无电压值" in caplog.text


def test_unrelated_notifications_do_not_reset_idle_timeout(caplog):
    backend = ExampleBackend()

    async def run():
        async with AsyncLimivia(backend=backend) as client:
            task = asyncio.create_task(async_adc.run(client, samples=2, idle_timeout=0.03))
            while not backend.transports:
                await asyncio.sleep(0)
            transport = backend.transports[0]
            await transport.started.wait()

            async def unrelated():
                while not transport.closed:
                    await transport.emit(sample_event(pin=1))
                    await transport.emit({"v": 1, "event": "changed", "revision": 2})
                    await asyncio.sleep(0.001)

            noise = asyncio.create_task(unrelated())
            try:
                async with asyncio.timeout(0.5):
                    with pytest.raises(RuntimeError, match="没有有效样本"):
                        await task
            finally:
                noise.cancel()
                await asyncio.gather(noise, return_exceptions=True)
        assert_no_background_tasks()

    asyncio.run(run())
    assert backend.transports[0].closed
    assert "停止状态未确认" not in caplog.text


@pytest.mark.parametrize("phase", ["sampling", "cleanup"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_cancellation_waits_for_cleanup_and_preserves_cancel(
    phase,
    cleanup_fails,
    caplog,
):
    caplog.set_level(logging.INFO)
    backend = ExampleBackend()

    def configure(transport):
        transport.reply_delay["adc.stop"] = 0.03
        # 保留停止阶段信号，让取消确实发生在等待应答期间。
        if cleanup_fails:
            transport.silent_op = "adc.stop"

    backend.configure = configure

    async def run():
        async with AsyncLimivia(backend=backend, timeout=0.08) as client:
            task = asyncio.create_task(
                async_adc.run(client, samples=1 if phase == "cleanup" else 2)
            )
            while not backend.transports:
                await asyncio.sleep(0)
            transport = backend.transports[0]
            await (transport.stopping if phase == "cleanup" else transport.started).wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert_no_background_tasks()

    asyncio.run(run())
    transport = backend.transports[0]
    assert [c["op"] for c in transport.commands].count("adc.stop") == 1
    assert transport.closed
    if cleanup_fails:
        assert "停止状态未确认" in caplog.text
        assert "ADC 已确认停止" not in caplog.text
    else:
        assert "ADC 已确认停止" in caplog.text


@pytest.mark.parametrize("failure", ["busy", "refused", "uncertain", "disconnected", "stop"])
def test_async_failures_have_no_retry_or_false_stop_confirmation(failure, caplog):
    backend = ExampleBackend()

    def configure(transport):
        if failure == "busy":
            transport.state["pins"][0]["mode"] = "output"
        elif failure == "refused":
            transport.failures["adc.start"] = {"code": "pin_busy", "message": "引脚被占用"}
        elif failure == "uncertain":
            transport.silent_op = "adc.start"
        elif failure == "disconnected":
            transport.disconnect_op = "adc.start"
        else:
            transport.failures["adc.stop"] = {"code": "hardware_error", "message": "停止失败"}

    backend.configure = configure

    async def run():
        async with AsyncLimivia(backend=backend, timeout=0.03) as client:
            with pytest.raises(RuntimeError):
                await async_adc.run(client, samples=1)
        assert_no_background_tasks()

    asyncio.run(run())
    transport = backend.transports[0]
    operations = [c["op"] for c in transport.commands]
    assert operations.count("adc.start") <= 1
    if failure in ("busy", "refused"):
        assert "adc.stop" not in operations
    elif failure == "uncertain":
        assert operations.count("adc.stop") == 1
    else:
        assert "停止状态未确认" in caplog.text
        assert "ADC 已确认停止" not in caplog.text
    assert transport.closed


def test_event_dispatch_coalesces_changes_and_keeps_unknown_and_protocol_errors(
    caplog, monkeypatch
):
    caplog.set_level(logging.INFO)
    backend = ExampleBackend()

    def configure(transport):
        transport.before_reply["hello"] = [
            {"v": 1, "event": "changed", "revision": 2},
            {"v": 1, "event": "changed", "revision": 3},
        ]
        transport.after_reply["state"] = [
            {"v": 1, "event": "future", "data": {"value": 42}},
            {"v": 2, "event": "changed"},
            sample_event(pin=1),
        ]

    backend.configure = configure
    displayed, counted = [], []
    original_display, original_count = async_events.display, async_events.count_event

    def display(event):
        displayed.append(event.type)
        original_display(event)

    def count(event, counts):
        counted.append(event.type)
        original_count(event, counts)

    monkeypatch.setattr(async_events, "display", display)
    monkeypatch.setattr(async_events, "count_event", count)

    async def run():
        async with AsyncLimivia(backend=backend) as client:
            await async_events.run(client, duration=0.05)
        assert_no_background_tasks()

    asyncio.run(run())
    assert displayed == counted
    assert {"state.changed", "state.completed", "unknown", "protocol.error", "adc.sample"} <= set(
        counted
    )
    transport = backend.transports[0]
    assert [c["op"] for c in transport.commands] == ["hello", "hello", "state", "state"]
    assert "未建模通知" in caplog.text
    assert "事件计数" in caplog.text
    assert transport.closed


@pytest.mark.parametrize("failure", ["refused", "timeout", "disconnect"])
def test_event_monitor_surfaces_failed_read_only_requests(failure):
    backend = ExampleBackend()

    def configure(transport):
        if failure == "refused":
            transport.failures["state"] = {"code": "hardware_error", "message": "状态不可用"}
        elif failure == "timeout":
            transport.silent_op = "state"
        else:
            transport.disconnect_op = "state"

    backend.configure = configure

    async def run():
        async with AsyncLimivia(backend=backend, timeout=0.02) as client:
            with pytest.raises(RuntimeError):
                await async_events.run(client, duration=1)
        assert_no_background_tasks()

    asyncio.run(run())
    assert [c["op"] for c in backend.transports[0].commands].count("state") == 1
