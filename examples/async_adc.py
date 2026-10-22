"""流式 ADC：精确计数、采样停滞检测，以及取消时的停止确认。"""

import asyncio
import logging
import sys

import typer
from pydantic import ValidationError

from limivia import AsyncConnection, AsyncLimivia, InvalidCommandError, QueueFullError
from limivia.types import LinkKind

from ._common import Kind, KindOption, PinOption, TargetOption, command_line, select_device

logger = logging.getLogger(__name__)


async def stop_sampling(connection: AsyncConnection, pin: int, timeout: float) -> None:
    """主消费循环退出后接管事件流；停止命令只提交一次。"""
    async with asyncio.timeout(timeout):
        stop_id = await connection.adc.stop(pin=pin)
        async for event in connection:
            if event.type == "adc.stop.completed" and event.request_id == stop_id:
                logger.info("ADC 已确认停止，GPIO%s 已释放", pin)
                return
            if event.type == "command.failed" and event.request_id == stop_id:
                raise RuntimeError(event.error.to_json())
            if event.type == "connection.closed":
                raise RuntimeError(f"连接已关闭：{event.error}")
        raise RuntimeError("未收到 ADC 停止确认。")


async def run(
    client: AsyncLimivia,
    *,
    kind: LinkKind = "ble",
    target: str | None = None,
    pin: int = 0,
    samples: int = 10,
    interval_ms: int = 200,
    idle_timeout: float = 15,
) -> None:
    if samples < 1 or idle_timeout <= 0:
        raise ValueError("samples 和 idle_timeout 必须大于零。")
    devices = await client.devices.list(kind=kind)
    target = select_device(devices, target)
    async with client.devices.connect(kind=kind, target=target) as connection:
        async for event in connection:
            if (
                event.type == "hello.completed"
                and event.request_id == connection.handshake_request_id
            ):
                selected = next((p for p in event.result.state.pins if p.pin == pin), None)
                if selected is None or selected.mode != "idle":
                    raise RuntimeError(f"GPIO{pin} 不可用或已被占用，请检查状态并显式清理。")
                break
            if event.type == "connection.closed":
                raise RuntimeError(f"连接已关闭：{event.error}")
        else:
            raise RuntimeError("未收到握手结果。")

        cleanup_needed = True
        try:
            try:
                start_id = await connection.adc.start(pin=pin, interval_ms=interval_ms)
            except (InvalidCommandError, QueueFullError, ValidationError):
                cleanup_needed = False
                raise
            count = 0
            started = False
            loop = asyncio.get_running_loop()
            # 启动应答使用 SDK 命令超时；收到首次样本后才开始采样空闲计时。
            deadline: float | None = None
            while count < samples:
                try:
                    async with asyncio.timeout_at(deadline):
                        event = await connection.recv()
                except TimeoutError:
                    raise RuntimeError(
                        f"GPIO{pin} 连续 {idle_timeout:g} 秒没有有效样本。"
                    ) from None
                except StopAsyncIteration:
                    raise RuntimeError("事件流提前结束。") from None

                sample = None
                if event.type == "adc.start.completed" and event.request_id == start_id:
                    started = True
                    deadline = loop.time() + idle_timeout
                    sample = event.result
                elif event.type == "adc.sample" and started:
                    sample = event.data
                elif event.type == "command.failed" and event.request_id == start_id:
                    cleanup_needed = event.error.may_have_executed
                    raise RuntimeError(f"{event.op} #{event.request_id}: {event.error.to_json()}")
                elif event.type == "connection.closed":
                    raise RuntimeError(f"连接已关闭：{event.error}")
                elif event.type == "protocol.error":
                    logger.warning("协议帧异常：%s", event.message)

                # 启动响应也是第一个样本。其他引脚通知既不计数，也不延长超时。
                if sample is not None and sample.pin == pin:
                    count += 1
                    deadline = loop.time() + idle_timeout
                    voltage = (
                        f"{sample.millivolts} mV"
                        if sample.millivolts is not None
                        else "未校准／无电压值"
                    )
                    logger.info(
                        "样本 %s/%s：GPIO%s raw=%s，电压=%s，calibrated=%s，设备时间=%s ms",
                        count,
                        samples,
                        pin,
                        sample.raw,
                        voltage,
                        sample.calibrated,
                        sample.uptime_ms,
                    )
        finally:
            if cleanup_needed:
                original_error = sys.exception()
                # 最多等待一个尚未结束的启动命令，再等待停止命令；不无限等待。
                cleanup = asyncio.create_task(
                    stop_sampling(connection, pin, 2 * client.timeout + 1),
                    name="example-adc-stop",
                )
                try:
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        # 正常完成后在清理期间收到首次取消，也要等待停止确认。
                        try:
                            await asyncio.shield(cleanup)
                        except Exception:
                            logger.exception("GPIO%s 停止状态未确认", pin)
                        raise
                except Exception as exc:
                    logger.error("GPIO%s 停止状态未确认：%s", pin, exc)
                    if original_error is None:
                        raise


async def main_async(
    kind: Kind,
    target: str | None,
    pin: int,
    samples: int,
    interval_ms: int,
    idle_timeout: float,
) -> None:
    async with AsyncLimivia() as client:
        await run(
            client,
            kind=kind.link,
            target=target,
            pin=pin,
            samples=samples,
            interval_ms=interval_ms,
            idle_timeout=idle_timeout,
        )


def main(
    kind: KindOption = Kind.ble,
    target: TargetOption = None,
    pin: PinOption = 0,
    samples: int = typer.Option(10, min=1, help="总样本数，包含启动响应中的首次采样"),
    interval_ms: int = typer.Option(200, min=100, max=10000, help="设备采样间隔 ms"),
    idle_timeout: float = typer.Option(15, min=0.1, help="启动后连续无目标引脚样本的超时秒数"),
) -> None:
    """收集指定数量 ADC 样本，结束或首次 Ctrl+C 时等待停止确认。"""
    with command_line():
        asyncio.run(main_async(kind, target, pin, samples, interval_ms, idle_timeout))


if __name__ == "__main__":
    typer.run(main)
