"""شب ۱ — انتخاب هدف شات مافیا (no_host)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import NS_MAFIA_SHOT
from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.no_host_mafia_night1 import _mafia_night1_ui_key
from bot.no_host_mafia_shot import (
    _apply_shot_target_to_game,
    _mafia_shot_mirror_ui_key,
    _mafia_shot_ui_key,
    build_no_host_mafia_shot_confirm_html,
    build_no_host_mafia_shot_pick_html,
    build_no_host_mafia_shot_team_html,
    mafia_shot_act_active,
)


class NoHostMafiaShotTest(unittest.TestCase):
    def test_pick_html(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 2
        text = build_no_host_mafia_shot_pick_html(game)
        self.assertIn("هدف شات", text)
        self.assertIn("شب دوم", text)
        self.assertIn("حداقل", text)

    def test_shot_acts(self) -> None:
        self.assertTrue(mafia_shot_act_active(None, "msk"))
        self.assertFalse(mafia_shot_act_active(None, "nms"))

    def test_shot_mirror_ui_key_reuses_night1_panel(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        mafia_uid = -11
        n1_key = _mafia_night1_ui_key(game, mafia_uid)
        game.mirror_prompt_messages[n1_key] = {"player": 1, "observer": 2}
        self.assertEqual(_mafia_shot_mirror_ui_key(game, mafia_uid), n1_key)
        game.mirror_prompt_messages.clear()
        self.assertEqual(
            _mafia_shot_mirror_ui_key(game, mafia_uid),
            _mafia_shot_ui_key(game, mafia_uid),
        )

    def test_apply_shot_target(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Citizen", username=None, role=Role.CITIZEN),
        )
        game.phase = Phase.NIGHT
        game.bazpors_night_substep = NS_MAFIA_SHOT
        _apply_shot_target_to_game(game, 20)
        self.assertEqual(game.actions.mafia_target, 20)
        self.assertTrue(game.bazpors_mafia_shot_registered)

    def test_team_html(self) -> None:
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
            Player(user_id=20, full_name="Target", username=None, role=Role.CITIZEN),
        )
        text = build_no_host_mafia_shot_team_html(game, gm, 20)
        self.assertIn("تیم شما شات کرد", text)
        self.assertIn("Target", text)

    def test_confirm_html(self) -> None:
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
            Player(user_id=20, full_name="Target", username=None, role=Role.CITIZEN),
        )
        text = build_no_host_mafia_shot_confirm_html(game, gm, 20)
        self.assertIn("تأیید", text)
        self.assertIn("Target", text)


if __name__ == "__main__":
    unittest.main()
