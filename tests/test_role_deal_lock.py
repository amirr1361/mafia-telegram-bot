"""قفل پخش نقش — جلوگیری از دوبار کلیک روی «پخش نقش‌های تصادفی»."""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from bot.game import GameManager
from bot.main import ROLE_DEAL_IN_PROGRESS_MSG, _ROLE_DEAL_LOCKS, deal_roles_full_pipeline
from bot.models import Phase, Player, Role


class RoleDealLockTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.manager = GameManager()
        self.game = self.manager.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="manual",
        )
        assert self.game is not None
        for i in range(10):
            uid = 100 + i
            self.manager.add_player(
                self.game,
                Player(user_id=uid, full_name=f"P{i}", username=None),
            )
        self.game.seats_finalized = True
        for seat, uid in enumerate(sorted(self.game.players), start=1):
            self.game.players[uid].seat = seat
        _ROLE_DEAL_LOCKS.pop(self.game.room_code, None)

    async def test_returns_wait_when_lock_already_held(self) -> None:
        lock = _ROLE_DEAL_LOCKS.setdefault(self.game.room_code, asyncio.Lock())
        await lock.acquire()
        try:
            err = await deal_roles_full_pipeline(mock.AsyncMock(), self.game)
        finally:
            lock.release()
        self.assertEqual(err, ROLE_DEAL_IN_PROGRESS_MSG)

    async def test_second_pipeline_after_roles_dealt(self) -> None:
        self.game.roles_dealt = True
        err = await deal_roles_full_pipeline(mock.AsyncMock(), self.game)
        self.assertEqual(err, "نقش‌ها قبلاً پخش شده‌اند.")


if __name__ == "__main__":
    unittest.main()
