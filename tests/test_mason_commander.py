"""تست فرمانده — سناریوی ماسون (منطق ایزوله)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_sniper as ms_sn


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
    )
    assert game is not None
    return game


class MasonCommanderApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mason_game(self.gm, n=12)
        self.gm.add_player(self.game, _p(10, "Sn", Role.SNIPER))
        self.gm.add_player(self.game, _p(20, "A", Role.TOWN_SIMPLE))
        self.gm.add_player(self.game, _p(30, "B", Role.TOWN_SIMPLE))
        self.gm.add_player(self.game, _p(40, "Cmd", Role.COMMANDER))

    def test_partial_approval_consumes_one_bullet(self) -> None:
        ms_sn.commit_mason_sniper_night_selection(self.game, [20, 30])
        self.assertTrue(ms_cmd.commit_mason_commander_approval(self.game, [20]))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(self.game), 1)
        self.assertEqual(ms_cmd.mason_unused_selected_targets_after_partial_approval(self.game), [30])

    def test_reject_all_consumes_zero(self) -> None:
        ms_sn.commit_mason_sniper_night_selection(self.game, [20, 30])
        self.assertTrue(ms_cmd.mason_commander_rejects_all_shots(self.game))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(self.game), 0)

    def test_no_commander_auto_approve_on_finalize(self) -> None:
        game = _mason_game(self.gm, n=16)
        self.gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        self.gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [20])
        ms_cmd.auto_approve_sniper_shots_when_no_commander(game)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [20])

    def test_full_approval_consumes_two(self) -> None:
        ms_sn.commit_mason_sniper_night_selection(self.game, [20, 30])
        self.assertTrue(ms_cmd.commit_mason_commander_approval(self.game, [20, 30]))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(self.game), 2)

    def test_cannot_approve_without_sniper_selection(self) -> None:
        self.assertFalse(ms_cmd.commit_mason_commander_approval(self.game, [20]))

    def test_cannot_approve_target_not_selected(self) -> None:
        ms_sn.commit_mason_sniper_night_selection(self.game, [20])
        self.assertFalse(ms_cmd.commit_mason_commander_approval(self.game, [30]))


class MasonCommanderInheritanceTests(unittest.TestCase):
    def test_commander_inherits_remaining_bullets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [20])
        ms_cmd.commit_mason_commander_approval(game, [20])
        game.players[10].is_alive = False
        self.assertTrue(ms_cmd.mason_commander_inherits_sniper_shooting(game))
        self.assertEqual(ms_cmd.mason_commander_bullets_remaining(game), 1)

    def test_commander_direct_shot_when_no_sniper(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        self.assertTrue(ms_cmd.mason_commander_inherits_sniper_shooting(game))
        self.assertTrue(ms_cmd.commit_mason_commander_direct_shots(game, [20]))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)
        self.assertEqual(ms_sn.mason_commander_approved_shot_uids(game), [20])

    def test_commander_zero_bullets_when_sniper_exhausted(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 2
        game.players[10].is_alive = False
        self.assertEqual(ms_cmd.mason_commander_bullets_remaining(game), 0)


class MasonApprovedKillResolutionTests(unittest.TestCase):
    def test_immune_target_not_in_kill_list(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "Boss", Role.GODFATHER))
        ms_sn.commit_mason_sniper_night_selection(game, [20])
        ms_cmd.commit_mason_commander_approval(game, [20])
        self.assertEqual(ms_sn.mason_approved_shots_attempted(game), [20])
        self.assertEqual(ms_sn.mason_approved_shots_that_kill(game), [])


class MasonResetOnDealTests(unittest.TestCase):
    def test_assign_roles_resets_mason_counters(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        for i in range(12):
            gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
        game.mason_doctor_self_save_count = 2
        game.mason_sniper_bullets_spent = 2
        gm.assign_roles(game)
        self.assertEqual(game.mason_doctor_self_save_count, 0)
        self.assertEqual(game.mason_sniper_bullets_spent, 0)
