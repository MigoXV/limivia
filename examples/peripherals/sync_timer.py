import time
from typing import Annotated

import typer

from .._common import (
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
    high_ms: Annotated[int, typer.Option(min=10)] = 100,
    low_ms: Annotated[int, typer.Option(min=10)] = 100,
    count: Annotated[int, typer.Option(min=0)] = 0,
):
    with (
        connect_sync(kind, target, control=True) as c,
        resource_sync(
            c, "timer", {"pin": pin}, {"high_ms": high_ms, "low_ms": low_ms, "count": count}
        ),
    ):
        time.sleep(duration)


if __name__ == "__main__":
    execute(main)()
