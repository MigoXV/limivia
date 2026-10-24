from limivia import Limivia, TransportKind

from .._common import run


def main():
    """读取唯一 USB 板卡的完整能力，不申请控制或停止设备。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        print(board.discover().to_json())


if __name__ == "__main__":
    run(main)
