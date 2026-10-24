from time import sleep

from limivia import Limivia, Pins, TransportKind

from .._common import run


def main():
    """在 GPIO13 输出 1kHz、25% 占空比的 PWM，然后释放。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.pwm.open(Pins.LED, frequency=1000, duty=25) as pwm:
            sleep(1)
            pwm.set_duty(0)


if __name__ == "__main__":
    run(main)
