from time import sleep

from limivia import Level, Limivia, Pins, TransportKind

from .._common import run


def main():
    """同步闪烁 GPIO13 五次，每次写入等待设备确认。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.gpio.output(Pins.LED, value=Level.LOW) as led:
            for _ in range(5):
                led.write(Level.HIGH)
                sleep(0.5)
                led.write(Level.LOW)
                sleep(0.5)


if __name__ == "__main__":
    run(main)
