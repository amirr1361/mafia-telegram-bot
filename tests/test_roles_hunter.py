"""تست منطق مشترک هانتر — bot/roles/hunter.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    Role,
    _apply_night_resolution,
    _eliminate_player,
    _effective_hunter_link_uid,
    _hunter_chain_companion_uid,
    hunter_chain_confirm_alert_text,
    hunter_chain_public_disclosure,
    process_narrator_callback,
    NIGHT_ACTIONS,
    NS_HUNTER,
)
from bot.game import GameManager
from bot.models import Game, Player
from bot.roles import hunter as hunter_mod
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


def _game_with_hunter() -> Game:
    return Game(
        room_code="hc",
        host_id=1,
        scenario_name="bazpors",
        players={
            1: _p(1, 1, "هانتر", Role.HUNTER),
            2: _p(2, 2, "مافیا", Role.MAFIA_BASIC),
            3: _p(3, 3, "رییس", Role.MAFIA_BOSS),
            4: _p(4, 4, "شهروند", Role.CITIZEN),
        },
    )


class HunterModuleCoreTests(unittest.TestCase):
    def test_find_alive_hunter(self) -> None:
        game = _game_with_hunter()
        self.assertEqual(hunter_mod.find_alive_hunter(game).user_id, 1)
        game.players[1].is_alive = False
        self.assertIsNone(hunter_mod.find_alive_hunter(game))

    def test_link_pool_excludes_self(self) -> None:
        game = _game_with_hunter()
        pool_ids = {p.user_id for p in hunter_mod.link_pool(game)}
        self.assertNotIn(1, pool_ids)
        self.assertIn(2, pool_ids)

    def test_commit_and_effective_link(self) -> None:
        game = _game_with_hunter()
        hunter_mod.commit_pick(game, 2)
        self.assertEqual(hunter_mod.effective_link_uid(game), 2)
        self.assertTrue(hunter_mod.linked_this_night(game))

    def test_commit_no_link(self) -> None:
        game = _game_with_hunter()
        hunter_mod.commit_pick(game, 2)
        hunter_mod.commit_no_link(game)
        self.assertFalse(hunter_mod.linked_this_night(game))
        self.assertIsNone(game.bazpors_hunter_report_link_uid)

    def test_chain_companion_mafia_not_boss(self) -> None:
        game = _game_with_hunter()
        hunter_mod.commit_pick(game, 2)
        self.assertEqual(hunter_mod.chain_companion_uid(game, 1), 2)
        game.bazpors_hunter_link_uid = 3
        self.assertIsNone(hunter_mod.chain_companion_uid(game, 1))

    def test_no_chain_to_citizen(self) -> None:
        game = _game_with_hunter()
        hunter_mod.commit_pick(game, 4)
        self.assertIsNone(hunter_mod.chain_companion_uid(game, 1))

    def test_mafia_shot_kills_hunter_linked_to_boss_only(self) -> None:
        game = _game_with_hunter()
        gm = GameManager()
        hunter_mod.commit_pick(game, 3)
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = 1
        _apply_night_resolution(game, gm)
        self.assertFalse(game.players[1].is_alive)
        self.assertTrue(game.players[3].is_alive)

    def test_eliminate_hunter_kills_linked_mafia_basic(self) -> None:
        game = _game_with_hunter()
        gm = GameManager()
        hunter_mod.commit_pick(game, 2)
        _eliminate_player(game, gm, 1)
        self.assertFalse(game.players[1].is_alive)
        self.assertFalse(game.players[2].is_alive)

    def test_effective_link_shim_matches_module(self) -> None:
        game = _game_with_hunter()
        game.bazpors_hunter_link_uid = None
        game.bazpors_hunter_report_link_uid = 2
        self.assertEqual(_effective_hunter_link_uid(game), 2)
        self.assertEqual(hunter_mod.effective_link_uid(game), 2)


class HunterSemiAutoPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_hp_commits_through_shared_module(self) -> None:
        game = make_semi_auto_game()
        game.players[-4] = _p(-5, 5, "H", Role.HUNTER)
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_HUNTER
        err = process_narrator_callback(game, self.gm, "hp", -3, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_hunter_link_uid, -3)
        self.assertTrue(game.bazpors_hunter_linked_this_night)


class HunterNoHostPathTests(unittest.TestCase):
    def test_apply_pick_shim(self) -> None:
        from bot.no_host_night1 import _apply_hunter_pick_to_game

        game = _game_with_hunter()
        _apply_hunter_pick_to_game(game, 2)
        self.assertEqual(hunter_mod.effective_link_uid(game), 2)


if __name__ == "__main__":
    unittest.main()
