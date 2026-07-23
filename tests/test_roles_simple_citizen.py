"""تست منطق مشترک شهروند ساده — bot/roles/simple_citizen.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.chaos_handshake import decide_chaos_winner
from bot.game import GameManager, apply_bazpors_yakuzai_recruit
from bot.models import Game, Player, Role
from bot.roles import detective as det
from bot.roles import nato as nato_mod
from bot.roles import simple_citizen as cit_mod


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class SimpleCitizenModuleCoreTests(unittest.TestCase):
    def _game(self) -> Game:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        return game

    def test_is_simple_citizen(self) -> None:
        self.assertTrue(cit_mod.is_simple_citizen_role(Role.CITIZEN))
        self.assertFalse(cit_mod.is_simple_citizen_role(Role.DOCTOR))

    def test_find_alive_simple_citizens(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "C1", Role.CITIZEN))
        gm.add_player(game, _p(20, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(30, "C2", Role.CITIZEN, alive=False))
        alive = cit_mod.find_alive_simple_citizens(game)
        self.assertEqual([p.user_id for p in alive], [10])

    def test_has_no_night_action(self) -> None:
        self.assertFalse(cit_mod.has_night_action())

    def test_not_nato_guessable(self) -> None:
        self.assertFalse(cit_mod.is_nato_guessable_role(Role.CITIZEN))
        self.assertNotIn(Role.CITIZEN, nato_mod.guess_roles_in_room(self._game()))

    def test_yaku_always_succeeds(self) -> None:
        self.assertTrue(cit_mod.yaku_negotiation_succeeds(Role.CITIZEN, player_count=12))

    def test_detective_negative_town(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "C", Role.CITIZEN))
        result = det.evaluate_inquiry(game, 10)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_TOWN)
        self.assertTrue(cit_mod.reads_as_town_for_detective(game, game.players[10]))

    def test_chaos_citizen_team(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "C", Role.CITIZEN))
        gm.add_player(game, _p(20, "M", Role.MAFIA_BASIC))
        self.assertTrue(cit_mod.counts_as_chaos_citizen_team(game, 10))
        self.assertFalse(cit_mod.counts_as_chaos_citizen_team(game, 20))

    def test_chaos_mutual_citizens_win(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "C1", Role.CITIZEN))
        gm.add_player(game, _p(20, "C2", Role.CITIZEN))
        gm.add_player(game, _p(30, "M", Role.MAFIA_BASIC))
        out = decide_chaos_winner(game, {10: 20, 20: 10, 30: 10})
        self.assertEqual(out["winner"], "citizens")

    def test_yaku_recruit_converts_citizen(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "C", Role.CITIZEN))
        apply_bazpors_yakuzai_recruit(game, game.players[10])
        self.assertEqual(game.players[10].role, Role.MAFIA_BASIC)
        self.assertFalse(cit_mod.is_simple_citizen(game.players[10]))


class SimpleCitizenNoHostPathTests(unittest.TestCase):
    def test_alive_citizens_shim(self) -> None:
        from bot.no_host_citizen_night import _alive_citizens

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="C1", username=None, role=Role.CITIZEN),
        )
        self.assertEqual(
            [p.user_id for p in _alive_citizens(game)],
            cit_mod.alive_simple_citizen_uids(game),
        )


if __name__ == "__main__":
    unittest.main()
