"""按发现选择UART内部回环或片内温度；结束显式停止全部实验。"""

import asyncio

from ._common import (
    Kind,
    KindOption,
    TargetOption,
    await_result,
    connect_async,
    execute,
    resource_async,
)


async def run(kind: Kind, target: str | None):
    async with connect_async(kind, target) as connection:
        discovery = await await_result(connection, await connection.discover())
        print(discovery.identity.to_json())
        available = {r.kind for r in discovery.resources if r.available}
        if not available.intersection({"uart", "temperature"}):
            raise RuntimeError("没有适用的演示能力")
        try:
            await await_result(connection, await connection.control.acquire())
            if "uart" in available:
                async with resource_async(
                    connection, "uart", {"tx": 20, "rx": 21}, {"loopback": True}
                ) as resource:
                    await await_result(
                        connection,
                        await connection.resource.call(
                            resource=resource,
                            action="write",
                            args={"data": b"LIMIVIA\x00\xff"},
                        ),
                    )
                    value = await await_result(
                        connection,
                        await connection.resource.call(
                            resource=resource,
                            action="read",
                            args={"length": 9},
                        ),
                    )
                    print(value)
            else:
                async with resource_async(connection, "temperature", {}, {}) as resource:
                    value = await await_result(
                        connection,
                        await connection.resource.call(
                            resource=resource,
                            action="read",
                            args={},
                        ),
                    )
                    print(value)
        finally:
            stopped = await await_result(connection, await connection.outputs.stop())
            print("停止清理和持久化已确认", stopped)


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    asyncio.run(run(kind, target))


if __name__ == "__main__":
    execute(main)()
