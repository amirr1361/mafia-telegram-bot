"""شب اول مذاکره — پیام ناتمام‌ها به کمک‌کننده حذف شد؛ یادآور ۱۲۰ثانیه‌ای حفظ است."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import (
    NIGHT_START,
    build_host_message_and_keyboard,
    push_host_step,
)
from bot.game import GameManager
from bot.models import Player, Role
from bot.room_mode import is_mozakere_scenario


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _night_start_game(gm: GameManager, *, assistant_uid: int = 900):
    """اتاق مذاکره در آستانهٔ شب — پنل‌های بازیکن آمادهٔ اعزام."""
    game = gm.create_game(
        host_id=1, scenario_name="mozakere", max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "MZNS"
    gm.games["MZNS"] = game
    game.bot_assistant_user_id = assistant_uid
    game.no_host_assistant_narrator_active = True
    game.no_host_observer_only_narrator_mirror = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    game.no_host_night_entry_dispatched_night = 1
    gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
    gm.add_player(game, _p(20, "RezaCitizen", Role.CITIZEN, seat=2))
    return game


class MozakereNightStartHelperSuppressedTests(unittest.IsolatedAsyncioTestCase):
    def test_mozakere_builder_returns_no_helper_panel(self):
        gm = GameManager()
        game = _night_start_game(gm)
        out = build_host_message_and_keyboard(game, gm)
        self.assertTrue(isinstance(out, tuple))
        text, kb = out
        self.assertEqual(text, "")
        self.assertIsNone(kb)

    async def test_push_host_step_sends_nothing_to_helper(self):
        gm = GameManager()
        game = _night_start_game(gm)
        bot = MagicMock()

        async def fake_send(bot_, chat_id, text, **kwargs):
            raise AssertionError(
                f"helper must not receive the night-start pending panel: {text}"
            )

        with patch(
            "bot.bazpors_narrator.safe_send_message_return", new=fake_send
        ), patch(
            "bot.bazpors_narrator._try_edit_assistant_panel", new=AsyncMock()
        ), patch(
            "bot.bazpors_narrator._try_edit_observer_narrator_mirror",
            new=AsyncMock(),
        ):
            await push_host_step(bot, game, gm)

    def test_bazpors_no_host_night_start_panel_also_suppressed(self):
        gm = GameManager()
        game = gm.create_game(
            host_id=1, scenario_name="bazpors", max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.room_code = "BZNS"
        gm.games["BZNS"] = game
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 1
        game.no_host_night_parallel_collect_active = True
        game.no_host_night_entry_dispatched_night = 1
        gm.add_player(game, _p(10, "Bboss", Role.MAFIA_BOSS, seat=1))
        self.assertFalse(is_mozakere_scenario(game))
        # بازپرس هم مانند مذاکره: پنل «شب … آغاز شد» ارسال نمی‌شود.
        text, kb = build_host_message_and_keyboard(game, gm)
        self.assertEqual((text, kb), ("", None))

    async def test_pending_refresh_path_no_longer_resends_to_helper(self):
        from bot.no_host_night_reconcile import _refresh_pending_panel

        gm = GameManager()
        game = _night_start_game(gm)
        bot = MagicMock()

        async def fake_send(bot_, chat_id, text, **kwargs):
            raise AssertionError(
                f"pending refresh must not message the helper: {text}"
            )

        with patch(
            "bot.bazpors_narrator.safe_send_message_return", new=fake_send
        ):
            await _refresh_pending_panel(bot, game, gm, reason="test")
            # internal tracking still recorded exactly once
            self.assertNotEqual(game.no_host_night_ready_signature, "")
            first = game.no_host_night_ready_signature
            await _refresh_pending_panel(bot, game, gm, reason="test2")
            self.assertEqual(game.no_host_night_ready_signature, first)

    async def test_night_entry_player_panels_still_dispatched(self):
        gm = GameManager()
        game = _night_start_game(gm)
        bot = MagicMock()
        with patch(
            "bot.bazpors_narrator.safe_send_message_return", new=AsyncMock()
        ), patch(
            "bot.no_host_night_entry.dispatch_all_no_host_night_entry_panels",
            new=AsyncMock(),
        ) as dispatch:
            await push_host_step(bot, game, gm)
        dispatch.assert_awaited()

    async def test_120s_reminder_still_sent_with_counter_after_suppression(self):
        from bot.night_helper_reminder import (
            _send_reminder_if_needed,
            night_reminder_night_stamp,
        )

        gm = GameManager()
        game = _night_start_game(gm)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=4242))
        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(
            bot,
            game,
            gm,
            generation=gen,
            night_count=night_reminder_night_stamp(game),
        )
        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.await_args.kwargs
        text = kwargs.get("text") or ""
        self.assertIn("🌙 <b>قابلیت اتمام شب</b>", text)
        self.assertIn("اقدام شبانه تکمیل نشده است", text)
        kb = kwargs.get("reply_markup")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])
        self.assertGreaterEqual(game.night_helper_reminder_last_count, 1)


if __name__ == "__main__":
    unittest.main()
