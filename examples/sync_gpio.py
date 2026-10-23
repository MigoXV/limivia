import time

from ._common import (
    DurationOption,
    Kind,
    KindOption,
    PinOption,
    TargetOption,
    connect_sync,
    execute,
    resource_sync,
    wait,
)


def main(
    kind: KindOption = Kind.usb,
    target: TargetOption = None,
    pin: PinOption = 13,
    duration: DurationOption = 1,
):
    with (
        connect_sync(kind, target, control=True) as c,
        resource_sync(c, "gpio", {"pin": pin}, {"mode": "output", "level": 1}) as resource,
    ):
        print(wait(c, c.resource.call(resource=resource, action="read", args={})))
        time.sleep(duration)


if __name__ == "__main__":
    execute(main)()
