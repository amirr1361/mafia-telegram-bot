"""تساوی مافیا/شهروند بعد از اعمال شب — گزارش شب قبل از اعلام تساوی."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    MAFIA_TIE_GATE,
    _finish_resolve_to_extra,
    build_host_message_and_keyboard,
    mafia_citizen_equal,
)
from bot.game import GameManager
from bot.models import Game, Player, Role


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


class MafiaTieNightReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_apply_resolve_tie_shows_night_report_then_tie_notice(self) -> None:
        """۱ مافیا + ۲ شهروند؛ شات یک شهروند → تساوی ۱ به ۱."""
        players = {
            -1: _p(-1, 1, "رییس مافیا", Role.MAFIA_BOSS),
            -2: _p(-2, 2, "شهروند ۱", Role.CITIZEN),
            -3: _p(-3, 3, "شهروند ۲", Role.CITIZEN),
        }
        game = Game(
            room_code="04",
            host_id=1,
            scenario_name="bazpors_salamat_test",
            players=players,
        )
        game.mafia_ids = {-1}
        game.bazpors_narrator_night_count = 1
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -3
        game.bazpors_alive_at_night_start = {uid: True for uid in players}

        _finish_resolve_to_extra(game, self.gm)

        self.assertEqual(game.bazpors_narrator_step, MAFIA_TIE_GATE)
        self.assertTrue(game.bazpors_mafia_tie_after_night_report)
        self.assertTrue(mafia_citizen_equal(game, self.gm))
        self.assertFalse(players[-3].is_alive)
        self.assertIn("گزارش", game.bazpors_night_report_html or "")

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("گزارش", body)
        self.assertIn("تساوی مافیا و شهروند", body)
        self.assertIn("tie_mafia_yes", str(kb.inline_keyboard))
        self.assertLess(body.index("گزارش"), body.index("تساوی"))


if __name__ == "__main__":
    unittest.main()
