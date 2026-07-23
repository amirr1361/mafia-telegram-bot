"""گزارش پایان شب برای ناظر در حالت کمک‌کننده + آینه."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import deliver_observer_night_end_report
from bot.game import GameManager
from bot.models import Game, Player, Role


class NoHostObserverNightReportTests(unittest.TestCase):
    def test_deliver_not_blocked_by_observer_only_mirror_flag(self) -> None:
        gm = GameManager()
        game = Game(
            room_code="14",
            host_id=1,
            scenario_name="bazpors",
            bazpors_host_mode="no_host",
            players={
                99: Player(99, "Obs", None, Role.CITIZEN, seat=1),
            },
        )
        game.bot_assistant_user_id = 1
        game.no_host_assistant_narrator_active = True
        game.no_host_observer_only_narrator_mirror = True
        game.observer_user_id = 99
        game.observer_prompt_status = "registered"
        game.bazpors_narrator_night_count = 2
        game.bazpors_night_report_html = (
            "<b>پایان شب دوم</b>\n-----------\n"
            "🌙 ═══ <b>گزارش کامل شب گذشته</b> ═══"
        )

        bot = AsyncMock()
        with patch(
            "bot.bazpors_narrator.safe_send_message", new_callable=AsyncMock
        ) as send:
            import asyncio

            asyncio.run(deliver_observer_night_end_report(bot, game, gm))
            send.assert_called_once()
            self.assertEqual(game.bazpors_observer_night_report_sent_night, 2)


if __name__ == "__main__":
    unittest.main()
