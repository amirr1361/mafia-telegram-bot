"""تست منطق مشترک ناتویی — bot/roles/nato.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_MAFIA_MENU,
    NS_NATO_CONFIRM,
    NS_NATO_ROLE,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.roles import doctor as dr
from bot.roles import nato as nato_mod
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
        room_code="NAT1",
        host_id=1,
        scenario_name="bazpors",
        players={
            10: _p(10, 1, "Boss", Role.MAFIA_BOSS),
            20: _p(20, 2, "Nato", Role.NATO),
            30: _p(30, 3, "Doc", Role.DOCTOR),
            40: _p(40, 4, "Cit", Role.CITIZEN),
        },
    )
    game.bazpors_host_mode = "no_host"
    game.bot_assistant_user_id = 1
    game.no_host_assistant_narrator_active = True
    return game


class NatoModuleCoreTests(unittest.TestCase):
    def test_find_alive_nato(self) -> None:
        game = _no_host_game()
        self.assertEqual(nato_mod.find_alive_nato(game).user_id, 20)

    def test_can_register_when_nato_alive(self) -> None:
        self.assertTrue(nato_mod.can_register(_no_host_game()))

    def test_cannot_register_after_used(self) -> None:
        game = _no_host_game()
        game.bazpors_nato_used = True
        self.assertFalse(nato_mod.can_register(game))

    def test_cannot_register_when_nato_dead(self) -> None:
        game = _no_host_game()
        game.players[20].is_alive = False
        self.assertFalse(nato_mod.can_register(game))
        self.assertIn("خارج شده", nato_mod.denied_message(game))

    def test_guess_roles_excludes_citizen(self) -> None:
        roles = nato_mod.guess_roles_in_room(_no_host_game())
        self.assertIn(Role.DOCTOR, roles)
        self.assertNotIn(Role.CITIZEN, roles)

    def test_target_pool_non_mafia_only(self) -> None:
        pool_ids = {p.user_id for p in nato_mod.target_pool(_no_host_game())}
        self.assertIn(30, pool_ids)
        self.assertNotIn(10, pool_ids)
        self.assertNotIn(20, pool_ids)

    def test_evaluate_correct_guess(self) -> None:
        game = _no_host_game()
        self.assertTrue(nato_mod.evaluate_guess(game, Role.DOCTOR, 30))

    def test_evaluate_wrong_guess(self) -> None:
        game = _no_host_game()
        self.assertFalse(nato_mod.evaluate_guess(game, Role.DETECTIVE, 30))

    def test_commit_guess_success(self) -> None:
        game = _no_host_game()
        gm = GameManager()
        ok = nato_mod.commit_guess(game, Role.DOCTOR, 30, gm=gm, announce=True)
        self.assertTrue(ok)
        self.assertTrue(game.bazpors_nato_used)
        self.assertTrue(game.bazpors_nato_action_registered)
        self.assertEqual(game.bazpors_nato_kill_target_uid, 30)

    def test_commit_guess_voids_doctor_pick(self) -> None:
        game = _no_host_game()
        dr.commit_pick(game, 40)
        nato_mod.commit_guess(game, Role.DOCTOR, 30)
        self.assertEqual(dr.save_uid_set(game), set())

    def test_commit_confirm_result(self) -> None:
        game = _no_host_game()
        nato_mod.commit_confirm_result(game, 30, success=True)
        self.assertTrue(game.bazpors_nato_success)
        self.assertEqual(game.bazpors_nato_kill_target_uid, 30)

    def test_target_invalid_for_mafia(self) -> None:
        game = _no_host_game()
        self.assertFalse(nato_mod.target_valid(game, 10))


class NatoSemiAutoPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_mnato_starts_role_step(self) -> None:
        game = make_semi_auto_game()
        game.players[-1].role = Role.NATO
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_MAFIA_MENU
        err = process_narrator_callback(game, self.gm, "mnato", 0, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_night_substep, NS_NATO_ROLE)

    def test_npick_commits_through_shared_module(self) -> None:
        game = make_semi_auto_game()
        game.players[-2].role = Role.NATO
        game.players[-3].role = Role.DOCTOR
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_NATO_ROLE
        process_narrator_callback(game, self.gm, "nrole", 0, Role.DOCTOR.value)
        game.bazpors_night_substep = NS_NATO_CONFIRM
        err = process_narrator_callback(game, self.gm, "npick", -3, "")
        self.assertIsNone(err)
        self.assertTrue(game.bazpors_nato_used)
        self.assertTrue(game.bazpors_nato_success)

    def test_nwr_wrong_guess_commits_failure(self) -> None:
        game = make_semi_auto_game()
        game.players[-2].role = Role.NATO
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_NATO_CONFIRM
        game.bazpors_narrator_pending_uid = -3
        err = process_narrator_callback(game, self.gm, "nwr", 0, "")
        self.assertIsNone(err)
        self.assertFalse(game.bazpors_nato_success)
        self.assertIsNone(game.bazpors_nato_kill_target_uid)


class NatoNoHostPathTests(unittest.TestCase):
    def test_no_host_allowed_helper(self) -> None:
        from bot.no_host_mafia_nato import no_host_nato_allowed

        self.assertTrue(no_host_nato_allowed(_no_host_game()))

    def test_apply_guess_via_shared_module(self) -> None:
        from bot.no_host_mafia_nato import _apply_nato_guess_to_game

        game = _no_host_game()
        gm = GameManager()
        _apply_nato_guess_to_game(game, gm, guess_role=Role.DOCTOR, target_uid=30)
        self.assertTrue(game.bazpors_nato_success)


if __name__ == "__main__":
    unittest.main()
