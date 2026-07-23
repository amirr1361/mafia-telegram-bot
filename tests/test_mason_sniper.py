"""تست تک‌تیرانداز — سناریوی ماسون (منطق ایزوله)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Player, Role
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


class MasonSniperBulletTests(unittest.TestCase):
    def test_bullet_limit_by_room_size(self) -> None:
        gm = GameManager()
        self.assertEqual(ms_sn.mason_sniper_bullet_limit(_mason_game(gm, n=12)), 2)
        self.assertEqual(ms_sn.mason_sniper_bullet_limit(_mason_game(gm, n=15)), 3)
        self.assertEqual(ms_sn.mason_sniper_bullet_limit(_mason_game(gm, n=14)), 2)

    def test_selection_does_not_consume_bullets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        self.assertTrue(ms_sn.commit_mason_sniper_night_selection(game, [20]))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)

    def test_no_shot_selection_consumes_zero(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        self.assertTrue(ms_sn.commit_mason_sniper_night_selection(game, []))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)


class MasonSniperImmunityTests(unittest.TestCase):
    def test_godfather_immune(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        boss = _p(20, "Boss", Role.GODFATHER)
        gm.add_player(game, boss)
        self.assertTrue(ms_sn.mason_sniper_shot_immune(game, boss))

    def test_mason_armored_immune(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        armored = _p(20, "Rt", Role.RUINTAN)
        gm.add_player(game, armored)
        self.assertTrue(ms_sn.mason_sniper_shot_immune(game, armored))

    def test_town_not_immune(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        town = _p(20, "T", Role.TOWN_SIMPLE)
        gm.add_player(game, town)
        self.assertFalse(ms_sn.mason_sniper_shot_immune(game, town))


class MasonSniperNeverDiesTests(unittest.TestCase):
    def test_sniper_never_dies_flag(self) -> None:
        self.assertTrue(ms_sn.mason_sniper_never_dies_for_shot())


class MasonSniperSelectionTests(unittest.TestCase):
    def test_two_targets_when_bullets_remain(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        self.assertTrue(ms_sn.commit_mason_sniper_night_selection(game, [20, 30]))
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [20, 30])

    def test_three_targets_when_18_player_and_three_remain(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=18)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        for i, uid in enumerate((20, 30, 40), start=1):
            gm.add_player(game, _p(uid, f"T{i}", Role.TOWN_SIMPLE))
        self.assertEqual(ms_sn.mason_sniper_max_targets_this_night(game), 3)
        self.assertTrue(
            ms_sn.commit_mason_sniper_night_selection(game, [20, 30, 40])
        )

    def test_cannot_select_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        self.assertFalse(ms_sn.commit_mason_sniper_night_selection(game, [10]))


class BazporsSniperUnchangedTests(unittest.TestCase):
    def test_bazpors_shot_limit_stays_one(self) -> None:
        from bot.roles import sniper as sn

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertEqual(sn.shot_limit(game), 1)
