"""ارسال موازی با سقف همزمانی — برای broadcast به چند chat_id تلگرام."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

DEFAULT_BROADCAST_CONCURRENCY = 5


async def gather_bounded(
    items: list[T],
    coro: Callable[[T], Awaitable[None]],
    *,
    limit: int = DEFAULT_BROADCAST_CONCURRENCY,
) -> None:
    """هر item را با حداکثر ``limit`` coroutine همزمان اجرا می‌کند."""
    if not items:
        return
    sem = asyncio.Semaphore(limit)

    async def _one(item: T) -> None:
        async with sem:
            await coro(item)

    await asyncio.gather(*(_one(item) for item in items))
