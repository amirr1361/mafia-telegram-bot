"""بازپرسی روز وقتی بازپرس در شب مرده اما نامزدها زنده‌اند."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    ASK_NIGHT_EXTRA,
    _interrog_ready_split_night_end_panel,
    _refresh_interrog_ready_for_day,
    build_host_message_and_keyboard,
    build_night_end_report_bundle_html,
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


class InterrogInterrogatorDeadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_interrog_ready_when_interrogator_dies_but_nominees_alive(self) -> None:
        nato = _p(-910001, 1, "ناتو", Role.NATO)
        interrogator = _p(-910003, 3, "بازپرس", Role.INTERROGATOR, alive=False)
        hunter = _p(-910007, 7, "هانتر", Role.HUNTER)
        game = Game(
            room_code="34",
            host_id=1,
            scenario_name="bazpors_salamat_test",
            players={
                -910001: nato,
                -910003: interrogator,
                -910004: _p(-910004, 4, "شهروند ۱", Role.CITIZEN),
                -910006: _p(-910006, 6, "رییس مافیا", Role.MAFIA_BOSS),
                -910007: hunter,
                -910010: _p(-910010, 10, "شهروند ۲", Role.CITIZEN),
            },
        )
        game.mafia_ids = {-910006}
        game.bazpors_narrator_night_count = 1
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -910001
        game.bazpors_interrog_second_uid = -910007
        game.bazpors_interrog_ready_for_day = False
        game.bazpors_interrog_cancel_next_day = False
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_alive_at_night_start[-910003] = True

        _refresh_interrog_ready_for_day(game)

        self.assertTrue(game.bazpors_interrog_ready_for_day)
        self.assertFalse(game.bazpors_interrog_cancel_next_day)

        game.bazpors_host_mode = "semi_auto"
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        game.bazpors_night_report_html = "گزارش شب"
        self.assertTrue(_interrog_ready_split_night_end_panel(game, self.gm))
        report = build_night_end_report_bundle_html(game, self.gm)
        self.assertIn("دو دکمهٔ زیر", report)
        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("بازپرسی باید انجام شود", body)
        self.assertNotIn("گزارش شب", body)
        self.assertIsNotNone(kb)
        self.assertIn("intr_continue", str(kb.inline_keyboard))

    def test_interrog_cancel_when_nominee_died_same_night(self) -> None:
        hunter = _p(-910007, 7, "هانتر", Role.HUNTER, alive=False)
        game = Game(
            room_code="34",
            host_id=1,
            scenario_name="bazpors_salamat_test",
            players={
                -910001: _p(-910001, 1, "ناتو", Role.NATO),
                -910003: _p(-910003, 3, "بازپرس", Role.INTERROGATOR, alive=False),
                -910007: hunter,
            },
        )
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -910001
        game.bazpors_interrog_second_uid = -910007
        game.bazpors_alive_at_night_start = {
            -910001: True,
            -910003: True,
            -910007: True,
        }

        _refresh_interrog_ready_for_day(game)

        self.assertFalse(game.bazpors_interrog_ready_for_day)
        self.assertTrue(game.bazpors_interrog_cancel_next_day)


if __name__ == "__main__":
    unittest.main()
