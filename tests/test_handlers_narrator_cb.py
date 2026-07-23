"""تست ثبت router narrator_cb (فاز ۲)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from aiogram import Dispatcher

from bot.handlers.narrator_cb import (
    _assistant_panel_in_place,
    _handle_ki_as_win,
    _handle_tie_citizen,
    register_narrator_cb_handlers,
    router,
)


class NarratorCbRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def test_router_name(self) -> None:
        self.assertEqual(router.name, "narrator_cb")

    def test_register_attaches_router(self) -> None:
        if router.parent_router is not None:
            self.assertEqual(router.name, "narrator_cb")
            return
        dp = Dispatcher()
        register_narrator_cb_handlers(dp)
        names = [r.name for r in dp.sub_routers]
        self.assertIn("narrator_cb", names)

    async def test_ki_as_win_blocks_no_host_handshake_path(self) -> None:
        from bot.game import GameManager

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            host_full_name="h",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        handled = await _handle_ki_as_win(MagicMock(), cb, game, "ki_as_mafia_win")
        self.assertTrue(handled)
        cb.answer.assert_awaited_once()

    async def test_tie_citizen_invalid_step(self) -> None:
        from bot.game import GameManager

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            host_full_name="h",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_step = "day_discuss"
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        handled = await _handle_tie_citizen(MagicMock(), cb, game, "tie_citizen_yes")
        self.assertTrue(handled)


class AssistantPanelInPlaceTests(unittest.TestCase):
    def test_false_when_not_no_host_assistant(self) -> None:
        from bot.game import GameManager

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            host_full_name="h",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        cb = MagicMock()
        cb.message = MagicMock()
        self.assertFalse(
            _assistant_panel_in_place(game, cb, "disc_ok", game.bazpors_narrator_step)
        )


if __name__ == "__main__":
    unittest.main()
