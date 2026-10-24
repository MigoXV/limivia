from limivia import Limivia, TransportKind

from .._common import run


def main():
    """显式停止全部实验并持久禁止流程自启，会影响其他控制来源。"""
    with Limivia.connect(kind=TransportKind.USB) as board:
        print(board.outputs.stop().to_json())


if __name__ == "__main__":
    run(main)
