"""تست منطق مشترک رئیس مافیا — bot/roles/mafia_boss.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.game import GameManager, apply_bazpors_yakuzai_recruit
from bot.models import Game, Player, Role
from bot.roles import detective as det
from bot.roles import mafia_boss as boss_mod
from bot.no_host_mafia_chooser import (
    resolve_mafia_night1_panel_recipients,
    resolve_mafia_shot_chooser,
    should_start_shiad_direct_shot_menu,
)
from bot.no_host_mafia_yaku import (
    no_host_yaku_boss_actor_may_act,
    resolve_no_host_yaku_boss_uid,
)


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


class MafiaBossModuleCoreTests(unittest.TestCase):
    def _no_host_game(self) -> Game:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        return game

    def test_find_alive_boss(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        self.assertEqual(boss_mod.find_alive_boss(game).user_id, 30)

    def test_shot_chooser_boss_then_nato_then_shiad(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "Sh", Role.SHIAD))
        gm.add_player(game, _p(20, "N", Role.NATO))
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 30)

        game2 = self._no_host_game()
        gm2 = GameManager()
        gm2.add_player(game2, _p(10, "Sh", Role.SHIAD))
        gm2.add_player(game2, _p(20, "N", Role.NATO))
        ch2 = resolve_mafia_shot_chooser(game2)
        assert ch2 is not None
        self.assertEqual(ch2.user_id, 20)

    def test_night1_panel_boss_only(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "Sh", Role.SHIAD))
        gm.add_player(game, _p(20, "N", Role.NATO))
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [30])

    def test_direct_shot_when_no_boss_no_nato(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "Sh", Role.SHIAD))
        self.assertTrue(should_start_shiad_direct_shot_menu(game))
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [10])

    def test_yaku_recruit_panel_when_all_classic_mafia_dead(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(
            game,
            _p(10, "Boss", Role.MAFIA_BOSS, alive=False),
        )
        gm.add_player(
            game,
            _p(20, "Nato", Role.NATO, alive=False),
        )
        gm.add_player(game, _p(30, "Recruit", Role.CITIZEN))
        game.bazpors_yakuzai_used = True
        apply_bazpors_yakuzai_recruit(game, game.players[30])
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [30])

    def test_yakuzai_allowed_requires_boss(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "M", Role.MAFIA))
        for uid in (30, 40, 50, 60, 70):
            gm.add_player(game, _p(uid, f"C{uid}", Role.CITIZEN))
        self.assertTrue(boss_mod.yakuzai_allowed(game, gm))

        game2 = self._no_host_game()
        gm2 = GameManager()
        gm2.add_player(game2, _p(20, "M", Role.MAFIA))
        for uid in (30, 40, 50, 60, 70):
            gm2.add_player(game2, _p(uid, f"C{uid}", Role.CITIZEN))
        self.assertFalse(boss_mod.yakuzai_allowed(game2, gm2))

    def test_yaku_sacrifice_pool_excludes_boss_when_multiple_mafia(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "M", Role.MAFIA))
        pool = boss_mod.yaku_sacrifice_pool(game)
        self.assertEqual([p.user_id for p in pool], [20])

    def test_hunter_chain_skips_boss_link(self) -> None:
        game = self._no_host_game()
        boss = _p(10, "B", Role.MAFIA_BOSS)
        mafia = _p(20, "M", Role.MAFIA)
        self.assertFalse(boss_mod.hunter_chain_eliminates_link(game, boss))
        self.assertTrue(boss_mod.hunter_chain_eliminates_link(game, mafia))

    def test_sniper_boss_immune(self) -> None:
        boss = _p(10, "B", Role.MAFIA_BOSS)
        mafia = _p(20, "M", Role.MAFIA)
        self.assertTrue(boss_mod.sniper_boss_immune(boss))
        self.assertFalse(boss_mod.sniper_boss_immune(mafia))

    def test_detective_reads_boss_negative(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        result = det.evaluate_inquiry(game, 10)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)

    def test_yaku_boss_uid_and_actor(self) -> None:
        game = self._no_host_game()
        gm = GameManager()
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        self.assertEqual(resolve_no_host_yaku_boss_uid(game), 10)
        self.assertTrue(no_host_yaku_boss_actor_may_act(game, 10, 10))
        self.assertFalse(no_host_yaku_boss_actor_may_act(game, 99, 10))


if __name__ == "__main__":
    unittest.main()
