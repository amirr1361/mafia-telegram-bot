"""همگانی no_host: ناظر به‌ازای هر صندلی (شامل بات مصنوعی) یک نسخه می‌گیرد."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.models import Player
from bot.observer_delivery import broadcast_to_players


class ObserverBroadcastSeatsTest(unittest.IsolatedAsyncioTestCase):
    async def test_observer_gets_one_copy_per_seat_including_synthetic(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=100, full_name="Real", username=None)
        )
        gm.fill_bazpors_no_host_synthetic_lobby(game)
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        game.bot_assistant_user_id = 100

        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            await broadcast_to_players(
                bot,
                game,
                "test broadcast",
                exclude=100,
                is_synthetic_uid=is_synthetic_player_uid,
            )
            obs_messages = [
                c
                for c in send.call_args_list
                if c.args and c.args[1] == 999
            ]
            self.assertEqual(len(obs_messages), len(game.players) - 1)
            for call in obs_messages:
                self.assertIn("ناظر — پیام صندلی", call.args[2])


if __name__ == "__main__":
    unittest.main()
