import asyncio
import base64
import struct
from typing import Annotated

import typer

from ._common import (
    Kind,
    KindOption,
    PinOption,
    TargetOption,
    await_result,
    connect_async,
    execute,
    resource_async,
)


async def run(kind: Kind, target: str | None, pin: int, samples: int, interval_ms: int):
    async with (
        connect_async(kind, target, control=True) as c,
        resource_async(c, "adc", {"pin": pin}, {"interval_ms": interval_ms}) as resource,
    ):
        count = 0
        async with asyncio.timeout(max(10, samples * interval_ms / 1000 * 3)):
            while count < samples:
                packet = await await_result(
                    c, await c.resource.call(resource=resource, action="events", args={})
                )
                for event in packet["events"]:
                    raw, mv = struct.unpack("<ii", base64.b64decode(event["data"], validate=True))
                    print(
                        {
                            "raw": raw,
                            "millivolts": None if mv < 0 else mv,
                            "sequence": event["sequence"],
                        }
                    )
                    count += 1
                    if count == samples:
                        break
                await asyncio.sleep(interval_ms / 1000)


def main(
    kind: KindOption = Kind.usb,
    target: TargetOption = None,
    pin: PinOption = 0,
    samples: Annotated[int, typer.Option(min=1)] = 3,
    interval_ms: Annotated[int, typer.Option(min=10)] = 100,
):
    asyncio.run(run(kind, target, pin, samples, interval_ms))


if __name__ == "__main__":
    execute(main)()
