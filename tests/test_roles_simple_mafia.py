"""تست منطق مشترک مافیا ساده — bot/roles/simple_mafia.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_mafia_chooser import resolve_mafia_shot_chooser
from bot.roles import detective as det
from bot.roles import simple_mafia as maf_mod


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class SimpleMafiaModuleCoreTests(unittest.TestCase):
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

    def test_is_simple_mafia_role(self) -> None:
        self.assertTrue(maf_mod.is_simple_mafia_role(Role.MAFIA_BASIC))
        self.assertFalse(maf_mod.is_simple_mafia_role(Role.MAFIA_BOSS))

    def test_find_alive_simple_mafia(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        gm.add_player(game, _p(20, "B", Role.MAFIA_BOSS))
        found = maf_mod.find_alive_simple_mafia(game)
        self.assertEqual([p.user_id for p in found], [10])

    def test_mafia_aligned(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        self.assertTrue(maf_mod.is_mafia_aligned(game, game.players[10]))

    def test_detective_positive_for_simple_mafia(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        result = det.evaluate_inquiry(game, 10)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.POSITIVE)

    def test_boss_dead_simple_mafia_chooser_fallback(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        gm.add_player(
            game,
            _p(20, "B", Role.MAFIA_BOSS, alive=False),
        )
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 10)

    def test_hunter_chain_eliminates_simple_mafia_link(self) -> None:
        from bot.roles.mafia_boss import hunter_chain_eliminates_link

        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        self.assertTrue(
            hunter_chain_eliminates_link(game, game.players[10])
        )

    def test_has_mafia_team_member_alive(self) -> None:
        game = self._game()
        gm = GameManager()
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        self.assertTrue(maf_mod.has_mafia_team_member_alive(game))


if __name__ == "__main__":
    unittest.main()
