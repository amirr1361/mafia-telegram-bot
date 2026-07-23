"""پاک‌سازی پیام‌های پنل پس از resolve شب."""

from __future__ import annotations

import unittest

from bot.bazpors_night_panel_purge import (
    clear_tracked_panel_message_state,
    collect_tracked_panel_message_refs,
    night_panel_purge_recipient_uids,
)
from bot.game import GameManager
from bot.models import Player, Role


class BazporsNightPanelPurgeTests(unittest.TestCase):
    def test_collect_refs_from_mirror_and_panels(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.mirror_prompt_messages["k1"] = {
            "text": "t",
            "player": (100, 11),
            "observer": (200, 22),
        }
        game.no_host_mafia_night1_refs[-1] = (100, 33, "m")
        game.bazpors_assistant_panel_refs["step"] = (300, 44)
        game.bazpors_observer_narrator_mirror_refs["m"] = (200, 55)
        game.bazpors_assistant_panel_chat_id = 300
        game.bazpors_assistant_panel_message_id = 66

        refs = collect_tracked_panel_message_refs(game)
        self.assertEqual(
            set(refs),
            {(100, 11), (200, 22), (100, 33), (300, 44), (200, 55), (300, 66)},
        )

    def test_recipients_alive_observer_assistant(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 50
        game.observer_user_id = 60
        game.no_host_assistant_narrator_active = True
        gm.add_player(
            game, Player(10, "A", None, Role.CITIZEN, seat=1, is_alive=True)
        )
        gm.add_player(
            game, Player(20, "B", None, Role.MAFIA_BASIC, seat=2, is_alive=False)
        )
        uids = night_panel_purge_recipient_uids(game)
        self.assertIn(10, uids)
        self.assertNotIn(20, uids)
        self.assertIn(50, uids)
        self.assertIn(60, uids)

    def test_clear_tracked_state(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
        )
        assert game is not None
        game.mirror_prompt_messages["x"] = {"text": "t"}
        game.mirror_action_claims["x"] = 1
        game.bazpors_assistant_panel_chat_id = 1
        game.bazpors_assistant_panel_message_id = 2
        clear_tracked_panel_message_state(game)
        self.assertEqual(game.mirror_prompt_messages, {})
        self.assertEqual(game.mirror_action_claims, {})
        self.assertIsNone(game.bazpors_assistant_panel_chat_id)


if __name__ == "__main__":
    unittest.main()
