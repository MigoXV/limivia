"""只读事件观察：一个消费者分发给展示和统计，命令结果按 ID 关联。"""

import asyncio
import logging
from collections import Counter

import typer

from limivia import AsyncLimivia
from limivia.types import DeviceEvent, HelloCommand, LinkKind, StateCommandParam

from ._common import Kind, KindOption, TargetOption, command_line, select_device

logger = logging.getLogger(__name__)


def display(event: DeviceEvent) -> None:
    """第一个订阅者：按 type 收窄后展示数据；不读取连接。"""
    if event.type == "hello.completed":
        logger.info("hello #%s：%s", event.request_id, event.result.name)
    elif event.type == "state.completed":
        logger.info("state #%s：%s", event.request_id, event.result.to_json())
    elif event.type == "state.changed":
        logger.info("状态版本变化：%s（通知不是完整状态）", event.revision)
    elif event.type == "adc.sample":
        logger.info("观察到 ADC 通知：%s", event.data.to_json())
    elif event.type == "protocol.error":
        logger.warning("协议帧异常：%s", event.message)
    elif event.type == "unknown":
        logger.info("未建模通知：%s", event.raw)
    elif event.type == "command.failed":
        logger.error("%s #%s：%s", event.op, event.request_id, event.error.to_json())
    elif event.type == "connection.closed":
        logger.info("连接关闭：%s", event.error)


def count_event(event: DeviceEvent, counts: Counter[str]) -> None:
    """第二个订阅者：独立统计；仍不读取连接。"""
    counts[event.type] += 1


async def run(
    client: AsyncLimivia,
    *,
    kind: LinkKind = "ble",
    target: str | None = None,
    duration: float = 10,
) -> None:
    if duration <= 0:
        raise ValueError("duration 必须大于零。")
    devices = await client.devices.list(kind=kind)
    target = select_device(devices, target)
    counts: Counter[str] = Counter()
    async with client.devices.connect(kind=kind, target=target) as connection:
        # 两种公开命令输入形式；返回 ID 并不代表已经执行。
        hello_id = await connection.send(HelloCommand())
        state_command: StateCommandParam = {"type": "state", "params": {}}
        initial_state_id = await connection.send(state_command)
        state_id: int | None = initial_state_id
        pending = {connection.handshake_request_id, hello_id, initial_state_id}
        refresh_needed = False
        deadline = asyncio.get_running_loop().time() + duration
        try:
            while True:
                # 只有这一处消费事件；观察时长到期只取消等待，不创建第二个消费者。
                try:
                    async with asyncio.timeout_at(deadline):
                        event = await connection.recv()
                except TimeoutError:
                    logger.info("观察时长已到，尚未收到结果的只读请求=%s", sorted(pending))
                    break
                except StopAsyncIteration:
                    raise RuntimeError("事件流提前结束。") from None
                display(event)
                count_event(event, counts)

                if event.type == "hello.completed" and event.request_id in pending:
                    pending.remove(event.request_id)
                elif event.type == "state.changed":
                    refresh_needed = True
                elif event.type == "state.completed" and event.request_id == state_id:
                    pending.discard(event.request_id)
                    state_id = None
                elif event.type == "command.failed" and event.request_id in pending:
                    raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
                elif event.type == "connection.closed":
                    raise RuntimeError(f"观察期间连接已关闭：{event.error}")

                # 合并连续 changed 通知，始终至多一个状态查询在等待结果。
                if refresh_needed and state_id is None:
                    state_id = await connection.state.retrieve()
                    pending.add(state_id)
                    refresh_needed = False
        finally:
            logger.info("事件计数：%s", dict(counts))


async def main_async(kind: Kind, target: str | None, duration: float) -> None:
    async with AsyncLimivia() as client:
        await run(client, kind=kind.link, target=target, duration=duration)


def main(
    kind: KindOption = Kind.ble,
    target: TargetOption = None,
    duration: float = typer.Option(10, min=0.1, help="只读观察时长，秒"),
) -> None:
    """只读观察事件并分发，结束后不会停止设备原有任务。"""
    with command_line():
        asyncio.run(main_async(kind, target, duration))


if __name__ == "__main__":
    typer.run(main)
