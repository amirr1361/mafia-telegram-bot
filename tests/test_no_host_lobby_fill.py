"""لابی «گردانندگی بدون گرداننده»: سازنده بازیکن + پر کردن بقیهٔ ظرفیت."""

from __future__ import annotations

import unittest

from bot.game import (
    SYNTHETIC_PLAYER_NAME_POOL,
    GameManager,
    draw_unique_synthetic_player_names,
    is_synthetic_player_uid,
    role_label_fa,
)
from bot.main import (
    build_private_role_message_html,
    build_shuffle_confirm_prompt_html,
    host_receives_moderator_deal_messages,
    players_receive_post_deal_hub_message,
)
from bot.models import Player, Role


class NoHostLobbyFillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_fill_keeps_creator_and_fills_remaining(self) -> None:
        creator_id = 108214166
        game = self.gm.create_game(
            host_id=creator_id,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        err = self.gm.add_player(
            game,
            Player(
                user_id=creator_id,
                full_name="سازنده",
                username="creator",
            ),
        )
        self.assertIsNone(err)
        self.assertEqual(len(game.players), 1)

        fill_err = self.gm.fill_bazpors_no_host_synthetic_lobby(game)
        self.assertIsNone(fill_err)
        self.assertEqual(len(game.players), 12)
        self.assertIn(creator_id, game.players)
        self.assertTrue(game.players[creator_id].is_alive)
        self.assertFalse(is_synthetic_player_uid(creator_id))
        synth_ids = [u for u in game.players if is_synthetic_player_uid(u)]
        self.assertEqual(len(synth_ids), 11)
        synth_names = [
            game.players[u].full_name for u in synth_ids if u in game.players
        ]
        self.assertEqual(len(synth_names), len(set(synth_names)))
        for name in synth_names:
            self.assertIn(name, SYNTHETIC_PLAYER_NAME_POOL)

    def test_fill_with_extra_real_player(self) -> None:
        creator_id = 100
        game = self.gm.create_game(
            host_id=creator_id,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=creator_id, full_name="A", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=200, full_name="B", username=None)
        )
        self.assertIsNone(self.gm.fill_bazpors_no_host_synthetic_lobby(game))
        self.assertEqual(len(game.players), 10)
        self.assertEqual(
            sum(1 for u in game.players if not is_synthetic_player_uid(u)), 2
        )

    def test_no_host_skips_moderator_post_deal_messages(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(host_receives_moderator_deal_messages(game))
        self.assertFalse(players_receive_post_deal_hub_message(game))

    def test_no_host_shuffle_prompt_hides_seat_list(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=1, full_name="A", username=None)
        )
        self.assertIsNone(self.gm.fill_bazpors_no_host_synthetic_lobby(game))
        rows = self.gm.prepare_shuffle(game)
        html_msg = build_shuffle_confirm_prompt_html(game, rows)
        self.assertIn("شماره صندلی", html_msg)
        self.assertIn("تایید", html_msg)
        self.assertNotIn("🪑", html_msg)

    def test_no_host_private_role_message_text(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        html_msg = build_private_role_message_html(game, Role.SHIAD)
        self.assertIn("بازی بدون گرداننده برگزار می‌شود", html_msg)
        self.assertNotIn("گرداننده انجام می‌شود", html_msg)
        self.assertIn("شیاد", html_msg)

    def test_semi_auto_fill_keeps_real_host_and_fills_rest(self) -> None:
        host_id = 501
        game = self.gm.create_game(
            host_id=host_id,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=host_id, full_name="گرداننده", username=None)
        )
        self.assertIsNone(self.gm.fill_bazpors_semi_auto_synthetic_lobby(game))
        self.assertEqual(len(game.players), 12)
        self.assertIn(host_id, game.players)
        self.assertFalse(is_synthetic_player_uid(host_id))
        self.assertEqual(
            sum(1 for u in game.players if is_synthetic_player_uid(u)), 11
        )

    def test_semi_auto_fill_uses_unique_pool_names(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.assertIsNone(self.gm.fill_bazpors_semi_auto_synthetic_lobby(game))
        names = [p.full_name for p in game.players.values()]
        self.assertEqual(len(names), 10)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(set(names).issubset(set(SYNTHETIC_PLAYER_NAME_POOL)))

    def test_synthetic_names_include_role_after_deal(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.assertIsNone(self.gm.fill_bazpors_semi_auto_synthetic_lobby(game))
        self.gm.assign_roles(game)
        for p in game.players.values():
            if not is_synthetic_player_uid(p.user_id):
                continue
            self.assertIsNotNone(p.role)
            base = p.full_name.split("-", 1)[0]
            self.assertIn(base, SYNTHETIC_PLAYER_NAME_POOL)
            role_part = p.full_name.split("-", 1)[1]
            self.assertEqual(role_part, role_label_fa(p.role))

    def test_draw_unique_names_never_repeats_within_count(self) -> None:
        names = draw_unique_synthetic_player_names(12)
        self.assertEqual(len(names), 12)
        self.assertEqual(len(names), len(set(names)))

    def test_semi_auto_still_skips_player_hub(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.assertTrue(host_receives_moderator_deal_messages(game))
        self.assertFalse(players_receive_post_deal_hub_message(game))


if __name__ == "__main__":
    unittest.main()
