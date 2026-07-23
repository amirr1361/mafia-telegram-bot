"""پزشک — شب no_host."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import _doctor_save_pool, _doctor_save_uid_set
from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_doctor_night import (
    _commit_doctor_pick,
    build_no_host_doctor_nato_blocked_html,
    build_no_host_doctor_pick_html,
)


class NoHostDoctorNightTest(unittest.TestCase):
    def test_pick_html_shows_self_save_count(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        game.bazpors_doctor_self_save_count = 0
        body = build_no_host_doctor_pick_html(game)
        self.assertIn("شب اول", body)
        self.assertIn("ثبت انتخاب پزشک", body)
        self.assertIn("یک نفر", body)
        self.assertIn("۰", body)
        self.assertNotIn("دو نفر", body)

    def test_pool_excludes_doctor_when_two_self_saves(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Doc", username=None, role=Role.DOCTOR),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        game.bazpors_doctor_self_save_count = 2
        pool = _doctor_save_pool(game)
        self.assertEqual([p.user_id for p in pool], [20])

    def test_commit_single_save_for_night_resolution(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Doc", username=None, role=Role.DOCTOR),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="A", username=None, role=Role.CITIZEN)
        )
        _commit_doctor_pick(game, 20)
        self.assertEqual(game.bazpors_doctor_save_uids, [20])
        self.assertEqual(_doctor_save_uid_set(game), {20})
        self.assertTrue(game.bazpors_night_pending_doctor_self_save is False)

    def test_nato_blocked_html(self) -> None:
        body = build_no_host_doctor_nato_blocked_html()
        self.assertIn("عملیات ناتویی", body)
        self.assertIn("اوکی", body)
        self.assertIn("امکان انتخاب هیچ بازیکنی", body)

    def test_self_save_sets_pending_flag(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Doc", username=None, role=Role.DOCTOR),
        )
        _commit_doctor_pick(game, 10)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)

    def test_finalize_night_commits_self_save_when_no_nato_yaku(self) -> None:
        from bot.bazpors_narrator import _commit_night_pending_state

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
        game.bazpors_doctor_self_save_count = 0
        game.bazpors_night_pending_doctor_self_save = True
        _commit_night_pending_state(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 1)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)

    def test_finalize_night_skips_self_save_after_nato(self) -> None:
        from bot.bazpors_narrator import _commit_night_pending_state

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
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_nato_action_registered = True
        _commit_night_pending_state(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)


if __name__ == "__main__":
    unittest.main()
