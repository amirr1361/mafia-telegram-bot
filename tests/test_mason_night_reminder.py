"""یادآور عمومی شب ماسون — متن ثابت، بدون نام بازیکن/نقش."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_reminder import (
    REMINDER_DELAY_SEC,
    _send_reminder_if_needed,
    build_mason_night_reminder_text,
    cancel_mason_night_reminder_task,
    cleanup_mason_night_helper_reminder,
    collect_mason_night_pending_holder_uids,
    mason_reminder_display_name,
    refresh_mason_night_helper_reminder,
    schedule_mason_night_helper_reminder,
)
from bot.mason_night_ready import maybe_finish_mason_parallel_night
from bot.models import Phase, Player, Role


def _p(uid, name, role, *, alive=True, seat=0):
    return Player(user_id=uid, full_name=name, username=None, role=role, is_alive=alive, seat=seat)


def _night_game(gm, *, assistant_uid=900, creator_uid=1):
    game = gm.create_game(host_id=creator_uid, scenario_name="masoon", max_players=12, bazpors_host_mode="no_host")
    assert game is not None
    old_code = game.room_code
    game.room_code = "R2"
    if old_code in gm.games:
        gm.games.pop(old_code, None)
    gm.games["R2"] = game
    game.bot_assistant_user_id = assistant_uid
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.observer_full_name = "Observer"
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    game.mason_night_entry_dispatched_night = 1
    return game


def _mark_roles_done(game):
    for attr in (
        "mason_night_saboteur_confirmed", "mason_night_doctor_confirmed",
        "mason_night_sniper_confirmed", "mason_night_commander_confirmed",
        "mason_night_gunner_confirmed", "mason_night_guardian_confirmed",
        "mason_night_mason_confirmed", "mason_night_detective_confirmed",
        "mason_night_natasha_confirmed", "mason_night_priest_confirmed",
    ):
        setattr(game, attr, True)
    # اوکی انتظار شهرونده‌های سادهٔ زنده (۵۵، ۵۶ و کمک‌کنندهٔ ۹۰۰)
    game.mason_night_wait_ok_uids = [55, 56, 900]


def _mafia_done(game):
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True


def _seed_pending_cast(gm, game):
    gm.add_player(game, _p(900, "HelperSeat", Role.TOWN_SIMPLE, seat=1))
    gm.add_player(game, _p(-920008, "ابوالفضل - گادفادر", Role.GODFATHER, seat=2))
    gm.add_player(game, _p(-920005, "خسروی - پزشک", Role.DOCTOR, seat=3))
    gm.add_player(game, _p(55, "Ali", Role.TOWN_SIMPLE, seat=4))
    gm.add_player(game, _p(56, "Reza", Role.TOWN_SIMPLE, seat=5))
    gm.add_player(game, _p(-920001, "مهدی - ماسون", Role.MASON, seat=6))
    gm.add_player(game, _p(999, "ObserverPerson", Role.OBSERVER, seat=99))
    game.no_host_mafia_night1_done = False
    game.mafia_ids = {-920008}


class MasonNightReminderTextTests(unittest.TestCase):
    def test_delay_constant_is_120(self):
        self.assertEqual(REMINDER_DELAY_SEC, 120.0)

    def test_display_name_strips_synthetic_role(self):
        p = _p(-920005, "خسروی - پزشک", Role.DOCTOR, seat=3)
        self.assertEqual(mason_reminder_display_name(p), "خسروی")

    def test_text_is_generic_static(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        text = build_mason_night_reminder_text(game, 4)
        # متن عمومی با شمارندهٔ زنده — بدون هیچ نام/نقش/صندلی
        self.assertIn("🌙 قابلیت اتمام شب", text)
        self.assertIn("هنوز ۴ اقدام شبانه تکمیل نشده است", text)
        self.assertIn("گزینه «اتمام شب»", text)
        self.assertIn("اقدامات تأییدشده محاسبه می‌شوند", text)
        for banned in ("پزشک", "گادفادر", "ماسون", "خسروی", "ابوالفضل", "Ali", "Reza", "DOCTOR", "GODFATHER"):
            self.assertNotIn(banned, text)
        # بدون هشدارهای سرباز/اسنایپر (فقط ویژهٔ نماینده ۱۲/۱۳)
        self.assertNotIn("🪖", text)
        self.assertNotIn("🎯", text)

    def test_text_identical_for_different_casts(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        text1 = build_mason_night_reminder_text(game, 3)
        gm2 = GameManager()
        game2 = _night_game(gm2)
        gm2.add_player(game2, _p(10, "SomeoneElse", Role.DOCTOR, seat=1))
        text2 = build_mason_night_reminder_text(game2, 3)
        self.assertEqual(text1, text2)


class MasonNightReminderDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        cancel_mason_night_reminder_task("R2")
        cancel_mason_night_reminder_task("R3")

    def _bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=4242))
        bot.edit_message_text = AsyncMock()
        bot.delete_message = AsyncMock()
        return bot

    async def test_schedule_does_not_send_immediately(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        bot = self._bot()
        with patch("bot.mason_night_reminder.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            schedule_mason_night_helper_reminder(bot, game)
            await asyncio.sleep(0)
            cancel_mason_night_reminder_task(game.room_code)
        sleep_mock.assert_awaited()
        bot.send_message.assert_not_called()
        self.assertIsNone(game.mason_night_reminder_message_id)

    async def test_reminder_sent_after_delay_to_helper_only(self):
        gm = GameManager()
        game = _night_game(gm, assistant_uid=900, creator_uid=1)
        _seed_pending_cast(gm, game)
        bot = self._bot()
        gm.games[game.room_code] = game

        async def _instant_sleep(_delay):
            return None

        with patch('bot.mason_night_reminder.asyncio.sleep', side_effect=_instant_sleep):
            with patch('bot.app_state.manager', gm):
                schedule_mason_night_helper_reminder(bot, game)
                from bot.mason_night_reminder import _REMINDER_TASKS

                task = _REMINDER_TASKS.get(game.room_code)
                self.assertIsNotNone(task)
                await task
        self.assertEqual(bot.send_message.await_args.kwargs.get('chat_id'), 900)
        text = bot.send_message.await_args.kwargs.get('text') or ''
        self.assertIn('🌙 قابلیت اتمام شب', text)
        self.assertIn('اقدام شبانه تکمیل نشده است', text)
        self.assertNotIn('خسروی', text)
        self.assertNotIn('گادفادر', text)
        kb = bot.send_message.await_args.kwargs.get('reply_markup')
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ['🌙 اتمام شب'])
        for c in bot.send_message.await_args_list:
            self.assertEqual(c.kwargs.get('chat_id'), 900)

    async def test_no_reminder_if_night_already_ready(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "A", Role.TOWN_SIMPLE, seat=1))
        _mafia_done(game)
        _mark_roles_done(game)
        game.mason_night_wait_ok_uids = [10]
        bot = self._bot()
        gen = 1
        game.mason_night_reminder_generation = gen
        iso = game.created_at.isoformat()
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1, created_at_iso=iso)
        bot.send_message.assert_not_called()

    async def test_no_reminder_if_phase_changed(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        game.no_host_night_parallel_collect_active = False
        bot = self._bot()
        gen = 1
        game.mason_night_reminder_generation = gen
        iso = game.created_at.isoformat()
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1, created_at_iso=iso)
        bot.send_message.assert_not_called()

    async def test_no_reminder_if_game_ended(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        game.phase = Phase.ENDED
        bot = self._bot()
        gen = 1
        game.mason_night_reminder_generation = gen
        iso = game.created_at.isoformat()
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1, created_at_iso=iso)
        bot.send_message.assert_not_called()

    async def test_no_reminder_without_pending_actions(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        _mafia_done(game)
        _mark_roles_done(game)
        bot = self._bot()
        gen = 1
        iso = game.created_at.isoformat()
        game.mason_night_reminder_generation = gen
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1, created_at_iso=iso)
        bot.send_message.assert_not_called()

    async def test_synthetic_included_observer_excluded(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        pending = collect_mason_night_pending_holder_uids(game, gm)
        self.assertTrue(any(is_synthetic_player_uid(u) for u in pending))
        self.assertNotIn(999, pending)

    async def test_dead_players_excluded(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "Alive", Role.TOWN_SIMPLE, seat=1))
        gm.add_player(game, _p(11, "Dead", Role.TOWN_SIMPLE, seat=2, alive=False))
        _mafia_done(game)
        _mark_roles_done(game)
        pending = collect_mason_night_pending_holder_uids(game, gm)
        self.assertIn(10, pending)
        self.assertNotIn(11, pending)

    async def test_refresh_deletes_when_done_without_edits(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "Ali", Role.TOWN_SIMPLE, seat=1))
        gm.add_player(game, _p(20, "Reza", Role.TOWN_SIMPLE, seat=2))
        _mafia_done(game)
        _mark_roles_done(game)
        game.mason_night_reminder_chat_id = 900
        game.mason_night_reminder_message_id = 77
        game.mason_night_reminder_initial_pending_uids = [10, 20]
        game.mason_night_reminder_last_text = "old"
        bot = self._bot()
        game.mason_night_wait_ok_uids = [10, 20]
        await refresh_mason_night_helper_reminder(bot, game, gm)
        # متن ثابت است — هیچ ویرایشی انجام نمی‌شود؛ فقط حذف
        bot.edit_message_text.assert_not_awaited()
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.mason_night_reminder_message_id)

    async def test_refresh_keeps_message_while_pending(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "Ali", Role.TOWN_SIMPLE, seat=1))
        gm.add_player(game, _p(20, "Reza", Role.TOWN_SIMPLE, seat=2))
        _mafia_done(game)
        _mark_roles_done(game)
        game.mason_night_reminder_chat_id = 900
        game.mason_night_reminder_message_id = 77
        game.mason_night_reminder_initial_pending_uids = [10, 20]
        game.mason_night_reminder_last_text = build_mason_night_reminder_text(game, 1)
        bot = self._bot()
        game.mason_night_wait_ok_uids = [20]
        await refresh_mason_night_helper_reminder(bot, game, gm)
        # شمارنده بدون تغییر → بدون edit و بدون پیام جدید
        bot.edit_message_text.assert_not_awaited()
        bot.delete_message.assert_not_awaited()
        self.assertEqual(game.mason_night_reminder_message_id, 77)

    async def test_refresh_edits_count_in_place_and_keeps_button(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "Ali", Role.TOWN_SIMPLE, seat=1))
        gm.add_player(game, _p(20, "Reza", Role.TOWN_SIMPLE, seat=2))
        _mafia_done(game)
        _mark_roles_done(game)
        game.mason_night_reminder_chat_id = 900
        game.mason_night_reminder_message_id = 77
        game.mason_night_reminder_initial_pending_uids = [10, 20]
        # قبلاً ۲ اقدام ناتمام نمایش داده شده بود
        game.mason_night_reminder_last_text = build_mason_night_reminder_text(game, 2)
        bot = self._bot()
        game.mason_night_wait_ok_uids = [20]
        await refresh_mason_night_helper_reminder(bot, game, gm)
        bot.edit_message_text.assert_awaited_once()
        self.assertEqual(bot.edit_message_text.await_args.kwargs.get("chat_id"), 900)
        self.assertEqual(bot.edit_message_text.await_args.kwargs.get("message_id"), 77)
        text = bot.edit_message_text.await_args.kwargs.get("text") or ""
        self.assertIn("هنوز ۱ اقدام شبانه تکمیل نشده است", text)
        kb = bot.edit_message_text.await_args.kwargs.get("reply_markup")
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])
        self.assertEqual(game.mason_night_reminder_last_text, text)

    async def test_refresh_deletes_at_zero_count(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "Ali", Role.TOWN_SIMPLE, seat=1))
        _mafia_done(game)
        _mark_roles_done(game)
        # همهٔ اوکی‌های انتظار ثبت شده و جمع‌آوری هنوز فعال: شمارنده صفر
        game.mason_night_wait_ok_uids = [10, 900]
        game.mason_night_reminder_chat_id = 900
        game.mason_night_reminder_message_id = 77
        game.mason_night_reminder_last_text = build_mason_night_reminder_text(game, 1)
        bot = self._bot()
        from bot.mason_night_ready import all_mason_parallel_night_ready

        self.assertTrue(all_mason_parallel_night_ready(game))
        # اتمام عادی (بدون فشار دکمه) → حذف پیام و باطل‌سازی callback؛
        # هیچ اتمام اجباری و هیچ جریمه‌ای اجرا نمی‌شود.
        await refresh_mason_night_helper_reminder(bot, game, gm)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.mason_night_reminder_message_id)

    async def test_stale_generation_timer_does_not_send(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        bot = self._bot()
        iso = game.created_at.isoformat()
        game.mason_night_reminder_generation = 5
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=4, night_count=1, created_at_iso=iso)
        bot.send_message.assert_not_called()

    async def test_old_night_timer_does_not_send_on_night2(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        game.bazpors_narrator_night_count = 2
        bot = self._bot()
        iso = game.created_at.isoformat()
        game.mason_night_reminder_generation = 1
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=1, night_count=1, created_at_iso=iso)
        bot.send_message.assert_not_called()

    async def test_room_reuse_different_created_at_blocked(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        bot = self._bot()
        game.mason_night_reminder_generation = 1
        game.mason_night_reminder_created_at_iso = game.created_at.isoformat()
        await _send_reminder_if_needed(bot, game, gm, generation=1, night_count=1, created_at_iso="2000-01-01T00:00:00+00:00")
        bot.send_message.assert_not_called()

    async def test_duplicate_send_prevented(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        bot = self._bot()
        gen = 1
        iso = game.created_at.isoformat()
        game.mason_night_reminder_generation = gen
        game.mason_night_reminder_created_at_iso = iso
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1, created_at_iso=iso)
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1, created_at_iso=iso)
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_cleanup_deletes_message(self):
        gm = GameManager()
        game = _night_game(gm)
        game.mason_night_reminder_chat_id = 900
        game.mason_night_reminder_message_id = 55
        game.mason_night_reminder_initial_pending_uids = [10]
        bot = self._bot()
        await cleanup_mason_night_helper_reminder(bot, game)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.mason_night_reminder_message_id)

    async def test_new_night_bumps_generation(self):
        gm = GameManager()
        game = _night_game(gm)
        _seed_pending_cast(gm, game)
        bot = self._bot()
        game.mason_night_reminder_generation = 3
        with patch("bot.mason_night_reminder.asyncio.sleep", new=AsyncMock()):
            schedule_mason_night_helper_reminder(bot, game)
            cancel_mason_night_reminder_task(game.room_code)
        self.assertEqual(game.mason_night_reminder_generation, 4)

    async def test_maybe_finish_cleans_up_reminder(self):
        gm = GameManager()
        game = _night_game(gm)
        gm.add_player(game, _p(10, "Ali", Role.TOWN_SIMPLE, seat=1))
        _mafia_done(game)
        _mark_roles_done(game)
        game.mason_night_wait_ok_uids = [10]
        game.mason_night_reminder_chat_id = 900
        game.mason_night_reminder_message_id = 9
        game.mason_night_reminder_initial_pending_uids = [10]
        game.mason_night_reminder_last_text = "old"
        bot = self._bot()
        with patch("bot.no_host_night_ready.maybe_finish_no_host_parallel_night", new=AsyncMock()):
            await maybe_finish_mason_parallel_night(bot, game, gm)
        bot.delete_message.assert_awaited()


class MasonNightReminderIsolationTests(unittest.TestCase):
    def test_bazpors_collect_returns_empty(self):
        gm = GameManager()
        game = gm.create_game(host_id=1, scenario_name="bazpors", max_players=10, bazpors_host_mode="no_host")
        assert game is not None
        gm.add_player(game, _p(10, "A", Role.CITIZEN, seat=1))
        self.assertEqual(collect_mason_night_pending_holder_uids(game, gm), [])

    def test_mozakere_collect_returns_empty(self):
        gm = GameManager()
        game = gm.create_game(host_id=1, scenario_name="mozakere", max_players=12, bazpors_host_mode="no_host")
        assert game is not None
        self.assertEqual(collect_mason_night_pending_holder_uids(game, gm), [])

    def test_russian_collect_returns_empty(self):
        gm = GameManager()
        game = gm.create_game(host_id=1, scenario_name="russian_mafia", max_players=8, bazpors_host_mode="host_helper")
        assert game is not None
        self.assertEqual(collect_mason_night_pending_holder_uids(game, gm), [])


if __name__ == "__main__":
    unittest.main()
