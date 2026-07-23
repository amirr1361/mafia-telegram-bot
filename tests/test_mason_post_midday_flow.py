"""جریان پس از خواب نیمروزی — سناریوی ماسون (Room 53 style)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import (
    NS_DISCIPLINE_ASK,
    NIGHT_ACTIONS,
    _goto_discipline_ask,
    build_host_message_and_keyboard,
)
from bot.game import GameManager
from bot.mason_game_flow import mason_after_midday_step_confirmed
from bot.mason_helper_flow import handle_mason_helper_action

def _mason_game(gm: GameManager):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.no_host_assistant_narrator_active = True
    return game


def _bazpors_game(gm: GameManager):
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.no_host_assistant_narrator_active = True
    return game


class MasonPostMiddayHostPanelTests(unittest.TestCase):
    def test_room53_discipline_panel_not_hunter_wait(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DISCIPLINE_ASK
        game.bazpors_narrator_night_count = 1
        game.no_host_night1_hunter_done = False
        game.no_host_mafia_night1_done = False

        text, kb = build_host_message_and_keyboard(game, gm)

        self.assertIn("اخراج انضباطی", text)
        self.assertNotIn("هانتر", text)
        self.assertNotIn("تیم مافیا", text)
        self.assertIsNotNone(kb)

    def test_bazpors_night1_still_shows_hunter_wait(self) -> None:
        gm = GameManager()
        game = _bazpors_game(gm)
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_narrator_night_count = 1
        game.no_host_night1_hunter_done = False
        game.no_host_mafia_night1_done = False

        text, _ = build_host_message_and_keyboard(game, gm)

        self.assertIn("هانتر", text)
        self.assertIn("تیم مافیا", text)


class MasonPostMiddayFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_midday_ok_calls_mason_post_midday_route(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_game_flow.mason_after_midday_step_confirmed",
            new=AsyncMock(),
        ) as route:
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="ok",
                kind="midday",
            )

        route.assert_awaited_once_with(bot, game, gm)
        self.assertTrue(game.mason_midday_step_done)

    async def test_mason_after_midday_sets_discipline_and_pushes_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_narrator_night_count = 1
        bot = MagicMock()

        with patch(
            "bot.bazpors_narrator.push_host_step",
            new=AsyncMock(),
        ) as push:
            await mason_after_midday_step_confirmed(bot, game, gm)

        self.assertEqual(game.bazpors_night_substep, NS_DISCIPLINE_ASK)
        push.assert_awaited_once()
        self.assertTrue(push.await_args.kwargs.get("force_new_host_message"))

    async def test_room53_regression_host_panel_after_goto_discipline(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_narrator_night_count = 1
        game.no_host_night1_hunter_done = False
        game.no_host_mafia_night1_done = False
        _goto_discipline_ask(game)

        text, _ = build_host_message_and_keyboard(game, gm)

        self.assertEqual(game.bazpors_night_substep, NS_DISCIPLINE_ASK)
        self.assertIn("اخراج انضباطی", text)
        self.assertNotIn("در انتظار ثبت انتخاب‌های هانتر", text)
