"""هانتر — پنل انتخاب در شب ۲ و بعد."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_night_ready import _hunter_night1_ready


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


class NoHostHunterNight2Test(unittest.TestCase):
    def test_hunter_required_on_night_two_until_done(self) -> None:
        game = Game(
            room_code="55",
            host_id=1,
            scenario_name="bazpors",
            bazpors_host_mode="no_host",
            no_host_assistant_narrator_active=True,
            bazpors_narrator_night_count=2,
            players={
                -1: _p(-1, 1, "هانتر", Role.HUNTER),
                -2: _p(-2, 2, "شهروند", Role.CITIZEN),
            },
            max_players=12,
        )
        self.assertFalse(_hunter_night1_ready(game))
        game.no_host_night1_hunter_done = True
        self.assertTrue(_hunter_night1_ready(game))


if __name__ == "__main__":
    unittest.main()
