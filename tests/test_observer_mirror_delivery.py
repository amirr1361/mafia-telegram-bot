"""آینهٔ پیام بازیکنان برای ناظر و claim اولین کلیک."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.game import role_label_fa
from bot.observer_delivery import (
    game_observer_mirror_active,
    mirror_ui_claim_key,
    no_host_observer_registered,
    observer_player_copy_prefix,
    try_claim_mirror_ui,
)


class ObserverMirrorDeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _no_host_with_observer(self) -> tuple:
        game = self.gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=100, full_name="Creator", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=200, full_name="P2", username=None)
        )
        self.gm.ensure_observer_code(game)
        game.observer_prompt_status = "registered"
        game.observer_user_id = 300
        game.observer_full_name = "Obs"
        return game

    def test_mirror_inactive_without_registration(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(game_observer_mirror_active(game))

    def test_mirror_active_when_registered(self) -> None:
        game = self._no_host_with_observer()
        self.assertTrue(game_observer_mirror_active(game))

    def test_mirror_active_when_code_sent_but_observer_id_set(self) -> None:
        game = self._no_host_with_observer()
        game.observer_prompt_status = "code_sent"
        self.assertTrue(game_observer_mirror_active(game))

    def test_first_click_wins_between_player_and_observer(self) -> None:
        game = self._no_host_with_observer()
        key = mirror_ui_claim_key(game.room_code, "player_end_vote", 200)
        self.assertIsNone(try_claim_mirror_ui(game, key, 300, 200))
        self.assertEqual(game.mirror_action_claims[key], 300)
        self.assertEqual(
            try_claim_mirror_ui(game, key, 200, 200),
            "already_claimed",
        )

    def test_observer_cannot_claim_other_players_ui_without_mirror(self) -> None:
        game = self._no_host_with_observer()
        game.observer_prompt_status = "pending"
        game.observer_user_id = None
        key = mirror_ui_claim_key(game.room_code, "player_end_vote", 200)
        self.assertEqual(
            try_claim_mirror_ui(game, key, 300, 200),
            "forbidden",
        )

    def test_observer_copy_prefix_includes_role(self) -> None:
        game = self._no_host_with_observer()
        p = game.players[200]
        p.seat = 5
        p.role = Role.HUNTER
        prefix = observer_player_copy_prefix(game, 200)
        self.assertIn("ناظر — پیام صندلی", prefix)
        self.assertIn("P2", prefix)
        self.assertIn(role_label_fa(Role.HUNTER), prefix)

    def test_observer_copy_prefix_unknown_role(self) -> None:
        game = self._no_host_with_observer()
        p = game.players[200]
        p.seat = 3
        p.role = None
        prefix = observer_player_copy_prefix(game, 200)
        self.assertIn("نقش نامشخص", prefix)


if __name__ == "__main__":
    unittest.main()
