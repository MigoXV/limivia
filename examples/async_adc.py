"""采集 GPIO0，收到指定数量的数据后等待 adc.stop 的完成事件。"""

import asyncio
import logging

import typer

from limivia import AsyncLimivia
from limivia.types import LinkKind

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def collect(kind: LinkKind, samples: int) -> None:
    async with AsyncLimivia() as client:
        devices = await client.devices.list(kind=kind)
        if not devices:
            raise RuntimeError("未发现设备")
        async with client.devices.connect(kind=kind, target=devices[0].id) as connection:
            await connection.adc.start(pin=0, interval_ms=200)
            count = 0
            stop_id = None
            async for event in connection:
                sample = None
                if event.type == "adc.start.completed":
                    sample = event.result
                elif event.type == "adc.sample":
                    sample = event.data
                elif event.type == "adc.stop.completed" and event.request_id == stop_id:
                    logger.info("设备已确认停止采样")
                    return
                elif event.type == "command.failed":
                    raise RuntimeError(event.error.message)
                elif event.type == "connection.closed":
                    raise RuntimeError("设备连接已关闭")
                if sample is not None:
                    logger.info("raw=%s，mV=%s", sample.raw, sample.millivolts)
                    count += 1
                    if count >= samples and stop_id is None:
                        stop_id = await connection.adc.stop(pin=0)


def main(
    kind: str = typer.Option("ble", envvar="LIMIVIA_TRANSPORT"),
    samples: int = typer.Option(10, min=1),
) -> None:
    if kind not in ("ble", "usb"):
        raise typer.BadParameter("kind 必须为 ble 或 usb")
    asyncio.run(collect("ble" if kind == "ble" else "usb", samples))


if __name__ == "__main__":
    typer.run(main)
