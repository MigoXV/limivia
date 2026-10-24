from limivia import Limivia, Pins, TransportKind

from .._common import run


def main():
    """UART 内部回环：写入字节、等待发送排空，再读取字节。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        with board.uart.open(tx=Pins.GPIO20, rx=Pins.GPIO21, loopback=True) as uart:
            uart.write(b"hello")
            uart.drain()
            print(uart.read(5))


if __name__ == "__main__":
    run(main)
