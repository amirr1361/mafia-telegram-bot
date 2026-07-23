"""پاک‌سازی آینهٔ پنل‌ها در شروع شب جدید."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_mirror_reset import reset_no_host_night_mirror_prompts
from bot.no_host_phase import reset_no_host_per_night_role_state
from bot.observer_delivery import mirror_ui_claim_key


class NoHostMirrorResetTests(unittest.TestCase):
    def test_reset_clears_mirror_prompts(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        key = mirror_ui_claim_key(game.room_code, "night1_mafia", -1)
        game.mirror_prompt_messages[key] = {"text": "old", "observer": (99, 1)}
        game.mirror_action_claims["x"] = 1
        reset_no_host_night_mirror_prompts(game)
        self.assertEqual(game.mirror_prompt_messages, {})
        self.assertEqual(game.mirror_action_claims, {})

    def test_per_night_role_reset_includes_mirror_clear(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(-1, "M", None, Role.NATO, seat=1, is_alive=True)
        )
        game.mirror_prompt_messages["k"] = {"text": "t"}
        reset_no_host_per_night_role_state(game)
        self.assertEqual(game.mirror_prompt_messages, {})


if __name__ == "__main__":
    unittest.main()
