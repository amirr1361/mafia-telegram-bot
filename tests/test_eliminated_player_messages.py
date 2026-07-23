"""پیام حذف و قطع ارسال برای بازیکنان خارج‌شده."""

from __future__ import annotations

import unittest

from bot.models import Phase, Player, Role
from bot.game import GameManager
from bot.observer_delivery import (
    ELIMINATED_PLAYER_MESSAGE_HTML,
    player_should_receive_game_messages,
    queue_player_elimination_notify,
)


class EliminatedPlayerMessagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_dead_player_does_not_receive_messages(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=20, full_name="B", username=None)
        )
        game.bot_assistant_user_id = 10
        game.observer_user_id = 30
        game.players[20].is_alive = False
        self.assertFalse(player_should_receive_game_messages(game, 20))
        self.assertTrue(player_should_receive_game_messages(game, 10))
        self.assertTrue(player_should_receive_game_messages(game, 30))

    def test_assistant_still_receives_when_dead_seat(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        game.bot_assistant_user_id = 10
        game.players[10].is_alive = False
        self.assertTrue(player_should_receive_game_messages(game, 10))

    def test_queue_skips_observer_only(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 10
        game.observer_user_id = 30
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=99, full_name="C", username=None)
        )
        queue_player_elimination_notify(game, 10)
        queue_player_elimination_notify(game, 30)
        queue_player_elimination_notify(game, 99)
        self.assertEqual(game.eliminated_notify_uids, [10, 99])

    def test_assistant_still_receives_panels_when_dead(self) -> None:
        """پیام حذف نباید پنل کمک‌کننده را قطع کند — فقط queue/notify جداست."""
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 10
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        game.players[10].is_alive = False
        game.no_host_assistant_narrator_active = True
        self.assertTrue(player_should_receive_game_messages(game, 10))

    def test_elimination_message_text(self) -> None:
        self.assertIn("شما از بازی خارج شدید", ELIMINATED_PLAYER_MESSAGE_HTML)


if __name__ == "__main__":
    unittest.main()
