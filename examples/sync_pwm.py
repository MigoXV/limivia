import time
from typing import Annotated

import typer

from ._common import (
    DurationOption,
    Kind,
    KindOption,
    PinOption,
    TargetOption,
    connect_sync,
    execute,
    resource_sync,
)


def main(
    kind: KindOption = Kind.usb,
    target: TargetOption = None,
    pin: PinOption = 13,
    duration: DurationOption = 1,
    frequency: Annotated[int, typer.Option(min=1)] = 1000,
    duty: Annotated[float, typer.Option(min=0, max=100)] = 25,
    breath_ms: Annotated[int, typer.Option(min=0)] = 0,
):
    with (
        connect_sync(kind, target, control=True) as c,
        resource_sync(
            c,
            "pwm",
            {"pin": pin},
            {"frequency": frequency, "resolution": 10, "duty": duty, "breath_ms": breath_ms},
        ),
    ):
        time.sleep(duration)


if __name__ == "__main__":
    execute(main)()
