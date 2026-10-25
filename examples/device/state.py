from limivia import Limivia, TransportKind

from .._common import run


def main():
    """同步读取唯一 USB 板卡的一致状态快照。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        print(board.state.snapshot().to_json())


if __name__ == "__main__":
    run(main)
