"""زنجیره مجری مافیا: رئیس → ناتو → شیاد."""

from __future__ import annotations

import unittest

from bot.game import GameManager, apply_bazpors_yakuzai_recruit
from bot.models import Player, Role
from bot.no_host_mafia_chooser import (
    resolve_mafia_night1_panel_recipients,
    resolve_mafia_shot_chooser,
    should_start_shiad_direct_shot_menu,
)


class NoHostMafiaChooserTest(unittest.TestCase):
    def test_shot_chooser_boss_then_nato_then_shiad(self) -> None:
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
            Player(user_id=10, full_name="Sh", username=None, role=Role.SHIAD),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="N", username=None, role=Role.NATO),
        )
        gm.add_player(
            game,
            Player(user_id=30, full_name="B", username=None, role=Role.MAFIA_BOSS),
        )
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 30)

        gm2 = GameManager()
        game2 = gm2.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game2 is not None
        gm2.add_player(
            game2,
            Player(user_id=10, full_name="Sh", username=None, role=Role.SHIAD),
        )
        gm2.add_player(
            game2,
            Player(user_id=20, full_name="N", username=None, role=Role.NATO),
        )
        ch2 = resolve_mafia_shot_chooser(game2)
        assert ch2 is not None
        self.assertEqual(ch2.user_id, 20)

    def test_direct_shot_when_no_boss_no_nato(self) -> None:
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
            Player(user_id=10, full_name="Sh", username=None, role=Role.SHIAD),
        )
        self.assertTrue(should_start_shiad_direct_shot_menu(game))
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [10])

    def test_yaku_recruit_panel_when_all_classic_mafia_dead(self) -> None:
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
            Player(
                user_id=10,
                full_name="Boss",
                username=None,
                role=Role.MAFIA_BOSS,
                is_alive=False,
            ),
        )
        gm.add_player(
            game,
            Player(
                user_id=20,
                full_name="Nato",
                username=None,
                role=Role.NATO,
                is_alive=False,
            ),
        )
        gm.add_player(
            game,
            Player(
                user_id=30,
                full_name="Recruit",
                username=None,
                role=Role.CITIZEN,
            ),
        )
        game.bazpors_yakuzai_used = True
        apply_bazpors_yakuzai_recruit(game, game.players[30])
        self.assertEqual(game.players[30].role, Role.MAFIA_BASIC)

        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [30])
        chooser = resolve_mafia_shot_chooser(game)
        assert chooser is not None
        self.assertEqual(chooser.user_id, 30)


if __name__ == "__main__":
    unittest.main()
