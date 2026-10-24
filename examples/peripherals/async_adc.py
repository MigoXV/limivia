import asyncio

from limivia import AsyncLimivia, Pins, TransportKind

from .._common import run


async def main():
    """每 100ms 采样 GPIO0，读取三条 SDK 已解码的 ADC 记录。"""
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        async with board.adc.open(Pins.GPIO0, interval_ms=100) as adc:
            remaining = 3
            async with asyncio.timeout(10):
                while remaining:
                    for sample in (await adc.events())[:remaining]:
                        print(sample.to_json())
                        remaining -= 1
                    await asyncio.sleep(0.1)


if __name__ == "__main__":
    run(main)
