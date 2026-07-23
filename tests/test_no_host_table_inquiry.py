"""استعلام وضعیت صندلی — مسیر بدون گرداننده."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import Role
from bot.game import GameManager, bazpors_counts_as_mafia_faction
from bot.models import Game, Player
from bot.no_host_table_inquiry import (
    NO_HOST_TABLE_INQUIRY,
    PHASE_ASK,
    PHASE_CONFIRM,
    build_no_host_table_inquiry_assistant_panel,
    build_table_inquiry_ask_panel,
    build_table_inquiry_confirm_panel,
    build_table_inquiry_no_broadcast_html,
    build_table_inquiry_yes_broadcast_html,
    enter_no_host_table_inquiry_before_day,
    process_no_host_table_inquiry_narrator_cb,
    reset_no_host_table_inquiry_state,
)


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


class NoHostTableInquiryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game(self) -> Game:
        game = Game(
            room_code="77",
            host_id=1,
            scenario_name="bazpors",
            players={
                10: _p(10, 1, "کمک", Role.CITIZEN),
                -1: _p(-1, 2, "مافیا۱", Role.MAFIA, alive=False),
                -2: _p(-2, 3, "مافیا۲", Role.MAFIA, alive=False),
                -3: _p(-3, 4, "شهروند", Role.CITIZEN, alive=False),
                -4: _p(-4, 5, "زنده", Role.CITIZEN),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 10
        return game

    def test_enter_sets_step_and_ask_panel(self) -> None:
        game = self._game()
        enter_no_host_table_inquiry_before_day(game)
        self.assertEqual(game.bazpors_narrator_step, NO_HOST_TABLE_INQUIRY)
        self.assertEqual(game.no_host_table_inquiry_phase, PHASE_ASK)
        text, kb = build_no_host_table_inquiry_assistant_panel(game, self.gm)
        self.assertEqual(text, build_table_inquiry_ask_panel())
        self.assertIsNotNone(kb)
        self.assertIn("tinq_yes", kb.inline_keyboard[0][0].callback_data)

    def test_yes_confirm_flow(self) -> None:
        game = self._game()
        enter_no_host_table_inquiry_before_day(game)
        self.assertIsNone(
            process_no_host_table_inquiry_narrator_cb(game, self.gm, "tinq_yes", 0)
        )
        self.assertEqual(game.no_host_table_inquiry_phase, PHASE_CONFIRM)
        self.assertEqual(game.no_host_table_inquiry_pending, "yes")
        text, _ = build_no_host_table_inquiry_assistant_panel(game, self.gm)
        self.assertIn("بله", text)
        self.assertEqual(
            build_table_inquiry_confirm_panel("yes"),
            text,
        )

    def test_back_from_confirm(self) -> None:
        game = self._game()
        enter_no_host_table_inquiry_before_day(game)
        process_no_host_table_inquiry_narrator_cb(game, self.gm, "tinq_no", 0)
        self.assertIsNone(
            process_no_host_table_inquiry_narrator_cb(game, self.gm, "tinq_back", 0)
        )
        self.assertEqual(game.no_host_table_inquiry_phase, PHASE_ASK)
        self.assertIsNone(game.no_host_table_inquiry_pending)

    def test_yes_broadcast_counts_dead_factions(self) -> None:
        game = self._game()
        game.mafia_ids = {-1, -2}
        html = build_table_inquiry_yes_broadcast_html(game, self.gm)
        self.assertIn("استعلام وضعیت میز", html)
        self.assertIn("۲", html)
        self.assertIn("عضو مافیا", html)
        self.assertIn("۱", html)
        self.assertIn("شهروند", html)
        for p in game.players.values():
            if not p.is_alive and p.role != Role.OBSERVER:
                if bazpors_counts_as_mafia_faction(game, p):
                    pass

    def test_no_broadcast(self) -> None:
        game = self._game()
        html = build_table_inquiry_no_broadcast_html(game, self.gm)
        self.assertIn("لازم نیست", html)

    def test_reset_clears_state(self) -> None:
        game = self._game()
        enter_no_host_table_inquiry_before_day(game)
        game.no_host_table_inquiry_pending = "yes"
        reset_no_host_table_inquiry_state(game)
        self.assertIsNone(game.no_host_table_inquiry_phase)
        self.assertIsNone(game.no_host_table_inquiry_pending)
