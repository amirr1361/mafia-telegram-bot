"""تست gather_bounded."""

from __future__ import annotations

import asyncio
import unittest

from bot.async_broadcast import gather_bounded


class GatherBoundedTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_all_items_with_concurrency_cap(self) -> None:
        seen: list[int] = []
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def work(n: int) -> None:
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            seen.append(n)
            async with lock:
                active -= 1

        await gather_bounded(list(range(8)), work, limit=3)
        self.assertEqual(sorted(seen), list(range(8)))
        self.assertLessEqual(peak, 3)


if __name__ == "__main__":
    unittest.main()
