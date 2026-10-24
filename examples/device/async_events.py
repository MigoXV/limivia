import asyncio

from limivia import AsyncLimivia, TransportKind
from limivia.constants import NotificationTopic

from .._common import run


async def main():
    """订阅设备通知两秒；通知与业务等待独立分发。"""
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        async with board.notifications.subscribe(
            topics=[NotificationTopic.JOB, NotificationTopic.RESOURCE, NotificationTopic.DATA]
        ) as updates:
            try:
                async with asyncio.timeout(2):
                    async for event in updates:
                        print(event.to_json())
            except TimeoutError:
                pass


if __name__ == "__main__":
    run(main)
