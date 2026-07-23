"""اسنایپر — شب no_host."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_sniper_night import (
    _commit_sniper_pick,
    _sniper_shot_pool,
    build_no_host_sniper_pick_html,
)


class NoHostSniperNightTest(unittest.TestCase):
    def test_pick_html_has_rules(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        body = build_no_host_sniper_pick_html(game)
        self.assertIn("شب اول", body)
        self.assertIn("ثبت انتخاب اسنایپر", body)
        self.assertIn("یک‌بار", body)
        self.assertIn("رئیس مافیا", body)
        self.assertIn("پس از پایان فاز امشب", body)

    def test_pool_excludes_sniper(self) -> None:
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
            Player(user_id=10, full_name="Sn", username=None, role=Role.SNIPER),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="A", username=None, role=Role.CITIZEN),
        )
        pool = _sniper_shot_pool(game)
        self.assertEqual([p.user_id for p in pool], [20])

    def test_commit_sets_night_target(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        _commit_sniper_pick(game, 20)
        self.assertEqual(game.bazpors_sniper_night_target_uid, 20)
        _commit_sniper_pick(game, None)
        self.assertIsNone(game.bazpors_sniper_night_target_uid)


if __name__ == "__main__":
    unittest.main()
