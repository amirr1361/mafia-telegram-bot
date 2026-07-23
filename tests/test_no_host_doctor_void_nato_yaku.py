"""no_host — باطل شدن نجات خود پزشک پس از ناتو/یاکوزا."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    _arm_night_actions_baseline,
    _commit_night_pending_state,
    _void_semi_auto_doctor_night_pick,
)
from bot.game import GameManager
from bot.models import Player, Role


class NoHostDoctorVoidNatoYakuTests(unittest.TestCase):
    def _no_host_game(self):
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_enabled = True
        game.bot_assistant_user_id = 1
        game.no_host_assistant_narrator_active = True
        return game

    def test_void_pending_self_save_after_nato(self) -> None:
        game = self._no_host_game()
        game.players[10] = Player(
            user_id=10, full_name="Doc", username=None, role=Role.DOCTOR
        )
        game.bazpors_doctor_save_uids = [10]
        game.actions.doctor_save = 10
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 0
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_nato_action_registered = True

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(game.bazpors_doctor_save_uids, [])
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_commit_skips_self_save_when_nato_registered(self) -> None:
        game = self._no_host_game()
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 0
        game.bazpors_nato_action_registered = True

        _commit_night_pending_state(game)

        self.assertEqual(game.bazpors_doctor_self_save_count, 0)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)

    def test_void_after_nato_with_stale_count_from_legacy_commit(self) -> None:
        game = self._no_host_game()
        game.players[10] = Player(
            user_id=10, full_name="Doc", username=None, role=Role.DOCTOR
        )
        game.bazpors_doctor_save_uids = [10]
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_nato_action_registered = True
        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(game.bazpors_doctor_self_save_count, 0)
        self.assertEqual(game.bazpors_doctor_save_uids, [])

    def test_void_pending_does_not_erase_prior_self_save_count(self) -> None:
        game = self._no_host_game()
        game.players[10] = Player(
            user_id=10, full_name="Doc", username=None, role=Role.DOCTOR
        )
        game.bazpors_doctor_save_uids = [10]
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 1
        game.bazpors_nato_action_registered = True

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(game.bazpors_doctor_self_save_count, 1)

    def test_void_after_yaku_clears_self_save_count(self) -> None:
        game = self._no_host_game()
        game.players[10] = Player(
            user_id=10, full_name="Doc", username=None, role=Role.DOCTOR
        )
        game.bazpors_doctor_save_uids = [10]
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_yaku_night_civilian_uid = -5
        game.bazpors_yaku_night_success = False

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_nato_void_keeps_prior_night_committed_self_save_count(self) -> None:
        """شب ۱ commit → شب ۲ نجات خود + ناتو → شمارنده همچنان ۱."""
        game = self._no_host_game()
        doc_uid = -920003
        game.players[doc_uid] = Player(
            user_id=doc_uid, full_name="Doc", username=None, role=Role.DOCTOR
        )
        game.bazpors_narrator_night_count = 2
        game.bazpors_doctor_self_save_count = 1
        _arm_night_actions_baseline(game)
        self.assertEqual(game.bazpors_night_baseline_doctor_self_saves, 1)
        game.bazpors_doctor_save_uids = [doc_uid]
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_nato_action_registered = True

        _void_semi_auto_doctor_night_pick(game)

        self.assertEqual(game.bazpors_doctor_self_save_count, 1)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(game.bazpors_doctor_save_uids, [])

    def test_room43_night1_sequence_nato_after_self_pick(self) -> None:
        """شبیه اتاق ۴۳: نجات خود → جمع موازی → ناتو → شمارنده صفر."""
        from bot.bazpors_narrator import _commit_night_pending_state

        game = self._no_host_game()
        doc_uid = -920008
        game.players[doc_uid] = Player(
            user_id=doc_uid, full_name="امین-پزشک", username=None, role=Role.DOCTOR
        )
        game.bazpors_doctor_save_uids = [doc_uid]
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_nato_action_registered = True
        _void_semi_auto_doctor_night_pick(game)
        _commit_night_pending_state(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)


if __name__ == "__main__":
    unittest.main()
