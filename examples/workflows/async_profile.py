from limivia import AsyncLimivia, Pins, TransportKind
from limivia.constants import PeripheralKind, ResourceAction

from .._common import run


async def main():
    """高级示例：按实际能力选择 UART 内部回环或片内温度，只释放自有资源。"""
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        discovery = await board.discover()
        print(discovery.identity.to_json())
        available = {resource.kind for resource in discovery.resources if resource.available}
        if PeripheralKind.UART in available:
            async with board.uart.open(tx=Pins.GPIO20, rx=Pins.GPIO21, loopback=True) as uart:
                await uart.write(b"hello")
                await uart.drain()
                print(await uart.read(5))
        elif PeripheralKind.TEMPERATURE in available:
            async with board.resources.open(
                PeripheralKind.TEMPERATURE, pins={}, config={}
            ) as sensor:
                print((await sensor.call(ResourceAction.READ)).to_json())
        else:
            raise RuntimeError("没有适用的演示能力")


if __name__ == "__main__":
    run(main)
