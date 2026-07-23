"""تست post_game_flow و router پایان بازی."""

from __future__ import annotations

import unittest

from bot.post_game_flow import (
    EndGamePick,
    endgame_winner_keyboard,
    host_endgame_needs_abort_confirm,
)


class PostGameFlowTests(unittest.TestCase):
    def test_endgame_keyboard_uses_pick_callback(self) -> None:
        from bot.game import GameManager

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            host_full_name="h",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        kb = endgame_winner_keyboard(game)
        packed = kb.inline_keyboard[0][0].callback_data or ""
        self.assertIn("egw", packed)

    def test_abort_confirm_semi_auto_before_winner_pick(self) -> None:
        from bot.game import GameManager

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            host_full_name="h",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        game.roles_dealt = True
        game.host_may_pick_winner = False
        self.assertTrue(host_endgame_needs_abort_confirm(game))


if __name__ == "__main__":
    unittest.main()
