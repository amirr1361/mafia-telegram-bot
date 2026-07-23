"""بازگشت از مراحل اخراج انضباطی در semi_auto."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    CONFIRM_DISCIPLINE_KICK,
    NIGHT_ACTIONS,
    NS_DISCIPLINE_ASK,
    PICK_DISCIPLINE_KICK,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def make_semi_auto_game() -> Game:
    game = Game(
        room_code="77",
        host_id=1,
        scenario_name="bazpors",
        players={
            -1: _p(-1, 1, "رییس", Role.MAFIA_BOSS),
            -2: _p(-2, 2, "شهروند", Role.CITIZEN),
        },
        max_players=12,
    )
    game.bazpors_host_mode = "semi_auto"
    game.bazpors_narrator_enabled = True
    game.bazpors_narrator_night_count = 1
    game.bazpors_night_step_history = [NS_DISCIPLINE_ASK]
    return game


class DisciplineNightBackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_night_back_from_discipline_pick_returns_to_ask(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = PICK_DISCIPLINE_KICK
        game.bazpors_night_substep = NS_DISCIPLINE_ASK

        err = process_narrator_callback(game, self.gm, "night_back", 0, "")

        self.assertIsNone(err)
        self.assertEqual(game.bazpors_narrator_step, NIGHT_ACTIONS)
        self.assertEqual(game.bazpors_night_substep, NS_DISCIPLINE_ASK)

    def test_night_back_from_discipline_confirm_returns_to_pick(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = CONFIRM_DISCIPLINE_KICK
        game.bazpors_narrator_pending_uid = -2
        game.bazpors_night_substep = NS_DISCIPLINE_ASK

        err = process_narrator_callback(game, self.gm, "night_back", 0, "")

        self.assertIsNone(err)
        self.assertEqual(game.bazpors_narrator_step, PICK_DISCIPLINE_KICK)
        self.assertIsNone(game.bazpors_narrator_pending_uid)


if __name__ == "__main__":
    unittest.main()
