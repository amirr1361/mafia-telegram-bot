"""لابی مذاکره — پر کردن تصادفی، شافل صندلی و پخش نقش."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_synthetic_player_uid
from bot.main import (
    build_seat_assignment_player_message,
    build_shuffle_confirm_prompt_html,
    bump_seat_shuffle_count,
    host_receives_moderator_deal_messages,
    players_receive_post_deal_hub_message,
)
from bot.models import Player
from bot.room_mode import is_no_host_player_room


class MozakereLobbyFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _mozakere_no_host(self, *, max_players: int, creator_id: int = 9001):
        game = self.gm.create_game(
            host_id=creator_id,
            scenario_name="mozakere",
            max_players=max_players,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=creator_id, full_name="Host", username="host")
        )
        return game

    def test_fill_synthetic_for_all_counts(self) -> None:
        for n in (10, 11, 12, 13, 15):
            with self.subTest(players=n):
                game = self._mozakere_no_host(max_players=n, creator_id=8000 + n)
                err = self.gm.fill_no_host_synthetic_lobby(game)
                self.assertIsNone(err)
                self.assertEqual(len(game.players), n)
                self.assertEqual(
                    sum(1 for uid in game.players if not is_synthetic_player_uid(uid)),
                    1,
                )

    def test_shuffle_prompt_hides_names(self) -> None:
        game = self._mozakere_no_host(max_players=11)
        self.gm.fill_no_host_synthetic_lobby(game)
        rows = self.gm.prepare_shuffle(game)
        bump_seat_shuffle_count(game)
        html_msg = build_shuffle_confirm_prompt_html(game, rows)
        self.assertIn("۱ بار", html_msg)
        self.assertIn("تایید", html_msg)
        self.assertNotIn("🪑", html_msg)

    def test_seat_list_shows_mozakere_scenario(self) -> None:
        game = self._mozakere_no_host(max_players=11)
        self.gm.fill_no_host_synthetic_lobby(game)
        self.gm.prepare_shuffle(game)
        text = build_seat_assignment_player_message(game)
        self.assertIn("سناریو: مذاکره", text)
        self.assertIn("تعداد: ۱۱ نفر", text)
        self.assertIn("لیست بازیکنها به ترتیب شماره صندلی", text)
        numbered = [
            ln
            for ln in text.splitlines()
            if ln.strip() and ln.strip()[0] in "0123456789۰۱۲۳۴۵۶۷۸۹"
        ]
        self.assertEqual(len(numbered), 11)

    def test_reshuffle_increments_counter(self) -> None:
        game = self._mozakere_no_host(max_players=10)
        self.gm.fill_no_host_synthetic_lobby(game)
        self.gm.prepare_shuffle(game)
        bump_seat_shuffle_count(game)
        self.gm.prepare_shuffle(game)
        bump_seat_shuffle_count(game)
        html_msg = build_shuffle_confirm_prompt_html(game, [])
        self.assertIn("۲ بار", html_msg)

    def test_no_host_room_flags(self) -> None:
        game = self._mozakere_no_host(max_players=10)
        self.assertTrue(is_no_host_player_room(game))
        self.assertFalse(host_receives_moderator_deal_messages(game))
        self.assertFalse(players_receive_post_deal_hub_message(game))

    def test_bazpors_fill_still_works(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, Player(1, "A", None))
        self.assertIsNone(self.gm.fill_bazpors_no_host_synthetic_lobby(game))
        self.assertEqual(len(game.players), 10)


if __name__ == "__main__":
    unittest.main()
