"""گزارش پایان شب — ارسال همان متن گرداننده به ناظر."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import build_night_end_report_bundle_html
from bot.game import GameManager
from bot.models import Game, Player, Role


class ObserverNightEndReportTest(unittest.TestCase):
    def test_bundle_includes_report_roster_and_guidance(self) -> None:
        gm = GameManager()
        game = Game(
            room_code="99",
            host_id=1,
            scenario_name="bazpors",
            bazpors_host_mode="semi_auto",
            players={
                10: Player(10, "A", None, Role.CITIZEN, seat=1, is_alive=False),
                11: Player(11, "B", None, Role.MAFIA_BASIC, seat=2),
            },
        )
        game.bazpors_narrator_night_count = 1
        game.bazpors_night_report_html = (
            "<b>پایان شب اول</b>\n-----------\n"
            "🕯️ <b>نتیجه نهایی شب و روز گذشته:</b>\n"
            "🌙 ═══ <b>گزارش کامل شب گذشته</b> ═══"
        )
        text = build_night_end_report_bundle_html(game, gm)
        self.assertIn("پایان شب اول", text)
        self.assertIn("گزارش کامل شب گذشته", text)
        self.assertIn("وضعیت صندلی", text)
        self.assertIn("ثبت خروج شبانهٔ اضافی", text)


if __name__ == "__main__":
    unittest.main()
