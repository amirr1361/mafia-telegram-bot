"""روز فاز آشوب (Chaos) در سناریوی bazpors نیمه‌خودکار."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    ASK_NIGHT_EXTRA,
    DAY_DISCUSS,
    _build_night_end_report_panel_html,
    _ki_as_split_night_end_panel,
    _sync_ki_as_today,
    bazpors_chaos_phase_enabled,
    build_host_message_and_keyboard,
    ki_as_hand_resolve_day_active,
)
from bot.game import GameManager
from bot.models import Game, Player, Role


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def make_semi_auto_3p_endgame() -> Game:
    players = {
        -1: _p(-1, 1, "رییس مافیا", Role.MAFIA_BOSS),
        -2: _p(-2, 2, "شهروند ۱", Role.CITIZEN),
        -3: _p(-3, 3, "شهروند ۲", Role.CITIZEN),
    }
    game = Game(
        room_code="11",
        host_id=1,
        scenario_name="bazpors",
        players=players,
        max_players=13,
    )
    game.bazpors_host_mode = "semi_auto"
    game.bazpors_narrator_step = DAY_DISCUSS
    game.bazpors_narrator_host_day = 5
    game.mafia_ids = {-1}
    return game


class KiAsBazporsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_sync_ki_as_for_bazpors_semi_auto(self) -> None:
        game = make_semi_auto_3p_endgame()
        _sync_ki_as_today(game, self.gm)
        self.assertTrue(game.bazpors_ki_as_today)

    def test_ki_as_hand_resolve_active_for_bazpors_semi_auto(self) -> None:
        game = make_semi_auto_3p_endgame()
        self.assertTrue(ki_as_hand_resolve_day_active(game, self.gm))

    def test_chaos_day_discuss_shows_host_win_buttons(self) -> None:
        game = make_semi_auto_3p_endgame()
        _sync_ki_as_today(game, self.gm)
        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("نتیجهٔ بازی", body)
        self.assertNotIn("دست دادن» می‌رود", body)
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🏆 مافیا برنده شد", labels)
        self.assertIn("🏆 شهروند برنده شد", labels)
        self.assertNotIn("🗳 رأی‌گیری انجام شد", labels)

    def test_ki_as_not_set_for_plain_bazpors_without_narrator(self) -> None:
        game = make_semi_auto_3p_endgame()
        game.bazpors_host_mode = "manual"
        _sync_ki_as_today(game, self.gm)
        self.assertFalse(game.bazpors_ki_as_today)

    def test_chaos_enabled_for_no_host_mode(self) -> None:
        game = make_semi_auto_3p_endgame()
        game.bazpors_host_mode = "no_host"
        game.bot_assistant_user_id = 1
        game.no_host_assistant_narrator_active = True
        self.assertTrue(bazpors_chaos_phase_enabled(game))
        _sync_ki_as_today(game, self.gm)
        self.assertTrue(game.bazpors_ki_as_today)

    def test_ki_as_split_night_end_followup_panel(self) -> None:
        game = make_semi_auto_3p_endgame()
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        game.bazpors_night_report_html = "<b>پایان شب سوم</b>"
        _sync_ki_as_today(game, self.gm)
        self.assertTrue(_ki_as_split_night_end_panel(game, self.gm))
        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("فاز آشوب", body)
        self.assertNotIn("پایان شب", body)
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["فاز آشوب شروع شد"])
        self.assertNotIn("ثبت خروج شبانه", " ".join(labels))

    def test_night_end_report_panel_for_chaos_split(self) -> None:
        game = make_semi_auto_3p_endgame()
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        game.bazpors_narrator_night_count = 3
        game.bazpors_night_report_html = (
            "<b>پایان شب سوم</b>\n-----------\n"
            "🕯️ <b>نتیجه نهایی شب و روز گذشته:</b>\n"
            "در شبی که گذشت با کسی خداحافظی نکردیم.\n\n"
            "🌙 ═══ <b>گزارش کامل شب گذشته</b> ═══\n"
            "🔴 شات مافیا: تست"
        )
        _sync_ki_as_today(game, self.gm)
        self.assertTrue(_ki_as_split_night_end_panel(game, self.gm))
        report = _build_night_end_report_panel_html(game, self.gm, "")
        self.assertIn("پایان شب سوم", report)
        self.assertIn("نتیجه نهایی", report)
        self.assertIn("وضعیت صندلی", report)
        self.assertIn("فاز آشوب", report)


if __name__ == "__main__":
    unittest.main()
