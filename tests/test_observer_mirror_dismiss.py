"""بستن پیام بازیکن وقتی ناظر به‌جای او انتخاب می‌کند."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Player
from bot.observer_delivery import (
    apply_mirror_claim_winner,
    dismiss_player_mirror_prompt,
    mirror_ui_claim_key,
    register_mirror_prompt_pair,
)


class ObserverMirrorDismissTest(unittest.IsolatedAsyncioTestCase):
    async def test_dismiss_edits_player_message(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=100, full_name="Assistant", username=None)
        )
        game.observer_user_id = 999
        game.observer_full_name = "Observer"
        game.observer_prompt_status = "registered"
        ui_key = mirror_ui_claim_key(game.room_code, "intro_night_start", 100)
        game.mirror_prompt_messages[ui_key] = {
            "text": "روز معارفه",
            "player": (100, 42),
        }
        bot = AsyncMock()
        await dismiss_player_mirror_prompt(bot, game, ui_key, 100)
        bot.edit_message_text.assert_called_once()
        args, kwargs = bot.edit_message_text.call_args
        self.assertEqual(kwargs["chat_id"], 100)
        self.assertEqual(kwargs["message_id"], 42)
        self.assertIsNone(kwargs["reply_markup"])
        self.assertIn("به‌جای شما", kwargs["text"])

    async def test_apply_mirror_claim_observer_dismisses_player(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.observer_user_id = 999
        game.observer_prompt_status = "registered"
        ui_key = "test:01:100"
        game.mirror_prompt_messages[ui_key] = {
            "text": "انتخاب",
            "player": (100, 1),
            "observer": (999, 2),
        }
        bot = AsyncMock()
        await apply_mirror_claim_winner(bot, game, ui_key, 999, 100)
        bot.edit_message_text.assert_called_once()


if __name__ == "__main__":
    unittest.main()
