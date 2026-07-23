"""تست تفنگدار و خرابکار — سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Player, Role
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_saboteur as ms_sb
from bot.roles.registry import get_role_module, is_registered_role


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


class MasonGunnerTownTests(unittest.TestCase):
    def test_gunner_is_town(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        gm.add_player(game, gunner)
        self.assertTrue(ms_gn.is_mason_gunner(game, gunner))
        self.assertTrue(ms_gn.mason_gunner_is_town(game, gunner))
        self.assertFalse(is_mafia_team(gunner.role))


class MasonGunnerNightTests(unittest.TestCase):
    def test_cannot_target_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        gm.add_player(game, gunner)
        self.assertFalse(ms_gn.mason_gunner_can_target(game, gunner, gunner))

    def test_can_target_other_alive_player(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        target = _p(20, "Amir", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, target)
        self.assertTrue(ms_gn.mason_gunner_can_target(game, gunner, target))
        self.assertTrue(ms_gn.commit_mason_gunner_target(game, gunner, target))
        self.assertEqual(game.mason_gunner_night_target_uid, 20)


class MasonDayGunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mason_game(self.gm)
        self.gunner = _p(10, "Ali", Role.GUNMAN)
        self.holder = _p(20, "Amir", Role.TOWN_SIMPLE)
        self.victim = _p(30, "Hasan", Role.SPY)
        self.gm.add_player(self.game, self.gunner)
        self.gm.add_player(self.game, self.holder)
        self.gm.add_player(self.game, self.victim)

    def test_gunner_target_becomes_day_gun_holder(self) -> None:
        ms_gn.commit_mason_gunner_target(self.game, self.gunner, self.holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(self.game)
        self.assertEqual(ms_gn.mason_day_gun_holder_uid(self.game), 20)
        self.assertTrue(ms_gn.mason_day_gun_available(self.game))
        self.assertFalse(ms_gn.mason_day_gun_is_sabotaged(self.game))

    def test_holder_can_shoot_other_player(self) -> None:
        ms_gn.commit_mason_gunner_target(self.game, self.gunner, self.holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(self.game)
        self.assertTrue(
            ms_gn.mason_day_gun_holder_can_shoot(self.game, self.holder, self.victim)
        )

    def test_normal_gun_eliminates_target(self) -> None:
        ms_gn.commit_mason_gunner_target(self.game, self.gunner, self.holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(self.game)
        ms_gn.mark_mason_gun_delivered_to_holder(self.game)
        result = ms_gn.resolve_mason_day_gun_shot(self.game, self.holder, self.victim)
        assert result is not None
        self.assertFalse(result.sabotaged)
        self.assertEqual(result.eliminated_uid, 30)
        self.assertEqual(result.survivor_uid, 20)
        self.assertTrue(ms_gn.mason_day_gun_is_used(self.game))


class MasonSaboteurTests(unittest.TestCase):
    def test_saboteur_is_mafia(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        sab = _p(40, "Sb", Role.SABOTEUR)
        gm.add_player(game, sab)
        self.assertTrue(ms_sb.is_mason_saboteur(game, sab))
        self.assertTrue(ms_sb.mason_saboteur_is_mafia(game, sab))
        self.assertTrue(is_mafia_team(sab.role))

    def test_saboteur_can_target_alive_players(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        sab = _p(40, "Sb", Role.SABOTEUR)
        target = _p(20, "Amir", Role.TOWN_SIMPLE)
        gm.add_player(game, sab)
        gm.add_player(game, target)
        self.assertTrue(ms_sb.mason_saboteur_can_target(game, sab, target))
        self.assertTrue(ms_sb.commit_mason_saboteur_target(game, sab, target))

    def test_matching_targets_sabotage_gun(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Amir", Role.TOWN_SIMPLE)
        sab = _p(40, "Sb", Role.SABOTEUR)
        victim = _p(30, "Hasan", Role.SPY)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, sab)
        gm.add_player(game, victim)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_sb.commit_mason_saboteur_target(game, sab, holder)
        self.assertTrue(ms_sb.mason_saboteur_sabotages_gunner_target(game))
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertTrue(ms_gn.mason_day_gun_is_sabotaged(game))

    def test_sabotaged_gun_kills_holder_not_target(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Amir", Role.TOWN_SIMPLE)
        sab = _p(40, "Sb", Role.SABOTEUR)
        victim = _p(30, "Hasan", Role.SPY)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, sab)
        gm.add_player(game, victim)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_sb.commit_mason_saboteur_target(game, sab, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        result = ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        assert result is not None
        self.assertTrue(result.sabotaged)
        self.assertEqual(result.eliminated_uid, 20)
        self.assertEqual(result.survivor_uid, 30)

    def test_non_matching_saboteur_target_normal_gun(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Amir", Role.TOWN_SIMPLE)
        sab = _p(40, "Sb", Role.SABOTEUR)
        other = _p(25, "Other", Role.TOWN_SIMPLE)
        victim = _p(30, "Hasan", Role.SPY)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, sab)
        gm.add_player(game, other)
        gm.add_player(game, victim)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_sb.commit_mason_saboteur_target(game, sab, other)
        self.assertFalse(ms_sb.mason_saboteur_sabotages_gunner_target(game))
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        result = ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        assert result is not None
        self.assertFalse(result.sabotaged)
        self.assertEqual(result.eliminated_uid, 30)


class MasonDayGunStateTests(unittest.TestCase):
    def test_gun_cannot_be_used_twice(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Amir", Role.TOWN_SIMPLE)
        a = _p(30, "A", Role.TOWN_SIMPLE)
        b = _p(31, "B", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, a)
        gm.add_player(game, b)
        ms_gn.commit_mason_gunner_target(game, gunner, holder)
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        ms_gn.resolve_mason_day_gun_shot(game, holder, a)
        self.assertFalse(ms_gn.mason_day_gun_available(game))
        self.assertIsNone(ms_gn.resolve_mason_day_gun_shot(game, holder, b))

    def test_reset_on_new_game(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        for i in range(12):
            gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
        game.mason_gunner_night_target_uid = 20
        game.mason_day_gun_holder_uid = 20
        game.mason_day_gun_sabotaged = True
        game.mason_day_gun_used = True
        game.mason_gun_spent = True
        gm.assign_roles(game)
        self.assertIsNone(game.mason_gunner_night_target_uid)
        self.assertIsNone(game.mason_day_gun_holder_uid)
        self.assertFalse(game.mason_day_gun_sabotaged)
        self.assertFalse(game.mason_day_gun_used)
        self.assertFalse(game.mason_gun_spent)


class MasonGunnerSaboteurRegistryTests(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertTrue(is_registered_role(Role.GUNMAN))
        self.assertTrue(is_registered_role(Role.SABOTEUR))
        self.assertIs(get_role_module(Role.GUNMAN), ms_gn)
        self.assertIs(get_role_module(Role.SABOTEUR), ms_sb)


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_helpers_inert_outside_mason(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gunner = _p(10, "Gn", Role.GUNMAN)
        gm.add_player(game, gunner)
        self.assertFalse(ms_gn.is_mason_gunner(game, gunner))
        self.assertFalse(ms_gn.mason_day_gun_available(game))

    def test_mozakere_unaffected(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        sab = _p(40, "Sb", Role.SABOTEUR)
        gm.add_player(game, sab)
        self.assertFalse(ms_sb.is_mason_saboteur(game, sab))
