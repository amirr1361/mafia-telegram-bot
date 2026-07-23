"""همگانی انتظار یاکوزایی — غیرمافیا و آینهٔ ناظر."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.models import Player, Role
from bot.no_host_mafia_yaku import _broadcast_yaku_wait_to_non_mafia


class NoHostYakuBroadcastTest(unittest.IsolatedAsyncioTestCase):
    async def test_non_mafia_synthetic_mirrored_to_observer(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=100, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game,
            Player(user_id=50, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        gm.fill_bazpors_no_host_synthetic_lobby(game)
        game.observer_user_id = 999
        game.observer_prompt_status = "registered"

        bot = AsyncMock()
        with patch(
            "bot.no_host_mafia_yaku.broadcast_to_alive_non_mafia_players",
            new_callable=AsyncMock,
        ) as broadcast:
            await _broadcast_yaku_wait_to_non_mafia(bot, game)
            broadcast.assert_awaited_once()
            self.assertIn("یاکوزایی", broadcast.await_args.args[2])
            self.assertIs(
                broadcast.await_args.kwargs.get("is_synthetic_uid"),
                is_synthetic_player_uid,
            )


if __name__ == "__main__":
    unittest.main()
