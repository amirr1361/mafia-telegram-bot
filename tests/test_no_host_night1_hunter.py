"""شب ۱ — انتخاب هانتر (no_host)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.no_host_night1 import (
    build_no_host_hunter_night1_pick_html,
    build_no_host_hunter_rules_html,
    hunter_night1_act_active,
)


class NoHostNight1HunterTest(unittest.TestCase):
    def test_rules_html(self) -> None:
        text = build_no_host_hunter_rules_html()
        self.assertIn("قوانین هانتر", text)
        self.assertIn("رییس مافیا", text)
        self.assertIn("فقط هانتر خارج می‌شود", text)
        self.assertNotIn("هیچ‌کدام خارج نمی‌شوند", text)
        self.assertIn("شهروند", text)

    def test_pick_html(self) -> None:
        from bot.models import Game

        game = Game(room_code="01", host_id=1, scenario_name="bazpors")
        game.bazpors_narrator_night_count = 1
        text = build_no_host_hunter_night1_pick_html(game)
        self.assertIn("شب اول", text)
        self.assertNotIn("ثانیه", text)
        self.assertNotIn("خودکار", text)

    def test_hunter_acts(self) -> None:
        from bot.models import Game

        g = Game(room_code="01", host_id=1, scenario_name="bazpors")
        self.assertTrue(hunter_night1_act_active(g, "hnp"))
        self.assertFalse(hunter_night1_act_active(g, "d1dc"))


if __name__ == "__main__":
    unittest.main()
