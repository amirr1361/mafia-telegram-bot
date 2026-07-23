"""شافل صندلی — نیمه‌خودکار بدون نمایش نام به گرداننده."""

from __future__ import annotations

import unittest

from bot.main import (
    build_shuffle_confirm_prompt_html,
    bump_seat_shuffle_count,
)
from bot.models import Game, Player, Role


class SemiAutoShufflePrivacyTests(unittest.TestCase):
    def _game(self, mode: str) -> Game:
        return Game(
            room_code="99",
            host_id=1,
            scenario_name="bazpors",
            bazpors_host_mode=mode,
            players={
                10: Player(10, "علی", None, Role.CITIZEN, seat=None),
                20: Player(20, "رضا", None, Role.CITIZEN, seat=None),
            },
        )

    def test_semi_auto_hides_names_shows_count(self) -> None:
        game = self._game("semi_auto")
        bump_seat_shuffle_count(game)
        text = build_shuffle_confirm_prompt_html(game, [(1, game.players[10])])
        self.assertIn("۱ بار", text)
        self.assertNotIn("علی", text)
        self.assertNotIn("رضا", text)
        self.assertIn("تایید", text)

    def test_second_shuffle_increments_count(self) -> None:
        game = self._game("semi_auto")
        bump_seat_shuffle_count(game)
        bump_seat_shuffle_count(game)
        text = build_shuffle_confirm_prompt_html(game, [])
        self.assertIn("۲ بار", text)

    def test_manual_still_shows_names(self) -> None:
        game = self._game("manual")
        game.bazpors_seat_shuffle_count = 1
        rows = [(1, game.players[10]), (2, game.players[20])]
        text = build_shuffle_confirm_prompt_html(game, rows)
        self.assertIn("صندلی 1", text)
        self.assertIn("صندلی 2", text)


if __name__ == "__main__":
    unittest.main()
