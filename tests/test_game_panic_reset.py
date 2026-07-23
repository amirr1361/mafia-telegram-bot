"""حافظهٔ GameManager — بازنشانی اضطراری."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Phase, Player, Role


class GamePanicResetTests(unittest.TestCase):
    def test_reset_all_games_clears_maps(self) -> None:
        gm = GameManager()
        game = Game(
            room_code="42",
            host_id=100,
            scenario_name="bazpors",
            players={
                200: Player(200, "P", None, Role.CITIZEN, seat=1),
            },
        )
        game.phase = Phase.MANUAL
        gm.games["42"] = game
        gm.player_to_room[200] = "42"
        gm.host_to_room[100] = "42"
        game.observer_user_id = 300
        gm.observer_to_room[300] = "42"
        n = gm.reset_all_games()
        self.assertEqual(n, 1)
        self.assertEqual(len(gm.games), 0)
        self.assertEqual(len(gm.player_to_room), 0)
        self.assertEqual(len(gm.host_to_room), 0)
        self.assertEqual(len(gm.observer_to_room), 0)


if __name__ == "__main__":
    unittest.main()
