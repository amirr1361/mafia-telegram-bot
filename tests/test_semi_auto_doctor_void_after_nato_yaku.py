"""semi_auto — باطل شدن انتخاب پزشک پس از ناتو/یاکوزا."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    _apply_night_resolution,
    _compose_full_night_report,
    _doctor_save_uid_set,
    _void_semi_auto_doctor_night_pick,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from tests.test_semi_auto_yaku_doctor_skip import make_semi_auto_game


class SemiAutoDoctorVoidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_void_clears_save_and_reverts_self_save_count(self) -> None:
        game = make_semi_auto_game()
        doc = game.players[-2]
        game.bazpors_doctor_save_uids = [doc.user_id]
        game.actions.doctor_save = doc.user_id
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_nato_action_registered = True

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(_doctor_save_uid_set(game), set())
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_void_after_yaku_clears_prior_doctor_pick(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_doctor_save_uids = [-3]
        game.actions.doctor_save = -3
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_yaku_night_success = False

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(_doctor_save_uid_set(game), set())

    def test_nato_registration_voids_doctor_before_resolution(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = "night_actions"
        game.bazpors_night_substep = "ns_nato_confirm"
        game.bazpors_narrator_pending_uid = -3
        game.bazpors_nato_guess_role = Role.DETECTIVE.value
        game.bazpors_doctor_save_uids = [-3]
        game.actions.doctor_save = -3
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4

        err = process_narrator_callback(game, self.gm, "nwr", 0, "")
        self.assertIsNone(err)
        self.assertEqual(_doctor_save_uid_set(game), set())
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_mafia_shot_not_blocked_by_voided_doctor_save(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_nato_action_registered = True
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4
        game.bazpors_doctor_save_uids = [-4]
        game.actions.doctor_save = -4
        snap = {uid: True for uid in game.players}

        _void_semi_auto_doctor_night_pick(game)
        _apply_night_resolution(game, self.gm)

        self.assertFalse(game.players[-4].is_alive)

    def test_night_report_no_doctor_line_when_nato_done(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_nato_action_registered = True
        game.bazpors_doctor_save_uids = [-3]
        game.actions.doctor_save = -3
        snap = {uid: True for uid in game.players}

        report = _compose_full_night_report(game, self.gm, snap)
        self.assertNotIn("نجات پزشک:", report)

    def test_void_self_save_resets_to_baseline_only(self) -> None:
        game = make_semi_auto_game()
        doc = game.players[-2]
        game.bazpors_doctor_save_uids = [doc.user_id]
        game.bazpors_doctor_self_save_count = 2
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_nato_action_registered = True

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(game.bazpors_doctor_self_save_count, 0)


if __name__ == "__main__":
    unittest.main()
