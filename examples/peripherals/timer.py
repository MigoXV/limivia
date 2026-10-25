from time import sleep

from limivia import Limivia, Pins, TransportKind
from limivia.constants import PeripheralKind

from .._common import run


def main():
    """在板上定时翻转 GPIO13；退出时等待定时器资源释放。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.resources.open(
            PeripheralKind.TIMER,
            pins={"pin": Pins.LED},
            config={"high_ms": 100, "low_ms": 100, "count": 5},
        ):
            sleep(1.2)


if __name__ == "__main__":
    run(main)
