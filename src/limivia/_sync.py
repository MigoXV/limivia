"""同步业务门面：所有异步任务复用客户端的持久 BlockingPortal。"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, Self, Unpack

from anyio.from_thread import BlockingPortal

from ._board import AsyncBoard, AsyncJob, AsyncSubscription, Topic
from ._peripherals import AsyncADCInput, AsyncGPIOPin, AsyncPWMOutput, AsyncResource, AsyncUARTPort
from .constants import Level
from .resources import Resources
from .types import (
    CapabilitiesPage,
    ClientEvent,
    ClientEventParam,
    DeviceDiscovery,
    DeviceEvent,
    DeviceIdentity,
    JobStatus,
    ResourceInfo,
    ResourceKind,
    StatePage,
    StateSnapshot,
)
from .types import (
    Diagnostics as DiagnosticsResult,
)
from .types.results import (
    ADCSample,
    GPIOConfig,
    GPIOState,
    OperationResult,
    PeripheralEvents,
    PWMConfig,
    PWMState,
    UARTConfig,
)


class Resource[R: AsyncResource]:
    def __init__(self, resource: R, portal: BlockingPortal):
        self._async = resource
        self._portal = portal

    @property
    def info(self) -> ResourceInfo | None:
        return self._portal.call(lambda: self._async.info)

    def open(self) -> Self:
        self._portal.call(self._async.open)
        return self

    def __enter__(self) -> Self:
        self._portal.call(self._async.__aenter__)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._portal.call(self._async.__aexit__, exc_type, exc, tb)

    def close(self, *, cascade: bool = False) -> None:
        self._portal.call(partial(self._async.close, cascade=cascade))

    def recover(self, *, cascade: bool = False) -> None:
        self._portal.call(partial(self._async.recover, cascade=cascade))

    def status(self) -> OperationResult:
        return self._portal.call(self._async.status)

    def call(self, action: str, *, timeout_ms: int | None = None, **args: Any) -> OperationResult:
        return self._portal.call(partial(self._async.call, action, timeout_ms=timeout_ms, **args))


class GPIOPin(Resource[AsyncGPIOPin]):
    def read(self) -> int:
        return self._portal.call(self._async.read)

    def write(self, value: int) -> GPIOState:
        return self._portal.call(self._async.write, value)

    def events(self) -> PeripheralEvents:
        return self._portal.call(self._async.events)


class PWMOutput(Resource[AsyncPWMOutput]):
    def set_duty(self, duty: float) -> PWMState:
        return self._portal.call(self._async.set_duty, duty)

    def fade(self, duty: float, *, duration_ms: int) -> None:
        self._portal.call(partial(self._async.fade, duty, duration_ms=duration_ms))


class ADCInput(Resource[AsyncADCInput]):
    def read(self) -> ADCSample:
        return self._portal.call(self._async.read)

    def events(self) -> list[ADCSample]:
        return self._portal.call(self._async.events)


class UARTPort(Resource[AsyncUARTPort]):
    def write(self, data: bytes, *, timeout_ms: int | None = None) -> int:
        return self._portal.call(partial(self._async.write, data, timeout_ms=timeout_ms))

    def read(self, length: int, *, timeout_ms: int | None = None) -> bytes:
        return self._portal.call(partial(self._async.read, length, timeout_ms=timeout_ms))

    def drain(self, *, timeout_ms: int | None = None) -> None:
        self._portal.call(partial(self._async.drain, timeout_ms=timeout_ms))

    def clear(self) -> None:
        self._portal.call(self._async.clear)

    def errors(self) -> OperationResult:
        return self._portal.call(self._async.errors)

    def events(self) -> PeripheralEvents:
        return self._portal.call(self._async.events)

    def send_break(self, data: bytes, *, bits: int) -> None:
        self._portal.call(partial(self._async.send_break, data, bits=bits))


class GPIO:
    def __init__(self, board: Connection):
        self.board = board

    def output(
        self,
        pin: int,
        *,
        value: int = Level.LOW,
        open_drain: bool = False,
        **config: Unpack[GPIOConfig],
    ) -> GPIOPin:
        resource = self.board._portal.call(
            partial(
                self.board._async.gpio.output, pin, value=value, open_drain=open_drain, **config
            )
        )
        return GPIOPin(resource, self.board._portal)

    def input(self, pin: int, **config: Unpack[GPIOConfig]) -> GPIOPin:
        resource = self.board._portal.call(partial(self.board._async.gpio.input, pin, **config))
        return GPIOPin(resource, self.board._portal)


class PWM:
    def __init__(self, board: Connection):
        self.board = board

    def open(
        self,
        pin: int,
        *,
        frequency: int,
        duty: float = 0,
        resolution: int = 10,
        **config: Unpack[PWMConfig],
    ) -> PWMOutput:
        resource = self.board._portal.call(
            partial(
                self.board._async.pwm.open,
                pin,
                frequency=frequency,
                duty=duty,
                resolution=resolution,
                **config,
            )
        )
        return PWMOutput(resource, self.board._portal)


class ADC:
    def __init__(self, board: Connection):
        self.board = board

    def open(self, pin: int, *, attenuation: int = 0, interval_ms: int = 0) -> ADCInput:
        resource = self.board._portal.call(
            partial(
                self.board._async.adc.open, pin, attenuation=attenuation, interval_ms=interval_ms
            )
        )
        return ADCInput(resource, self.board._portal)


class UART:
    def __init__(self, board: Connection):
        self.board = board

    def open(
        self,
        *,
        tx: int | None = None,
        rx: int | None = None,
        rts: int | None = None,
        cts: int | None = None,
        baud: int = 115200,
        controller: int | None = None,
        **config: Unpack[UARTConfig],
    ) -> UARTPort:
        resource = self.board._portal.call(
            partial(
                self.board._async.uart.open,
                tx=tx,
                rx=rx,
                rts=rts,
                cts=cts,
                baud=baud,
                controller=controller,
                **config,
            )
        )
        return UARTPort(resource, self.board._portal)


class ResourceFactory:
    def __init__(self, board: Connection):
        self.board = board

    def open(
        self,
        kind: ResourceKind,
        *,
        pins: dict[str, int],
        config: dict[str, Any],
        parent: Resource | None = None,
        controller: int | None = None,
    ) -> Resource:
        resource = self.board._portal.call(
            partial(
                self.board._async.resources.open,
                kind,
                pins=pins,
                config=config,
                parent=parent._async if parent else None,
                controller=controller,
            )
        )
        return Resource(resource, self.board._portal)


class Job:
    def __init__(self, job: AsyncJob, portal: BlockingPortal):
        self._async = job
        self._portal = portal

    @property
    def id(self) -> int:
        return self._async.id

    @property
    def request_id(self) -> int | None:
        return self._async.request_id

    def status(self) -> JobStatus:
        return self._portal.call(self._async.status)

    def cancel(self) -> JobStatus:
        return self._portal.call(self._async.cancel)

    def wait(self, *, timeout: float | None = None) -> OperationResult:
        return self._portal.call(partial(self._async.wait, timeout=timeout))


class Jobs:
    def __init__(self, board: Connection):
        self.board = board

    def submit(self, command: ClientEvent | ClientEventParam) -> Job:
        return Job(
            self.board._portal.call(self.board._async.jobs.submit, command), self.board._portal
        )

    def get(self, job_id: int) -> Job:
        return Job(self.board._portal.call(self.board._async.jobs.get, job_id), self.board._portal)


class Subscription:
    def __init__(self, manager: AsyncSubscription, portal: BlockingPortal):
        self._manager = manager
        self._portal = portal
        self._stream = None

    def __enter__(self):
        self._stream = self._portal.call(self._manager.__aenter__)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._portal.call(self._manager.__aexit__, exc_type, exc, tb)

    def __iter__(self):
        return self

    def __next__(self):
        if self._stream is None:
            raise RuntimeError("请先进入订阅上下文")
        try:
            return self._portal.call(self._stream.__anext__)
        except StopAsyncIteration:
            raise StopIteration from None


class Notifications:
    def __init__(self, board: Connection):
        self.board = board

    def subscribe(
        self, *, topics: list[Topic], interval_ms: int = 100, queue_size: int | None = None
    ) -> Subscription:
        manager = self.board._portal.call(
            partial(
                self.board._async.notifications.subscribe,
                topics=topics,
                interval_ms=interval_ms,
                queue_size=queue_size,
            )
        )
        return Subscription(manager, self.board._portal)


class State:
    def __init__(self, board: Connection):
        self.board = board

    def retrieve(self, *, page: int | None = None, revision: int | None = None) -> StatePage:
        return self.board._portal.call(
            partial(self.board._async.state.retrieve, page=page, revision=revision)
        )

    def snapshot(self) -> StateSnapshot:
        return self.board._portal.call(self.board._async.state.snapshot)


class Capabilities:
    def __init__(self, board: Connection):
        self.board = board

    def retrieve(self, *, page: int | None = None) -> CapabilitiesPage:
        return self.board._portal.call(partial(self.board._async.capabilities.retrieve, page=page))


class RawEventStream:
    def __init__(self, stream, portal: BlockingPortal):
        self._stream = stream
        self._portal = portal

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self._portal.call(self._stream.close)

    def __iter__(self):
        return self

    def __next__(self) -> DeviceEvent:
        try:
            return self._portal.call(self._stream.__anext__)
        except StopAsyncIteration:
            raise StopIteration from None


class Diagnostics:
    def __init__(self, board: Connection):
        self.board = board

    def retrieve(self) -> DiagnosticsResult:
        return self.board._portal.call(self.board._async.diagnostics.retrieve)


class Control:
    def __init__(self, board: Connection):
        self.board = board

    def acquire(self) -> None:
        self.board._portal.call(self.board._async.control.acquire)

    def release(self) -> None:
        self.board._portal.call(self.board._async.control.release)


if TYPE_CHECKING:
    from ._client import RawConnection


class Connection:
    def __init__(self, board: AsyncBoard, portal: BlockingPortal):
        self._async = board
        self._portal = portal
        self._raw: RawConnection | None = None
        commands = Resources(self._execute)
        self.session = commands.session
        self.outputs = commands.outputs
        self.capabilities = Capabilities(self)
        self.mux = commands.mux
        self.buffer = commands.buffer
        self.storage = commands.storage
        self.ota = commands.ota
        self.wifi = commands.wifi
        self.mqtt = commands.mqtt
        self.espnow = commands.espnow
        self.power = commands.power
        self.system = commands.system
        self.flow = commands.flow
        self.rmt = commands.rmt
        self.gpio = GPIO(self)
        self.pwm = PWM(self)
        self.adc = ADC(self)
        self.uart = UART(self)
        self.resources = ResourceFactory(self)
        self.jobs = Jobs(self)
        self.notifications = Notifications(self)
        self.state = State(self)
        self.diagnostics = Diagnostics(self)
        self.control = Control(self)

    def _execute(self, command: ClientEvent | ClientEventParam) -> OperationResult:
        return self._portal.call(self._async._execute, command)

    @property
    def identity(self) -> DeviceIdentity | None:
        return self._portal.call(lambda: self._async.identity)

    @property
    def raw(self) -> RawConnection:
        from ._client import RawConnection

        if self._raw is None:
            self._raw = RawConnection(self._portal.call(lambda: self._async.raw), self._portal)
        return self._raw

    def discover(self, *, refresh: bool = False) -> DeviceDiscovery:
        return self._portal.call(partial(self._async.discover, refresh=refresh))

    def close(self) -> None:
        self._portal.call(self._async.close)
