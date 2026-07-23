"""جملهٔ بزرگان در شروع شب — بدون گرداننده."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.data.no_host_sage_quotes import SAGE_QUOTES
from bot.models import Player, Role
from bot.no_host_night_sage_quote import (
    alive_no_host_night_sage_recipient_uids,
    alive_synthetic_no_host_night_sage_uids,
    build_no_host_night_sage_quote_html,
    dispatch_no_host_night_sage_quotes_at_entry,
    resync_observer_night_sage_quotes,
)


class NoHostNightSageQuoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert self.game is not None
        self.game.bazpors_narrator_night_count = 2

    def test_quote_pool_has_one_thousand(self) -> None:
        self.assertEqual(len(SAGE_QUOTES), 1000)

    def test_html_has_header_and_quote(self) -> None:
        html = build_no_host_night_sage_quote_html(self.game, 100)
        self.assertIn("یه جمله از بزرگان", html)
        self.assertIn("—", html)

    def test_different_players_usually_get_different_quotes(self) -> None:
        q1 = build_no_host_night_sage_quote_html(self.game, 101)
        q2 = build_no_host_night_sage_quote_html(self.game, 202)
        self.assertNotEqual(q1, q2)

    def test_alive_recipients_includes_all_living_seats(self) -> None:
        game = self.game
        game.players[10] = Player(user_id=10, full_name="A", username=None, role=Role.DOCTOR)
        game.players[10].is_alive = True
        game.players[10].seat = 3
        game.players[20] = Player(user_id=20, full_name="B", username=None, role=Role.CITIZEN)
        game.players[20].is_alive = False
        uids = alive_no_host_night_sage_recipient_uids(game)
        self.assertIn(10, uids)
        self.assertNotIn(20, uids)

    def test_dispatch_at_entry_sends_once_per_alive_player(self) -> None:
        game = self.game
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 1
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.players[100] = Player(
            user_id=100, full_name="Cit", username=None, role=Role.CITIZEN
        )
        game.players[100].is_alive = True
        game.players[200] = Player(
            user_id=200, full_name="Doc", username=None, role=Role.DOCTOR
        )
        game.players[200].is_alive = True

        async def _run() -> None:
            bot = AsyncMock()
            with patch(
                "bot.no_host_night_sage_quote.send_no_host_night_sage_quote",
                new_callable=AsyncMock,
            ) as send_mock:
                await dispatch_no_host_night_sage_quotes_at_entry(bot, game)
                self.assertEqual(send_mock.await_count, 2)
                called_uids = {c.args[2] for c in send_mock.await_args_list}
                self.assertEqual(called_uids, {100, 200})
                send_mock.reset_mock()
                await dispatch_no_host_night_sage_quotes_at_entry(bot, game)
                send_mock.assert_not_awaited()

        import asyncio

        asyncio.run(_run())

    def test_dispatch_marks_observer_resync_for_synthetic_seats(self) -> None:
        game = self.game
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 1
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.players[100] = Player(
            user_id=100, full_name="Sh", username=None, role=Role.SHIAD
        )
        game.players[100].is_alive = True
        game.players[-920001] = Player(
            user_id=-920001, full_name="Boss", username=None, role=Role.MAFIA_BOSS
        )
        game.players[-920001].is_alive = True

        async def _run() -> None:
            bot = AsyncMock()
            with patch(
                "bot.no_host_night_sage_quote.send_no_host_night_sage_quote",
                new_callable=AsyncMock,
            ) as send_mock:
                await dispatch_no_host_night_sage_quotes_at_entry(bot, game)
                self.assertTrue(game.no_host_sage_needs_observer_resync)
                called = {c.args[2] for c in send_mock.await_args_list}
                self.assertIn(100, called)
                self.assertIn(-920001, called)

        import asyncio

        asyncio.run(_run())

    def test_resync_sends_sage_mirrors_for_synthetic_mafia(self) -> None:
        game = self.game
        game.bazpors_narrator_night_count = 1
        game.no_host_night_sage_dispatched_night = 1
        game.no_host_sage_needs_observer_resync = True
        game.observer_user_id = 500
        game.observer_prompt_status = "registered"
        game.players[-920003] = Player(
            user_id=-920003, full_name="Shiad", username=None, role=Role.SHIAD
        )
        game.players[-920003].is_alive = True
        game.players[-920008] = Player(
            user_id=-920008, full_name="Boss", username=None, role=Role.MAFIA_BOSS
        )
        game.players[-920008].is_alive = True
        game.players[100] = Player(
            user_id=100, full_name="Human", username=None, role=Role.CITIZEN
        )
        game.players[100].is_alive = True

        async def _run() -> None:
            bot = AsyncMock()
            with patch(
                "bot.no_host_night_sage_quote.send_no_host_night_sage_quote",
                new_callable=AsyncMock,
            ) as send_mock:
                await resync_observer_night_sage_quotes(bot, game)
                self.assertFalse(game.no_host_sage_needs_observer_resync)
                called = {c.args[2] for c in send_mock.await_args_list}
                self.assertEqual(called, {-920003, -920008})

        import asyncio

        asyncio.run(_run())

    def test_synthetic_recipients_includes_mafia_roles(self) -> None:
        game = self.game
        game.players[-920003] = Player(
            user_id=-920003, full_name="Sh", username=None, role=Role.SHIAD
        )
        game.players[-920003].is_alive = True
        game.players[-920005] = Player(
            user_id=-920005, full_name="N", username=None, role=Role.NATO
        )
        game.players[-920005].is_alive = True
        uids = alive_synthetic_no_host_night_sage_uids(game)
        self.assertEqual(uids, [-920005, -920003])


if __name__ == "__main__":
    unittest.main()
