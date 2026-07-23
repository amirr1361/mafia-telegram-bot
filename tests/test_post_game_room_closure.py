"""بستن اتاق و آزادسازی نگاشت‌ها پس از اتمام مدال‌ها."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot import db
from bot.game import GameManager


class PostGameRoomClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test.sqlite3"
        self._patch = mock.patch(
            "bot.config.get_database_path", return_value=self._db_path
        )
        self._patch.start()
        db.init_db()
        self.manager = GameManager()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_force_release_clears_host_and_real_players(self) -> None:
        game = self.manager.create_game(
            host_id=108214166,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        from bot.models import Player

        self.manager.add_player(
            game,
            Player(
                user_id=108214166,
                full_name="Host",
                username=None,
            ),
        )
        self.manager.player_to_room[108214166] = game.room_code
        synth = -920001
        game.players[synth] = Player(
            user_id=synth, full_name="Bot", username=None
        )

        self.manager.force_release_ended_session(
            game.room_code,
            108214166,
            {108214166, synth},
            observer_user_id=8553283735,
        )
        self.assertIsNone(self.manager.get_game(game.room_code))
        self.assertIsNone(self.manager.get_room_for_host(108214166))
        self.assertIsNone(self.manager.get_room_for_user(108214166))
        self.assertIsNone(self.manager.observer_to_room.get(8553283735))


if __name__ == "__main__":
    unittest.main()
