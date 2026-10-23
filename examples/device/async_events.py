import asyncio

from .._common import (
    DurationOption,
    Kind,
    KindOption,
    TargetOption,
    await_result,
    connect_async,
    execute,
)


async def run(kind: Kind, target: str | None, duration: float):
    async with connect_async(kind, target) as c:
        await await_result(c, await c.events.subscribe(topics=["job", "resource", "flow", "data"]))
        await c.state.retrieve()
        try:
            async with asyncio.timeout(duration):
                async for event in c:
                    print(event.to_json())
        except TimeoutError:
            pass


def main(kind: KindOption = Kind.usb, target: TargetOption = None, duration: DurationOption = 2):
    asyncio.run(run(kind, target, duration))


if __name__ == "__main__":
    execute(main)()
