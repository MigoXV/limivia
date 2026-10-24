from limivia import Level, Limivia, Pins, TransportKind

from .._common import run


def main():
    """点亮唯一 USB 板卡的 GPIO13，按回车后熄灭并释放。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.gpio.output(Pins.LED, value=Level.HIGH) as led:
            input("灯已亮，按回车熄灭…")
            led.write(Level.LOW)


if __name__ == "__main__":
    run(main)
