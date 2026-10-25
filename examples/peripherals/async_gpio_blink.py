import asyncio

from limivia import AsyncLimivia, Level, Pins, TransportKind

from .._common import run


async def main():
    """异步闪烁 GPIO13 五次，等待设备时不阻塞事件循环。"""
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        async with board.gpio.output(Pins.LED, value=Level.LOW) as led:
            for _ in range(5):
                await led.write(Level.HIGH)
                await asyncio.sleep(0.5)
                await led.write(Level.LOW)
                await asyncio.sleep(0.5)


if __name__ == "__main__":
    run(main)
