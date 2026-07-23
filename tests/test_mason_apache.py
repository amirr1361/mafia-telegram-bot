"""تست آپاچی — سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Player, Role
from bot.roles import mason_apache as ms_ap
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


class MasonApacheFactionTests(unittest.TestCase):
    def test_apache_counts_as_mafia(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        apache = _p(10, "Ap", Role.APACHE)
        gm.add_player(game, apache)
        self.assertTrue(ms_ap.apache_counts_as_mafia(game, apache))
        self.assertTrue(ms_ap.mason_counts_as_mafia_faction(game, apache))
        self.assertTrue(is_mafia_team(Role.APACHE))

    def test_mason_mafia_faction_includes_godfather(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        boss = _p(11, "Boss", Role.GODFATHER)
        gm.add_player(game, boss)
        self.assertTrue(ms_ap.mason_counts_as_mafia_faction(game, boss))


class MasonApacheIsolationTests(unittest.TestCase):
    def test_apache_no_mafia_intro_or_panels(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        apache = _p(10, "Ap", Role.APACHE)
        gm.add_player(game, apache)
        self.assertFalse(ms_ap.apache_receives_mafia_intro(game, apache))
        self.assertFalse(ms_ap.apache_receives_mafia_panels(game, apache))

    def test_other_mafia_get_intro_but_not_apache_identity(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        spy = _p(11, "Spy", Role.SPY)
        gm.add_player(game, spy)
        self.assertTrue(ms_ap.apache_receives_mafia_intro(game, spy))
        self.assertFalse(ms_ap.mafia_member_informed_about_apache(game, spy))


class MasonApacheDayAbilityTests(unittest.TestCase):
    def test_day_elimination_blocked_by_guardian(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        from bot.roles import mason_guardian as ms_gd

        ms_gd.commit_mason_guardian_night_pick(game, 20)
        ms_gd.activate_mason_guardian_day_protection(game)
        ms_ap.commit_mason_apache_day_pick(game, 20, confirmed=True)
        self.assertFalse(ms_ap.mason_apache_day_elimination_would_succeed(game, 20))

    def test_metadata(self) -> None:
        self.assertFalse(ms_ap.HAS_NIGHT_ACTION)
        self.assertTrue(ms_ap.HAS_DAY_ACTION)


class MasonApacheRegistryTests(unittest.TestCase):
    def test_registered_in_capability_registry(self) -> None:
        self.assertTrue(is_registered_role(Role.APACHE))
        self.assertIs(get_role_module(Role.APACHE), ms_ap)


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_bazpors_mafia_intro_not_gated_by_mason_helpers(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        boss = _p(10, "Boss", Role.MAFIA_BOSS)
        gm.add_player(game, boss)
        self.assertTrue(ms_ap.apache_receives_mafia_intro(game, boss))

    def test_mozakere_unaffected(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        neg = _p(11, "Neg", Role.MAFIA_NEGOTIATOR)
        gm.add_player(game, neg)
        self.assertFalse(ms_ap.apache_counts_as_mafia(game, neg))
