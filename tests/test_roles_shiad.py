"""تست منطق مشترک شیاد — bot/roles/shiad.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_SHIAD,
    NS_SHIAD_ACK,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.roles import detective as det
from bot.roles import shiad as shiad_mod
from tests.test_semi_auto_yaku_doctor_skip import make_semi_auto_game


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def _no_host_game() -> Game:
    game = Game(
        room_code="SH1",
        host_id=1,
        scenario_name="bazpors",
        players={
            10: _p(10, 1, "Sh", Role.SHIAD),
            20: _p(20, 2, "Det", Role.DETECTIVE),
            30: _p(30, 3, "Cit", Role.CITIZEN),
            40: _p(40, 4, "Boss", Role.MAFIA_BOSS),
        },
    )
    game.bazpors_host_mode = "no_host"
    game.bot_assistant_user_id = 1
    game.no_host_assistant_narrator_active = True
    return game


class ShiadModuleCoreTests(unittest.TestCase):
    def test_find_alive_shiad(self) -> None:
        self.assertEqual(shiad_mod.find_alive_shiad(_no_host_game()).user_id, 10)

    def test_guess_pool_excludes_self_and_mafia(self) -> None:
        pool_ids = {p.user_id for p in shiad_mod.guess_pool(_no_host_game())}
        self.assertIn(20, pool_ids)
        self.assertIn(30, pool_ids)
        self.assertNotIn(10, pool_ids)
        self.assertNotIn(40, pool_ids)

    def test_target_valid_rejects_mafia_and_self(self) -> None:
        game = _no_host_game()
        self.assertTrue(shiad_mod.target_valid(game, 20))
        self.assertFalse(shiad_mod.target_valid(game, 10))
        self.assertFalse(shiad_mod.target_valid(game, 40))

    def test_commit_blocks_detective_on_hit(self) -> None:
        game = _no_host_game()
        hit = shiad_mod.commit_pick(game, 20)
        self.assertTrue(hit)
        self.assertTrue(game.bazpors_detective_blocked)
        self.assertEqual(game.bazpors_shiad_target_uid, 20)

    def test_commit_wrong_guess_does_not_block(self) -> None:
        game = _no_host_game()
        hit = shiad_mod.commit_pick(game, 30)
        self.assertFalse(hit)
        self.assertFalse(game.bazpors_detective_blocked)
        self.assertIn("هدف شیاد", game.bazpors_detective_last_answer or "")

    def test_clear_pick(self) -> None:
        game = _no_host_game()
        shiad_mod.commit_pick(game, 20)
        shiad_mod.clear_pick(game)
        self.assertIsNone(game.bazpors_shiad_target_uid)
        self.assertFalse(game.bazpors_detective_blocked)

    def test_detective_inquiry_negative_shiad_when_blocked(self) -> None:
        game = _no_host_game()
        shiad_mod.commit_pick(game, 20)
        result = det.evaluate_inquiry(game, 30)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_SHIAD)


class ShiadSemiAutoPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_sg_commits_through_shared_module(self) -> None:
        game = make_semi_auto_game()
        game.players[-4].role = Role.SHIAD
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_SHIAD
        err = process_narrator_callback(game, self.gm, "sg", -3, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_shiad_target_uid, -3)
        self.assertTrue(game.bazpors_detective_blocked)
        self.assertEqual(game.bazpors_night_substep, NS_SHIAD_ACK)

    def test_sg_wrong_guess_advances(self) -> None:
        game = make_semi_auto_game()
        game.players[-4].role = Role.SHIAD
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_SHIAD
        err = process_narrator_callback(game, self.gm, "sg", -2, "")
        self.assertIsNone(err)
        self.assertFalse(game.bazpors_detective_blocked)
        self.assertIn("منفی (شهروندی)", game.bazpors_detective_last_answer or "")


class ShiadNoHostPathTests(unittest.TestCase):
    def test_no_host_commit_via_shim(self) -> None:
        from bot.no_host_shiad_night import _commit_shiad_pick

        game = _no_host_game()
        hit = _commit_shiad_pick(game, 20)
        self.assertTrue(hit)
        self.assertTrue(game.bazpors_detective_blocked)


if __name__ == "__main__":
    unittest.main()
