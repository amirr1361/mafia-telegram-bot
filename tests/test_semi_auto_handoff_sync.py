"""همگام‌سازی وضعیت بازی پس از انتقال no_host → semi_auto."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import Role
from bot.bazpors_semi_auto_state import sync_bazpors_semi_auto_after_handoff
from bot.game import GameManager
from bot.models import Game, Player
from bot.no_host_handoff import apply_handoff_to_semi_auto


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


class SemiAutoHandoffSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game(self) -> Game:
        return Game(
            room_code="77",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "گرداننده", Role.CITIZEN, alive=False),
                -2: _p(-2, 2, "شهروند", Role.CITIZEN),
                -3: _p(-3, 3, "مافیا", Role.MAFIA),
                -4: _p(-4, 4, "اسنایپر", Role.SNIPER),
            },
        )

    def test_sync_commits_pending_doctor_self_save(self) -> None:
        game = self._game()
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_doctor_self_save_count = 1
        sync_bazpors_semi_auto_after_handoff(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 2)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(game.bazpors_night_baseline_doctor_self_saves, 2)

    def test_sync_marks_sniper_shot_from_night_target(self) -> None:
        game = self._game()
        game.bazpors_narrator_night_count = 1
        game.bazpors_sniper_night_target_uid = -3
        sync_bazpors_semi_auto_after_handoff(game)
        self.assertTrue(game.bazpors_sniper_shot_used)

    def test_sync_interrog_from_day_decision(self) -> None:
        game = self._game()
        game.no_host_interrog_day_decision = "continue"
        sync_bazpors_semi_auto_after_handoff(game)
        self.assertTrue(game.bazpors_interrog_once_done)

    def test_apply_handoff_preserves_nato_yaku_flags(self) -> None:
        game = self._game()
        game.bazpors_host_mode = "no_host"
        game.bazpors_nato_used = True
        game.bazpors_yakuzai_used = True
        game.bazpors_doctor_self_save_count = 1
        apply_handoff_to_semi_auto(game, -1)
        self.assertEqual(game.bazpors_host_mode, "semi_auto")
        self.assertTrue(game.bazpors_nato_used)
        self.assertTrue(game.bazpors_yakuzai_used)
        self.assertEqual(game.bazpors_doctor_self_save_count, 1)

if __name__ == "__main__":
    unittest.main()
