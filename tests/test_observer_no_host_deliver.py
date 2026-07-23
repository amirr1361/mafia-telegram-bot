"""deliver_no_host_player_game_copy و آینهٔ حذف برای ناظر."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.models import Player, Role
from bot.observer_delivery import (
    deliver_no_host_player_game_copy,
    notify_eliminated_player,
)


class ObserverNoHostDeliverTest(unittest.IsolatedAsyncioTestCase):
    async def test_dead_player_gets_observer_mirror_only(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=100, full_name="A", username=None, role=Role.CITIZEN)
        )
        gm.add_player(
            game,
            Player(
                user_id=200,
                full_name="B",
                username=None,
                role=Role.CITIZEN,
                is_alive=False,
            ),
        )
        game.observer_prompt_status = "registered"
        game.observer_user_id = 300

        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            await deliver_no_host_player_game_copy(
                bot,
                game,
                200,
                "همگانی تست",
                is_synthetic_uid=is_synthetic_player_uid,
                parse_mode="HTML",
            )
            uids = [c.args[1] for c in send.call_args_list]
            self.assertNotIn(200, uids)
            self.assertIn(300, uids)

    async def test_elimination_notify_sends_mirror_to_observer(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=200, full_name="B", username=None, role=Role.CITIZEN)
        )
        game.observer_prompt_status = "registered"
        game.observer_user_id = 300

        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            await notify_eliminated_player(bot, game, 200)
            uids = [c.args[1] for c in send.call_args_list]
            self.assertIn(200, uids)
            self.assertIn(300, uids)
            self.assertGreaterEqual(len(send.call_args_list), 2)

    async def test_intro_night_civilian_message_to_observer(self) -> None:
        from bot.main import deliver_no_host_intro_night_started_messages

        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(
                user_id=100,
                full_name="A",
                username=None,
                role=Role.CITIZEN,
                is_alive=True,
            ),
        )
        game.observer_prompt_status = "registered"
        game.observer_user_id = 300

        bot = AsyncMock()
        with patch(
            "bot.main.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            await deliver_no_host_intro_night_started_messages(bot, game)
            uids = [c.args[1] for c in send.call_args_list]
            self.assertIn(100, uids)
            self.assertIn(300, uids)
            obs_text = next(c.args[2] for c in send.call_args_list if c.args[1] == 300)
            self.assertIn("شب معارفه آغاز شد", obs_text)


if __name__ == "__main__":
    unittest.main()
