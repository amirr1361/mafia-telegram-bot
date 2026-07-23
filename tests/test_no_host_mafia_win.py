"""برد مافیا در مسیر no_host."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    mafia_citizen_equal,
    mafia_faction_wins,
    no_mafia_alive,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_mafia_win import (
    build_no_host_all_players_roles_roster_html,
    build_no_host_mafia_win_announce_html,
)


def _no_host_game(**kwargs) -> Game:
    game = Game(**kwargs)
    game.bazpors_host_mode = "no_host"
    game.bot_assistant_user_id = 99
    game.no_host_assistant_narrator_active = True
    return game


def _p(uid: int, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=f"P{uid}",
        username=None,
        role=role,
        seat=uid,
        is_alive=alive,
    )


class NoHostMafiaWinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_mafia_wins_when_equal(self) -> None:
        game = _no_host_game(
            room_code="mw",
            host_id=1,
            scenario_name="bazpors",
            players={
                1: _p(1, Role.MAFIA_BASIC),
                2: _p(2, Role.CITIZEN),
            },
        )
        self.assertTrue(mafia_faction_wins(game, self.gm))
        self.assertTrue(mafia_citizen_equal(game, self.gm))

    def test_mafia_wins_when_majority(self) -> None:
        game = _no_host_game(
            room_code="mw",
            host_id=1,
            scenario_name="bazpors",
            players={
                1: _p(1, Role.MAFIA_BASIC),
                2: _p(2, Role.MAFIA_BOSS),
                3: _p(3, Role.CITIZEN),
            },
        )
        self.assertTrue(mafia_faction_wins(game, self.gm))
        self.assertFalse(mafia_citizen_equal(game, self.gm))

    def test_broadcast_html_includes_roles(self) -> None:
        game = _no_host_game(
            room_code="mw",
            host_id=1,
            scenario_name="bazpors",
            players={
                1: _p(1, Role.MAFIA_BASIC),
                2: _p(2, Role.CITIZEN, alive=False),
            },
        )
        announce = build_no_host_mafia_win_announce_html(game, self.gm)
        roster = build_no_host_all_players_roles_roster_html(game, self.gm)
        self.assertIn("برد مافیا", announce)
        self.assertIn("فهرست بازیکنان", roster)
        self.assertIn("مافیا", roster)
        self.assertIn("خارج‌شده", roster)

    def test_citizen_win_when_only_ruintan_mafia_team_dead(self) -> None:
        """رویین‌تن در شمار مافیا برای برد نیست — پس از حذف بقیهٔ تیم مافیا شهروند می‌برد."""
        game = _no_host_game(
            room_code="20",
            host_id=1,
            scenario_name="bazpors",
            players={
                10: _p(10, Role.RUINTAN),
                11: _p(11, Role.CITIZEN),
                12: _p(12, Role.DOCTOR),
            },
        )
        self.assertTrue(no_mafia_alive(game, self.gm))
        self.assertFalse(mafia_faction_wins(game, self.gm))

    def test_mafia_faction_wins_with_nato_alive(self) -> None:
        game = _no_host_game(
            room_code="mw",
            host_id=1,
            scenario_name="bazpors",
            players={
                1: _p(1, Role.NATO),
                2: _p(2, Role.CITIZEN),
            },
        )
        self.assertTrue(mafia_faction_wins(game, self.gm))
        self.assertFalse(no_mafia_alive(game, self.gm))
