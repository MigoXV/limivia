from limivia import AsyncLimivia, TransportKind

from .._common import run


async def main():
    """异步读取唯一 USB 板卡的一致状态快照。"""
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        print((await board.state.snapshot()).to_json())


if __name__ == "__main__":
    run(main)
