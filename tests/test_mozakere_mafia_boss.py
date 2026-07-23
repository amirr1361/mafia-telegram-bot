"""قوانین رئیس مافیا در سناریوی مذاکره — جدا از بازپرس."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Game, Player, Role
from bot.roles import detective as det
from bot.roles import mafia_boss as boss_mod
from bot.roles import sniper as sniper_mod
from bot.no_host_mafia_chooser import (
    resolve_mafia_night1_panel_recipients,
    resolve_mafia_shot_chooser,
    should_start_shiad_direct_shot_menu,
)


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class MozakereMafiaBossTests(unittest.TestCase):
    def _mozakere_game(self, *, n: int = 12) -> Game:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=n,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        return game

    def test_boss_in_mozakere_roster(self) -> None:
        from bot.game import mozakere_roles_for_count

        for n in (10, 11, 12, 13, 15):
            roles = mozakere_roles_for_count(n)
            self.assertIn(Role.MAFIA_BOSS, roles)

    def test_boss_is_mafia_team(self) -> None:
        self.assertTrue(is_mafia_team(Role.MAFIA_BOSS))

    def test_shot_chooser_is_boss_not_nato_or_shiad(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "Sh", Role.SHIAD))
        gm.add_player(game, _p(20, "N", Role.NATO))
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(40, "M", Role.MAFIA_NEGOTIATOR))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 30)
        self.assertTrue(boss_mod.is_mafia_shot_decider(game, ch))

    def test_shot_chooser_fallback_when_boss_dead(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(40, "M", Role.MAFIA_NEGOTIATOR))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 40)

    def test_night1_panel_only_shot_decider(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(40, "M", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(50, "S", Role.MAFIA_SIMPLE))
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [30])

    def test_no_shiad_direct_shot_menu(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "Sh", Role.SHIAD))
        self.assertFalse(should_start_shiad_direct_shot_menu(game))

    def test_yakuzai_not_allowed(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        for uid in (30, 40, 50, 60, 70):
            gm.add_player(game, _p(uid, f"C{uid}", Role.CITIZEN))
        self.assertFalse(boss_mod.yakuzai_allowed(game, gm))
        self.assertIsNone(boss_mod.yaku_boss_uid(game))

    def test_detective_reads_boss_negative(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "D", Role.DETECTIVE))
        result = det.evaluate_inquiry(game, 10)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)
        self.assertFalse(result.is_positive)

    def test_sniper_cannot_kill_boss(self) -> None:
        boss = _p(10, "B", Role.MAFIA_BOSS)
        self.assertTrue(boss_mod.sniper_boss_immune(boss))
        self.assertTrue(sniper_mod.boss_immune(boss))

    def test_sniper_resolution_skips_boss_kill(self) -> None:
        game = self._mozakere_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "S", Role.SNIPER))
        from bot.roles.night_state import sniper_night_state

        sniper_night_state(game).night_target_uid = 10
        sniper_mod.apply_night_resolution(game, gm)
        self.assertTrue(game.players[10].is_alive)

    def test_bazpors_shot_chooser_unchanged(self) -> None:
        """بازپرس هنوز ناتو را قبل از شیاد ترجیح می‌دهد."""
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, "Sh", Role.SHIAD))
        gm.add_player(game, _p(20, "N", Role.NATO))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 20)


if __name__ == "__main__":
    unittest.main()
