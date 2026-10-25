from limivia import Limivia, Pins, TransportKind

from .._common import run


def main():
    """读取 GPIO0 的 ADC 原始值与可用的校准电压。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.adc.open(Pins.GPIO0) as adc:
            print(adc.read().to_json())


if __name__ == "__main__":
    run(main)
