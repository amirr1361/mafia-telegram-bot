"""شب ۱ — انتخاب عملیات مافیا (no_host)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_SHOT,
    build_no_host_mafia_night1_confirm_html,
    build_no_host_mafia_night1_menu_html,
    mafia_night1_act_active,
    resolve_mafia_night1_panel_recipients,
)


def _game_night(nc: int = 1) -> "Game":
    from bot.models import Game

    g = Game(room_code="01", host_id=1, scenario_name="bazpors")
    g.bazpors_narrator_night_count = nc
    return g


class NoHostMafiaNight1Test(unittest.TestCase):
    def test_menu_html(self) -> None:
        text = build_no_host_mafia_night1_menu_html(_game_night(1))
        self.assertIn("شب اول", text)
        self.assertIn("تیم مافیا", text)

    def test_confirm_html(self) -> None:
        text = build_no_host_mafia_night1_confirm_html(_game_night(1), MAFIA_ACTION_SHOT)
        self.assertIn("مطمئن", text)
        self.assertIn("شات", text)

    def test_mafia_acts(self) -> None:
        self.assertTrue(mafia_night1_act_active(None, "nms"))
        self.assertFalse(mafia_night1_act_active(None, "hnp"))

    def test_panel_boss_alive_only_boss(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS)
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Nato", username=None, role=Role.NATO),
        )
        gm.add_player(
            game,
            Player(
                user_id=30,
                full_name="Simple",
                username=None,
                role=Role.MAFIA_BASIC,
            ),
        )
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [10])

    def test_panel_all_non_simple_if_boss_dead(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS, is_alive=False),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        gm.add_player(
            game,
            Player(user_id=25, full_name="Shiad", username=None, role=Role.SHIAD),
        )
        gm.add_player(
            game,
            Player(
                user_id=30,
                full_name="Simple",
                username=None,
                role=Role.MAFIA_BASIC,
            ),
        )
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [20])

    def test_panel_all_simple_if_only_simple_remain(self) -> None:
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
                user_id=30,
                full_name="Simple1",
                username=None,
                role=Role.MAFIA_BASIC,
            ),
        )
        gm.add_player(
            game,
            Player(
                user_id=31,
                full_name="Simple2",
                username=None,
                role=Role.MAFIA_SIMPLE,
            ),
        )
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual(sorted(p.user_id for p in panel), [30, 31])


if __name__ == "__main__":
    unittest.main()
