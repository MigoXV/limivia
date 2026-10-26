import asyncio

import pytest

from limivia import AsyncLimivia, InvalidCommandError
from limivia.types import GPIOState, PWMState
from tests.fakes import FakeBackend


def test_direct_open_and_write_each_use_one_device_request():
    async def run():
        backend = FakeBackend()
        backend.connection.direct = True
        async with AsyncLimivia.connect(kind="usb", backend=backend) as board:
            await board.control.acquire()
            before = len(backend.connection.commands)
            led = await board.gpio.output(13, value=1)
            assert led.info and led.initial_state.data["level"] == 1
            assert [c["op"] for c in backend.connection.commands[before:]] == ["resource.open"]
            for level in (0, 1):
                before = len(backend.connection.commands)
                state = await led.write(level)
                assert isinstance(state, GPIOState) and state.level == level
                assert state.resource == led.info.id and state.instance == led.info.instance
                sent = backend.connection.commands[before:]
                assert [c["op"] for c in sent] == ["resource.call"]
                assert sent[0]["params"]["instance"] == led.info.instance
            await led.close()
            pwm = await board.pwm.open(13, frequency=1000, duty=25)
            before = len(backend.connection.commands)
            state = await pwm.set_duty(50)
            assert isinstance(state, PWMState) and state.duty_percent == 50
            assert [c["op"] for c in backend.connection.commands[before:]] == ["resource.call"]

    asyncio.run(run())


def test_job_submit_rejects_direct_open_before_any_device_write():
    async def run():
        backend = FakeBackend()
        async with AsyncLimivia.connect(kind="usb", backend=backend) as board:
            before = len(backend.connection.commands)
            with pytest.raises(InvalidCommandError, match="直接返回"):
                await board.jobs.submit(
                    {
                        "type": "resource.open",
                        "params": {
                            "kind": "gpio",
                            "pins": {"pin": 13},
                            "config": {"mode": "output"},
                        },
                    }
                )
            assert len(backend.connection.commands) == before

    asyncio.run(run())


def test_foreground_burst_yields_to_a_background_page_after_four_frames():
    async def run():
        backend = FakeBackend()
        backend.connection.direct = True
        async with AsyncLimivia.connect(kind="usb", backend=backend) as board:
            led = await board.gpio.output(13)
            core = board._core
            core._foreground_burst = 0
            before = len(backend.connection.commands)
            page = core._enqueue({"type": "state", "params": {"page": 0}}, internal=True)
            requests = [
                core._enqueue(
                    {
                        "type": "resource.call",
                        "params": {
                            "resource": led.info.id,
                            "instance": led.info.instance,
                            "action": "read",
                            "args": {},
                        },
                    }
                )
                for _ in range(6)
            ]
            await asyncio.gather(page.future, *(r.future for r in requests))
            operations = [c["op"] for c in backend.connection.commands[before:]]
            assert operations == ["resource.call"] * 4 + ["state"] + ["resource.call"] * 2

    asyncio.run(run())


def test_missing_confirmed_state_is_unknown_and_never_replayed():
    from limivia import ResultUnknownError

    async def run():
        backend = FakeBackend()
        backend.connection.direct = True
        async with AsyncLimivia.connect(kind="usb", backend=backend) as board:
            led = await board.gpio.output(13)
            before = len(backend.connection.commands)

            def incomplete(response):
                response["result"].pop("mode", None)
                return response

            backend.connection.bad_response = incomplete
            try:
                with pytest.raises(ResultUnknownError) as error:
                    await led.write(1)
                assert error.value.may_have_executed
                assert [c["op"] for c in backend.connection.commands[before:]] == ["resource.call"]
            finally:
                backend.connection.bad_response = None

    asyncio.run(run())
