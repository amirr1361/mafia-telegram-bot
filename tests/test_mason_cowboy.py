"""تست کابوی — سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Player, Role
from bot.roles import mason_cowboy as ms_cw
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


class MasonCowboyTownTests(unittest.TestCase):
    def test_cowboy_is_town(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        cowboy = _p(40, "Cw", Role.COWBOY)
        gm.add_player(game, cowboy)
        self.assertTrue(ms_cw.mason_cowboy_is_town(game, cowboy))
        self.assertFalse(is_mafia_team(cowboy.role))


class MasonCowboyAbilityMetadataTests(unittest.TestCase):
    def test_no_night_day_action_yes(self) -> None:
        self.assertFalse(ms_cw.HAS_NIGHT_ACTION)
        self.assertTrue(ms_cw.HAS_DAY_ACTION)


class MasonCowboyDayPickTests(unittest.TestCase):
    def test_eliminates_any_alive_target(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        gm.add_player(game, _p(20, "Boss", Role.GODFATHER))
        ms_cw.commit_mason_cowboy_day_pick(game, 20, confirmed=True)
        self.assertTrue(ms_cw.mason_cowboy_day_elimination_would_succeed(game, 20))

    def test_unconfirmed_pick_does_not_eliminate(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_cw.commit_mason_cowboy_day_pick(game, 20, confirmed=False)
        self.assertFalse(ms_cw.mason_cowboy_day_elimination_would_succeed(game, 20))


class MasonCowboyRegistryTests(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertTrue(is_registered_role(Role.COWBOY))
        self.assertIs(get_role_module(Role.COWBOY), ms_cw)


class BazporsRegressionTests(unittest.TestCase):
    def test_cowboy_helpers_inert_outside_mason(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        cowboy = _p(40, "Cw", Role.COWBOY)
        gm.add_player(game, cowboy)
        self.assertFalse(ms_cw.is_mason_cowboy(game, cowboy))
        self.assertFalse(ms_cw.mason_cowboy_day_elimination_would_succeed(game, 40))
