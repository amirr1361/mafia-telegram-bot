"""پایان شب با بازپرسی — دو پیام جدا در semi_auto."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    ASK_NIGHT_EXTRA,
    DAY_INTERROG_GATE,
    NS_INTERROG_SKIP,
    NIGHT_ACTIONS,
    Role,
    _build_interrog_day_host_panel_html,
    _interrog_ready_split_night_end_panel,
    build_host_message_and_keyboard,
    preserve_night_end_host_message,
)
from bot.game import GameManager
from bot.models import Game, Player


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def _semi_auto_game() -> Game:
    players = {
        -1: _p(-1, 1, "رییس", Role.MAFIA_BOSS),
        -2: _p(-2, 2, "بازپرس", Role.INTERROGATOR),
        -3: _p(-3, 3, "کارآگاه", Role.DETECTIVE),
        -4: _p(-4, 4, "پزشک", Role.DOCTOR),
        -5: _p(-5, 5, "هانتر", Role.HUNTER),
        -6: _p(-6, 6, "ناتو", Role.NATO),
        -7: _p(-7, 7, "شیاد", Role.SHIAD),
        -8: _p(-8, 8, "رویین تن", Role.RUINTAN),
        -9: _p(-9, 9, "اسنایپر", Role.SNIPER),
        -10: _p(-10, 10, "شهروند ۱", Role.CITIZEN),
        -11: _p(-11, 11, "شهروند ۲", Role.CITIZEN),
        -12: _p(-12, 12, "مافیا", Role.MAFIA_BASIC),
    }
    game = Game(
        room_code="15",
        host_id=1,
        scenario_name="bazpors",
        players=players,
        max_players=12,
    )
    game.mafia_ids = {-1, -6, -12}
    game.bazpors_host_mode = "semi_auto"
    game.bazpors_narrator_night_count = 2
    game.bazpors_ki_as_today = False
    return game


class InterrogNightEndSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_split_panel_when_interrog_ready(self) -> None:
        game = _semi_auto_game()
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -10
        game.bazpors_interrog_second_uid = -11
        game.bazpors_night_report_html = "<b>پایان شب دوم</b>"

        self.assertTrue(_interrog_ready_split_night_end_panel(game, self.gm))

    def test_second_message_has_interrog_instructions(self) -> None:
        game = _semi_auto_game()
        game.bazpors_interrog_first_uid = -2
        game.bazpors_interrog_second_uid = -3
        body = _build_interrog_day_host_panel_html(game, self.gm, "")
        self.assertIn("بازپرسی باید انجام شود", body)
        self.assertIn("۳۰ ثانیه", body)
        self.assertIn("خواب نیم‌روزی", body)
        self.assertIn("لایک", body)

    def test_ask_night_extra_split_body_has_buttons_not_report(self) -> None:
        game = _semi_auto_game()
        game.bazpors_narrator_step = ASK_NIGHT_EXTRA
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -10
        game.bazpors_interrog_second_uid = -11
        game.bazpors_night_report_html = "گزارش شب"

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("بازپرسی باید انجام شود", body)
        self.assertNotIn("گزارش شب", body)
        self.assertIsNotNone(kb)

    def test_day_interrog_gate_once_done_confirm_only(self) -> None:
        game = _semi_auto_game()
        game.bazpors_narrator_step = DAY_INTERROG_GATE
        game.bazpors_interrog_once_done = True
        game.bazpors_narrator_host_day = 3

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("نیازی به بیدار کردن بازپرس نیست", body)
        self.assertIn("کار او انجام شده", body)
        self.assertNotIn("بازپرسی ادامه پیدا کند", body)
        assert kb is not None
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertEqual(labels, ["✅ تأیید"])

    def test_night_report_preserved_after_interrog_button_click(self) -> None:
        self.assertTrue(
            preserve_night_end_host_message(ASK_NIGHT_EXTRA, "intr_continue")
        )
        self.assertTrue(
            preserve_night_end_host_message(ASK_NIGHT_EXTRA, "intr_dissolve")
        )

    def test_night_interrog_skip_text(self) -> None:
        game = _semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_INTERROG_SKIP
        game.bazpors_interrog_once_done = True

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("نیازی به بیدار کردن بازپرس نیست", body)
        self.assertIn("کار او انجام شده", body)
        assert kb is not None
        self.assertEqual(
            [b.text for row in kb.inline_keyboard for b in row],
            ["✅ تأیید"],
        )


if __name__ == "__main__":
    unittest.main()
