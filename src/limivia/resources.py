"""同步和异步客户端共享的资源方法；T 为 int 或 Awaitable[int]。"""

from collections.abc import Callable
from typing import Literal

from .types import (
    ADCReadCommand,
    ADCStartCommand,
    ADCStopCommand,
    ClientEvent,
    ClientEventParam,
    GPIOReadCommand,
    GPIOSetCommand,
    OutputsStopCommand,
    PinReleaseCommand,
    Pull,
    PWMSetCommand,
    PWMStopCommand,
    StateCommand,
    TimerStartCommand,
    TimerStopCommand,
)


class Resource[T]:
    def __init__(self, send: Callable[[ClientEvent | ClientEventParam], T]):
        self._send = send


class StateResource[T](Resource[T]):
    def retrieve(self) -> T:
        return self._send(StateCommand())


class GPIOResource[T](Resource[T]):
    def set(
        self,
        *,
        pin: int,
        mode: Literal["input", "output"],
        pull: Pull = "none",
        level: Literal[0, 1] = 0,
    ) -> T:
        return self._send(
            GPIOSetCommand(
                params={
                    "pin": pin,
                    "mode": mode,
                    "pull": pull,
                    "level": level,
                }
            )
        )

    def read(self, *, pin: int) -> T:
        return self._send(GPIOReadCommand(params={"pin": pin}))


class PWMResource[T](Resource[T]):
    def set(self, *, pin: int, frequency: int, duty: float, breath_ms: int = 0) -> T:
        return self._send(
            PWMSetCommand(
                params={
                    "pin": pin,
                    "frequency": frequency,
                    "duty": duty,
                    "breath_ms": breath_ms,
                }
            )
        )

    def stop(self, *, pin: int) -> T:
        return self._send(PWMStopCommand(params={"pin": pin}))


class ADCResource[T](Resource[T]):
    def read(self, *, pin: int) -> T:
        return self._send(ADCReadCommand(params={"pin": pin}))

    def start(self, *, pin: int, interval_ms: int) -> T:
        return self._send(ADCStartCommand(params={"pin": pin, "interval_ms": interval_ms}))

    def stop(self, *, pin: int) -> T:
        return self._send(ADCStopCommand(params={"pin": pin}))


class TimerResource[T](Resource[T]):
    def start(
        self,
        *,
        pin: int,
        kind: Literal["blink", "pulse"],
        high_ms: int,
        low_ms: int = 1000,
        count: int = 0,
    ) -> T:
        return self._send(
            TimerStartCommand(
                params={
                    "pin": pin,
                    "kind": kind,
                    "high_ms": high_ms,
                    "low_ms": low_ms,
                    "count": count,
                }
            )
        )

    def stop(self, *, pin: int) -> T:
        return self._send(TimerStopCommand(params={"pin": pin}))


class PinResource[T](Resource[T]):
    def release(self, *, pin: int) -> T:
        return self._send(PinReleaseCommand(params={"pin": pin}))


class OutputsResource[T](Resource[T]):
    def stop(self) -> T:
        return self._send(OutputsStopCommand())
