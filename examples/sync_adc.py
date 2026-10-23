from ._common import (
    Kind,
    KindOption,
    PinOption,
    TargetOption,
    connect_sync,
    execute,
    resource_sync,
    wait,
)


def main(kind: KindOption = Kind.usb, target: TargetOption = None, pin: PinOption = 0):
    with (
        connect_sync(kind, target, control=True) as c,
        resource_sync(c, "adc", {"pin": pin}, {}) as resource,
    ):
        print(wait(c, c.resource.call(resource=resource, action="read", args={})))


if __name__ == "__main__":
    execute(main)()
