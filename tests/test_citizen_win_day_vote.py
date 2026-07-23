"""برد شهروند بعد از رأی روز — بدون گزارش شب قبلی."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    CITIZEN_WIN_GATE,
    CONFIRM_DAY_ELIM,
    build_host_message_and_keyboard,
    process_narrator_callback,
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


class CitizenWinDayVoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_day_vote_last_mafia_shows_vote_message_not_night_report(self) -> None:
        shiad = _p(-2, 2, "شیاد", Role.SHIAD)
        game = Game(
            room_code="33",
            host_id=1,
            scenario_name="bazpors_salamat_test",
            players={
                -1: _p(-1, 1, "شهروند ۱", Role.CITIZEN),
                -2: shiad,
                -3: _p(-3, 3, "بازپرس", Role.INTERROGATOR),
            },
        )
        game.mafia_ids = {-2}
        game.bazpors_narrator_step = CONFIRM_DAY_ELIM
        game.bazpors_narrator_pending_uid = -2
        game.bazpors_day_vote_defender_uids = "-2"
        game.bazpors_night_report_html = (
            "🌙 <b>گزارش کامل شب گذشته</b>\n\n• شات قدیمی"
        )

        err = process_narrator_callback(game, self.gm, "confirm_day_yes", 0, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_narrator_step, CITIZEN_WIN_GATE)
        self.assertEqual(game.bazpors_citizen_win_elim_source, "day_vote")
        self.assertEqual(game.bazpors_citizen_win_elim_uid, -2)
        self.assertFalse(shiad.is_alive)

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("رأی‌گیری روز", body)
        self.assertIn("شیاد", body)
        self.assertNotIn("گزارش کامل شب گذشته", body)
        self.assertIsNotNone(kb)
        self.assertIn("tie_citizen_yes", str(kb.inline_keyboard))


if __name__ == "__main__":
    unittest.main()
