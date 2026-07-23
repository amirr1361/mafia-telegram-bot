"""به‌تعویق اعلام برد تا پایان جمع‌آوری موازی شب (یاکوزا/ناتو)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_mafia_win import mafia_faction_wins, no_host_maybe_end_on_faction_win
from bot.no_host_night_ready import defer_no_host_faction_win_until_night_complete


def _no_host_parallel_game(*, night_count: int = 2) -> Game:
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 99
    game.no_host_assistant_narrator_active = True
    game.no_host_night_parallel_collect_active = True
    game.bazpors_narrator_step = "night_start"
    game.bazpors_narrator_night_count = night_count
    game.no_host_mafia_yaku_done = False
    game.no_host_doctor_pick_confirmed = False
    game.no_host_interrog_pick_confirmed = False
    return game


class DeferFactionWinParallelNightTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.bot = MagicMock()

    async def test_defer_while_parallel_collect_active(self) -> None:
        game = _no_host_parallel_game()
        self.assertTrue(defer_no_host_faction_win_until_night_complete(game))
        with patch(
            "bot.no_host_mafia_win.no_host_broadcast_mafia_win_and_finalize",
            new_callable=AsyncMock,
        ) as win_broadcast:
            ended = await no_host_maybe_end_on_faction_win(self.bot, game, self.gm)
        self.assertFalse(ended)
        win_broadcast.assert_not_awaited()

    async def test_win_after_parallel_collect_finished(self) -> None:
        game = _no_host_parallel_game()
        game.no_host_night_parallel_collect_active = False
        gm = self.gm
        gm.add_player(
            game,
            Player(-1, "M1", None, Role.MAFIA_BOSS, seat=1, is_alive=True),
        )
        gm.add_player(
            game,
            Player(-2, "M2", None, Role.NATO, seat=2, is_alive=True),
        )
        gm.add_player(
            game, Player(-3, "C1", None, Role.CITIZEN, seat=3, is_alive=True)
        )
        self.assertTrue(mafia_faction_wins(game, gm))
        with patch(
            "bot.no_host_mafia_win.no_host_broadcast_mafia_win_and_finalize",
            new_callable=AsyncMock,
        ) as win_broadcast:
            ended = await no_host_maybe_end_on_faction_win(self.bot, game, gm)
        self.assertTrue(ended)
        win_broadcast.assert_awaited_once()

    async def test_yaku_finalize_keeps_night_open_when_others_pending(self) -> None:
        from bot.no_host_mafia_yaku import _finalize_yaku_flow
        from bot.no_host_night_ready import all_no_host_parallel_night_ready

        game = _no_host_parallel_game()
        gm = self.gm
        gm.add_player(
            game,
            Player(-1, "Boss", None, Role.MAFIA_BOSS, seat=1, is_alive=True),
        )
        gm.add_player(
            game, Player(-2, "Sac", None, Role.MAFIA_BASIC, seat=2, is_alive=True)
        )
        gm.add_player(
            game, Player(-3, "Doc", None, Role.DOCTOR, seat=3, is_alive=True)
        )
        gm.add_player(
            game,
            Player(-4, "Int", None, Role.INTERROGATOR, seat=4, is_alive=True),
        )
        gm.add_player(
            game, Player(-5, "Kaveh", None, Role.CITIZEN, seat=5, is_alive=True)
        )
        gm.add_player(
            game, Player(-6, "C2", None, Role.CITIZEN, seat=6, is_alive=True)
        )
        game.mafia_ids = {-1, -2}

        game.no_host_mafia_yaku_flow_active = True
        game.no_host_mafia_yaku_done = False
        game.no_host_doctor_pick_confirmed = False
        game.no_host_interrog_pick_confirmed = False
        game.no_host_citizen_night_confirmed_uids = []

        with patch(
            "bot.no_host_mafia_yaku._notify_converted_player",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_yaku._notify_mafia_outcome",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.push_host_step",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_win.no_host_broadcast_mafia_win_and_finalize",
            new_callable=AsyncMock,
        ) as win_broadcast:
            await _finalize_yaku_flow(
                self.bot,
                game,
                gm,
                mafia_uid=-1,
                actor_uid=-1,
                sac_uid=-2,
                civ_uid=-5,
            )

        win_broadcast.assert_not_awaited()
        self.assertTrue(game.no_host_night_parallel_collect_active)
        self.assertFalse(all_no_host_parallel_night_ready(game))


if __name__ == "__main__":
    unittest.main()
