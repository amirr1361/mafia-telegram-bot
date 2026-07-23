"""نیمه‌خودکار — پزشک پس از یاکوزایی همان شب."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_DOC,
    NS_DOC_YAKU_SKIP,
    NS_INTERROG_SKIP,
    _advance_after_det,
    _compose_full_night_report,
    _semi_auto_doctor_skip_after_yaku_this_night,
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


def make_semi_auto_game() -> Game:
    game = Game(
        room_code="77",
        host_id=1,
        scenario_name="bazpors",
        players={
            -1: _p(-1, 1, "رییس", Role.MAFIA_BOSS),
            -2: _p(-2, 2, "پزشک", Role.DOCTOR),
            -3: _p(-3, 3, "کارآگاه", Role.DETECTIVE),
            -4: _p(-4, 4, "بازپرس", Role.INTERROGATOR),
        },
    )
    game.bazpors_host_mode = "semi_auto"
    game.bazpors_narrator_night_count = 1
    game.bazpors_alive_at_night_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }
    return game


class SemiAutoYakuDoctorSkipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_skip_flag_when_yaku_civilian_set(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_yaku_night_success = False
        self.assertTrue(_semi_auto_doctor_skip_after_yaku_this_night(game))

    def test_no_skip_without_yaku_this_night(self) -> None:
        game = make_semi_auto_game()
        self.assertFalse(_semi_auto_doctor_skip_after_yaku_this_night(game))

    def test_advance_after_det_shows_yaku_skip_panel(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_yaku_night_success = True

        _advance_after_det(game)

        self.assertEqual(game.bazpors_night_substep, NS_DOC_YAKU_SKIP)

    def test_yaku_skip_panel_text_and_next_advances_to_interrogator(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_interrog_once_done = True
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC_YAKU_SKIP

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("یاکوزایی", body)
        self.assertIn("نیازی به گرفتن انتخاب پزشک", body)
        self.assertIsNotNone(kb)

        err = process_narrator_callback(
            game, self.gm, "doc_yaku_skip_ok", 0, ""
        )
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_night_substep, NS_INTERROG_SKIP)

    def test_night_report_notes_doctor_skipped_for_yaku(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_yaku_night_civilian_uid = -3
        snap = dict(game.bazpors_alive_at_night_start)
        report = _compose_full_night_report(game, self.gm, snap)
        self.assertNotIn("نجات پزشک:", report)
        self.assertNotIn("انتخاب پزشک", report)

    def test_normal_doctor_step_when_no_yaku(self) -> None:
        game = make_semi_auto_game()
        _advance_after_det(game)
        self.assertEqual(game.bazpors_night_substep, NS_DOC)


if __name__ == "__main__":
    unittest.main()
