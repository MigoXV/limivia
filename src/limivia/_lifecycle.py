"""有界清理：保留原异常，原始取消不能打断已开始的资源释放。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from ._exceptions import ResourceCleanupError


def record_cleanup(original: BaseException, error: BaseException) -> None:
    errors = getattr(original, "cleanup_errors", None)
    if errors is None:
        errors = []
        original.cleanup_errors = errors  # type: ignore[attr-defined]
    if error not in errors:
        original.add_note(f"另有清理失败：{type(error).__name__}: {error}")
        errors.append(error)


async def cleanup(
    work: Coroutine[Any, Any, Any],
    original: BaseException | None,
    timeout: float,
) -> None:
    task = asyncio.create_task(work, name="limivia-resource-cleanup")
    deadline = asyncio.get_running_loop().time() + timeout
    cancellation: asyncio.CancelledError | None = None
    try:
        while True:
            remaining = max(0, deadline - asyncio.get_running_loop().time())
            try:
                await asyncio.wait_for(asyncio.shield(task), remaining)
                break
            except asyncio.CancelledError as exc:
                if task.cancelled():
                    raise ResourceCleanupError("资源清理任务被取消，释放状态未知") from exc
                cancellation = exc
    except Exception as exc:  # noqa: BLE001 -- preserve the primary exception
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        error = (
            exc
            if isinstance(exc, ResourceCleanupError)
            else ResourceCleanupError(
                "资源清理未确认",
                may_have_executed=True,
            )
        )
        if error is not exc:
            error.__cause__ = exc
        primary = original or cancellation
        if primary is None:
            raise error
        record_cleanup(primary, error)
    if cancellation is not None and original is None:
        raise cancellation
