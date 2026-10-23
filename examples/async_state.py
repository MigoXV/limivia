import asyncio

from ._common import Kind, KindOption, TargetOption, await_result, connect_async, execute


async def run(kind: Kind, target: str | None):
    async with connect_async(kind, target) as connection:
        snapshot = await await_result(connection, await connection.state.snapshot())
        print(snapshot.to_json())


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    asyncio.run(run(kind, target))


if __name__ == "__main__":
    execute(main)()
