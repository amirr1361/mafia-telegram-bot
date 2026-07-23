"""تست منطق مشترک رویین‌تن — bot/roles/ruintan.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import mafia_shot_allowed
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_night_resolve import _apply_no_host_night_resolution
from bot.roles import detective as det
from bot.roles import nato as nato_mod
from bot.roles import ruintan as ru_mod


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _game_with_ruintan(*, player_count: int = 12) -> Game:
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=player_count,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    gm.add_player(game, _p(10, "Ru", Role.RUINTAN))
    gm.add_player(game, _p(20, "M", Role.MAFIA_BASIC))
    gm.add_player(game, _p(30, "C", Role.CITIZEN))
    return game


class RuintanModuleCoreTests(unittest.TestCase):
    def test_find_alive_ruintan(self) -> None:
        game = _game_with_ruintan()
        self.assertEqual(ru_mod.find_alive_ruintan(game).user_id, 10)

    def test_mafia_shot_survives(self) -> None:
        game = _game_with_ruintan()
        self.assertTrue(ru_mod.mafia_shot_survives(game.players[10]))
        self.assertFalse(ru_mod.mafia_shot_survives(game.players[30]))

    def test_mafia_shot_not_allowed_when_only_ruintan_alive(self) -> None:
        game = _game_with_ruintan()
        game.players[20].is_alive = False
        game.players[30].is_alive = False
        self.assertFalse(ru_mod.mafia_shot_allowed(game))
        self.assertFalse(mafia_shot_allowed(game))

    def test_yaku_succeeds_12_player_not_13(self) -> None:
        self.assertTrue(ru_mod.yaku_negotiation_succeeds(Role.RUINTAN, player_count=12))
        self.assertFalse(ru_mod.yaku_negotiation_succeeds(Role.RUINTAN, player_count=13))

    def test_nato_can_guess_ruintan(self) -> None:
        game = _game_with_ruintan()
        gm = GameManager()
        roles = nato_mod.guess_roles_in_room(game)
        self.assertIn(Role.RUINTAN, roles)
        self.assertTrue(ru_mod.is_nato_guessable_role(Role.RUINTAN))

    def test_detective_negative_town(self) -> None:
        game = _game_with_ruintan()
        result = det.evaluate_inquiry(game, 10)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_TOWN)

    def test_night_resolve_ruintan_survives_mafia_shot(self) -> None:
        game = _game_with_ruintan()
        gm = GameManager()
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = 10
        _apply_no_host_night_resolution(game, gm)
        self.assertTrue(game.players[10].is_alive)


class RuintanNoHostPathTests(unittest.TestCase):
    def test_find_via_shim(self) -> None:
        from bot.no_host_ruintan_night import start_no_host_ruintan_night_flow

        game = _game_with_ruintan()
        game.bazpors_narrator_step = "night_start"
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 1
        self.assertIsNotNone(ru_mod.find_alive_ruintan(game))
        self.assertFalse(game.no_host_ruintan_night_confirmed)


if __name__ == "__main__":
    unittest.main()
