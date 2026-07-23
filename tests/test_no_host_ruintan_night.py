"""رویین‌تن — فاز شب no_host."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.no_host_ruintan_night import build_no_host_ruintan_night_html


class NoHostRuintanNightTest(unittest.TestCase):
    def test_night_html_has_role_and_wait(self) -> None:
        body = build_no_host_ruintan_night_html(confirmed=False)
        self.assertIn("رویین‌تن", body)
        self.assertIn("نقش شما", body)
        self.assertIn("از بازی خارج نخواهید شد", body)
        self.assertIn("منتظر اتمام فاز شب", body)

    def test_confirmed_html(self) -> None:
        body = build_no_host_ruintan_night_html(confirmed=True)
        self.assertIn("تأیید شما ثبت شد", body)

    def test_create_game_has_ruintan_fields(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertIsNone(game.no_host_ruintan_dm_signature)
        self.assertFalse(game.no_host_ruintan_night_confirmed)


if __name__ == "__main__":
    unittest.main()
