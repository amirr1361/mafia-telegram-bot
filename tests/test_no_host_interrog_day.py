"""بازپرسی روز — no_host."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import Role
from bot.game import GameManager
from bot.models import Game, Player
from bot.no_host_interrog_day import (
    IH_PHASE_ASSIST,
    IH_PHASE_SESSION,
    IH_PHASE_VOTE,
    NO_HOST_INTERROG_DAY,
    _all_wait_ok_received,
    _interrogator_alive,
    _resolve_session_if_ready,
    _session_ready,
    build_interrog_wait_player_html,
    build_no_host_interrog_day_assistant_panel,
    enter_no_host_interrog_day_step,
    interrog_day_session_wait_locked,
    process_no_host_interrog_day_narrator_cb,
    should_enter_no_host_interrog_day,
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


class NoHostInterrogDayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game(self) -> Game:
        game = Game(
            room_code="77",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "بازپرس", Role.INTERROGATOR),
                -2: _p(-2, 2, "شهروند۱", Role.CITIZEN),
                -3: _p(-3, 3, "شهروند۲", Role.CITIZEN),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.bot_assistant_user_id = 99
        game.no_host_assistant_narrator_active = True
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -2
        game.bazpors_interrog_second_uid = -3
        game.bazpors_interrog_ready_for_day = True
        return game

    def test_should_enter_when_interrog_ready(self) -> None:
        game = self._game()
        self.assertTrue(should_enter_no_host_interrog_day(game))

    def test_assistant_start_panel(self) -> None:
        game = self._game()
        enter_no_host_interrog_day_step(game)
        body, kb = build_no_host_interrog_day_assistant_panel(game, self.gm)
        self.assertIn("بازپرسی شروع شد", body)
        self.assertIsNotNone(kb)
        self.assertEqual(game.bazpors_narrator_step, NO_HOST_INTERROG_DAY)
        self.assertEqual(game.no_host_interrog_day_phase, IH_PHASE_ASSIST)

    def test_session_phase_shows_assistant_wait_panel(self) -> None:
        game = self._game()
        game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
        game.no_host_interrog_day_phase = IH_PHASE_SESSION
        game.no_host_interrog_day_ok_uids = [-2]
        game.no_host_interrog_day_decision = "continue"
        body, kb = build_no_host_interrog_day_assistant_panel(game, self.gm)
        self.assertIn("منتظر تأیید", body)
        self.assertNotIn("جلسه بازپرسی در جریان است", body)
        self.assertIsNone(kb)

    def test_session_wait_locked_only_in_session_phase(self) -> None:
        game = self._game()
        game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
        game.no_host_interrog_day_phase = IH_PHASE_SESSION
        self.assertFalse(interrog_day_session_wait_locked(game))
        game.no_host_interrog_day_assistant_wait_sent = True
        self.assertTrue(interrog_day_session_wait_locked(game))
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        self.assertFalse(interrog_day_session_wait_locked(game))
        game.no_host_interrog_day_assistant_wait_sent = True
        self.assertFalse(interrog_day_session_wait_locked(game))

    def test_continue_broadcast_unified(self) -> None:
        from bot.no_host_interrog_day import build_interrog_continue_broadcast_html

        body = build_interrog_continue_broadcast_html()
        self.assertIn("جلسه بازپرسی با اخذ آرا ادامه پیدا می‌کند", body)
        self.assertNotIn("بازپرس در شب گذشته", body)

    def test_session_ready_needs_ok_and_decision(self) -> None:
        game = self._game()
        game.no_host_interrog_day_phase = "session"
        game.no_host_interrog_day_decision = "continue"
        self.assertFalse(_session_ready(game))
        game.no_host_interrog_day_ok_uids = [-2, -3]
        self.assertTrue(_all_wait_ok_received(game))
        self.assertTrue(_session_ready(game))

    def test_narrator_cb_vote_phase(self) -> None:
        game = self._game()
        game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        err = process_no_host_interrog_day_narrator_cb(
            game, self.gm, "ih_vtie", 0
        )
        self.assertIsNone(err)
        self.assertEqual(game.no_host_interrog_day_pending_vote, "tie")

    def test_wait_player_html(self) -> None:
        body = build_interrog_wait_player_html()
        self.assertIn("بازپرس در حال تصمیم", body)
        self.assertIn("اوکی", body)
        self.assertNotIn("انحلال", body)

    def _game_dead_interrogator(self) -> Game:
        game = self._game()
        game.players[-1] = _p(-1, 1, "بازپرس", Role.INTERROGATOR, alive=False)
        return game

    def test_enter_assist_when_interrogator_dead(self) -> None:
        game = self._game_dead_interrogator()
        enter_no_host_interrog_day_step(game)
        self.assertEqual(game.no_host_interrog_day_phase, IH_PHASE_ASSIST)
        self.assertIsNone(game.no_host_interrog_day_decision)
        body, kb = build_no_host_interrog_day_assistant_panel(game, self.gm)
        self.assertIn("بازپرسی شروع شد", body)
        self.assertIn("ارسال درخواست به بازپرس", str(kb))

    def test_session_ready_without_interrogator_needs_ok(self) -> None:
        game = self._game_dead_interrogator()
        game.no_host_interrog_day_phase = IH_PHASE_SESSION
        self.assertFalse(_interrogator_alive(game))
        self.assertFalse(_session_ready(game))
        game.no_host_interrog_day_ok_uids = [-2, -3]
        self.assertTrue(_session_ready(game))
        self.assertEqual(game.no_host_interrog_day_decision, "continue")


class NoHostInterrogDayResolveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = Game(
            room_code="44",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "بازپرس", Role.INTERROGATOR),
                -2: _p(-2, 2, "شهروند۱", Role.CITIZEN),
                -3: _p(-3, 3, "شهروند۲", Role.CITIZEN),
            },
        )
        self.game.bazpors_host_mode = "no_host"
        self.game.bot_assistant_user_id = 99
        self.game.no_host_assistant_narrator_active = True
        self.game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
        self.game.no_host_interrog_day_phase = IH_PHASE_SESSION
        self.game.no_host_interrog_day_decision = "continue"
        self.game.no_host_interrog_day_ok_uids = [-2, -3]

    async def test_resolve_continue_sends_vote_panel_once(self) -> None:
        bot = AsyncMock()
        with patch(
            "bot.no_host_interrog_day._broadcast_all_alive",
            new_callable=AsyncMock,
        ) as broadcast:
            with patch(
                "bot.no_host_interrog_day._deliver_interrog_assistant_panel",
                new_callable=AsyncMock,
            ) as deliver:
                await _resolve_session_if_ready(bot, self.game, self.gm)
                await _resolve_session_if_ready(bot, self.game, self.gm)
        self.assertEqual(self.game.no_host_interrog_day_phase, IH_PHASE_VOTE)
        broadcast.assert_awaited_once()
        deliver.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
