"""یادآور عمومی شب کمک‌کننده — سناریوهای غیر ماسون."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.night_helper_reminder import (
    REMINDER_DELAY_SEC,
    REMINDER_BUTTON_PARAGRAPH,
    REMINDER_PLAIN_PARAGRAPH,
    NIGHT_FINISH_HEADER,
    NIGHT_FINISH_HEADER_HTML,
    NAM10_FORCE_FINISH_WARNINGS,
    _send_reminder_if_needed,
    build_counted_night_reminder_text,
    build_generic_night_reminder_text,
    cancel_night_helper_reminder_task,
    cleanup_night_helper_reminder,
    night_reminder_outstanding_count,
    night_reminder_uses_force_finish,
    refresh_night_helper_reminder,
    schedule_night_helper_reminder,
)
from bot.room_mode import (
    is_bazpors_no_host_room,
    is_mozakere_no_host_room,
    is_namayande10_no_host_room,
)


def _p(uid, name, role, *, alive=True, seat=0):
    return Player(user_id=uid, full_name=name, username=None, role=role, is_alive=alive, seat=seat)


def _mozakere_game(gm, *, assistant_uid=900):
    game = gm.create_game(
        host_id=1, scenario_name="mozakere", max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "RMZ"
    gm.games["RMZ"] = game
    game.bot_assistant_user_id = assistant_uid
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = "night_actions"
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    game.no_host_night_entry_dispatched_night = 1
    return game


def _nam10_game(gm, *, assistant_uid=900, max_players=10, players=None):
    game = gm.create_game(
        host_id=1, scenario_name="namayande", max_players=max_players,
        nam10_no_host=True,
    )
    assert game is not None
    for pl in players or []:
        err = gm.add_player(game, pl)
        assert err is None, err
    game.room_code = "RNM"
    gm.games["RNM"] = game
    game.bot_assistant_user_id = assistant_uid
    game.no_host_assistant_narrator_active = True
    game.nmnd_narrator_night_count = 2
    game.nmnd_night2_night_count = 2
    game.nmnd_night2_entry_dispatched = True
    game.nmnd_night2_mode = True
    game.nmnd_night2_phase = "collecting"
    game.phase = Phase.NIGHT
    return game


def _russian_game(gm, *, assistant_uid=900):
    game = gm.create_game(
        host_id=1, scenario_name="russian_mafia", max_players=8,
        bazpors_host_mode="host_helper",
    )
    assert game is not None
    game.room_code = "RRU"
    gm.games["RRU"] = game
    game.bot_assistant_user_id = assistant_uid
    game.phase = Phase.NIGHT
    return game


class ModeAndTextTests(unittest.TestCase):
    def test_mode_matrix(self):
        gm = GameManager()
        self.assertIsNone(self._mode_for(gm.create_game(
            host_id=1, scenario_name="masoon", max_players=12,
            bazpors_host_mode="no_host")))
        moz = _mozakere_game(GameManager())
        self.assertEqual(self._mode_for(moz), "no_host_collect")
        nam = _nam10_game(GameManager())
        self.assertEqual(self._mode_for(nam), "nam10")
        rus = _russian_game(GameManager())
        self.assertEqual(self._mode_for(rus), "russian")
        # بازپرس semi_auto و salamat_test و تک‌تاز — بدون یادآور
        semi = gm.create_game(
            host_id=1, scenario_name="bazpors", max_players=10,
            bazpors_host_mode="semi_auto")
        assert semi is not None
        self.assertIsNone(self._mode_for(semi))

    def _mode_for(self, game):
        from bot.night_helper_reminder import _mode

        return _mode(game)

    def test_text_has_no_names_roles_seats(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "پزشک - خسروی", Role.DOCTOR, seat=1))
        gm.add_player(game, _p(20, "Reza", Role.CITIZEN, seat=2))
        text = build_generic_night_reminder_text(game)
        self.assertIn("🌙 اقدامات شبانه هنوز تکمیل نشده‌اند", text)
        self.assertIn("برخی از بازیکنان هنوز اقدامات شبانه خود را تکمیل نکرده‌اند.", text)
        for banned in ("پزشک", "خسروی", "Reza", "DOCTOR", "CITIZEN", "صندلی", "۱", "۲"):
            self.assertNotIn(banned, text)

    def test_text_with_button_for_force_finish_scenarios(self):
        gm = GameManager()
        moz = _mozakere_game(gm)
        self.assertIn(REMINDER_BUTTON_PARAGRAPH, build_generic_night_reminder_text(moz))
        self.assertTrue(night_reminder_uses_force_finish(moz))
        nam = _nam10_game(GameManager())
        self.assertIn(REMINDER_BUTTON_PARAGRAPH, build_generic_night_reminder_text(nam))
        self.assertTrue(night_reminder_uses_force_finish(nam))

    def test_text_without_button_for_buttonless_scenarios(self):
        gm = GameManager()
        game = _russian_game(gm)
        text = build_generic_night_reminder_text(game)
        self.assertIn(REMINDER_PLAIN_PARAGRAPH, text)
        self.assertNotIn(REMINDER_BUTTON_PARAGRAPH, text)
        self.assertFalse(night_reminder_uses_force_finish(game))

    def test_delay_constant_is_120(self):
        self.assertEqual(REMINDER_DELAY_SEC, 120.0)


class MozakereReminderDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        for code in ("RMZ", "RNM", "RRU"):
            cancel_night_helper_reminder_task(code)

    def _bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=4242))
        bot.delete_message = AsyncMock()
        return bot

    async def test_schedule_delays_and_sends_to_helper_only(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        # یک اقدام ناقص (مافیا منو ثبت نشده)
        game.no_host_mafia_night1_done = False
        bot = self._bot()

        async def _instant_sleep(_delay):
            return None

        with patch("bot.night_helper_reminder.asyncio.sleep", side_effect=_instant_sleep):
            with patch("bot.app_state.manager", gm):
                schedule_night_helper_reminder(bot, game)
                from bot.night_helper_reminder import _REMINDER_TASKS

                task = _REMINDER_TASKS.get("RMZ")
                self.assertIsNotNone(task)
                await task
        self.assertEqual(bot.send_message.await_count, 1)
        kwargs = bot.send_message.await_args.kwargs
        self.assertEqual(kwargs.get("chat_id"), 900)
        kb = kwargs.get("reply_markup")
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])

    async def test_no_send_when_all_ready(self):
        from bot.no_host_night_ready import all_no_host_parallel_night_ready

        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.no_host_citizen_night_confirmed_uids = [20]
        self.assertTrue(all_no_host_parallel_night_ready(game))
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        game.night_helper_reminder_night_count = 1
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        bot.send_message.assert_not_called()

    async def test_no_send_without_helper(self):
        gm = GameManager()
        game = _mozakere_game(gm, assistant_uid=None)
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        bot.send_message.assert_not_called()

    async def test_no_send_when_collect_inactive(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        game.no_host_night_parallel_collect_active = False
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        bot.send_message.assert_not_called()

    async def test_no_send_when_phase_ended(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        game.phase = Phase.ENDED
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        bot.send_message.assert_not_called()

    async def test_stale_generation_blocked(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        game.night_helper_reminder_generation = 5
        await _send_reminder_if_needed(bot, game, gm, generation=4, night_count=1)
        bot.send_message.assert_not_called()

    async def test_old_night_stamp_blocked(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        game.no_host_mafia_night1_done = False
        game.bazpors_narrator_night_count = 2
        bot = self._bot()
        game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, gm, generation=1, night_count=1)
        bot.send_message.assert_not_called()

    async def test_duplicate_send_prevented(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_cleanup_deletes_message_and_clears_state(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        game.night_helper_reminder_chat_id = 900
        game.night_helper_reminder_message_id = 55
        bot = self._bot()
        await cleanup_night_helper_reminder(bot, game)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.night_helper_reminder_message_id)
        self.assertIsNone(game.night_helper_reminder_chat_id)

    async def test_reschedule_bumps_generation_and_cancels_old_task(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        bot = self._bot()
        game.night_helper_reminder_generation = 3
        with patch("bot.night_helper_reminder.asyncio.sleep", new=AsyncMock()):
            schedule_night_helper_reminder(bot, game)
            first = game.night_helper_reminder_generation
            schedule_night_helper_reminder(bot, game)
            second = game.night_helper_reminder_generation
            cancel_night_helper_reminder_task("RMZ")
        self.assertEqual(first, 4)
        self.assertEqual(second, 5)

    async def test_nam10_night_stamp_uses_night2_count(self):
        from bot.night_helper_reminder import night_reminder_night_stamp

        gm = GameManager()
        game = _nam10_game(gm)
        self.assertEqual(night_reminder_night_stamp(game), 2)

    async def test_russian_mode_no_button(self):
        gm = GameManager()
        game = _russian_game(gm)
        game.russian_mafia_night_index = 1
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        with patch(
            "bot.night_helper_reminder.night_reminder_all_ready",
            return_value=False,
        ):
            await _send_reminder_if_needed(bot, game, gm, generation=gen, night_count=1)
        self.assertEqual(bot.send_message.await_count, 1)
        kb = bot.send_message.await_args.kwargs.get("reply_markup")
        self.assertIsNone(kb)


class CountedReminderTextTests(unittest.TestCase):
    def test_mozakere_counted_text_generic_and_privacy(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "پزشک - خسروی", Role.DOCTOR, seat=1))
        gm.add_player(game, _p(20, "Reza", Role.CITIZEN, seat=2))
        text = build_counted_night_reminder_text(game, 4)
        self.assertIn(NIGHT_FINISH_HEADER_HTML, text)
        self.assertNotIn(NIGHT_FINISH_HEADER, text)
        self.assertIn("هنوز ۴ اقدام شبانه تکمیل نشده است، فاز شب همچنان ادامه دارد.", text)
        self.assertIn("لطفاً از بازیکنان بخواهید اقدامات شبانه خود را تکمیل و تأیید کنند.", text)
        self.assertIn("گزینه «اتمام شب»", text)
        self.assertIn("اقدامات تأییدشده محاسبه می‌شوند", text)
        for banned in ("پزشک", "خسروی", "Reza", "DOCTOR", "CITIZEN", "صندلی"):
            self.assertNotIn(banned, text)
        # بدون هشدارهای سرباز/اسنایپر
        self.assertNotIn("🪖", text)
        self.assertNotIn("🎯", text)

    def test_nam10_ten_player_no_warnings(self):
        gm = GameManager()
        game = _nam10_game(gm, max_players=10)
        text = build_counted_night_reminder_text(game, 2)
        self.assertIn(NIGHT_FINISH_HEADER, text)
        self.assertNotIn("⚠️ قوانین مهم اتمام اجباری شب", text)
        self.assertNotIn(NAM10_FORCE_FINISH_WARNINGS, text)

    def test_nam10_thirteen_with_soldier_has_warnings(self):
        gm = GameManager()
        game = _nam10_game(
            gm, max_players=13,
            players=[_p(30, "SoldierPerson", Role.SOLDIER, seat=1)],
        )
        text = build_counted_night_reminder_text(game, 3)
        self.assertIn("⚠️ قوانین مهم اتمام اجباری شب در سناریوی نماینده", text)
        self.assertIn("🪖 سرباز:", text)
        self.assertIn("🎯 اسنایپر موقت:", text)
        self.assertIn("سرباز در پایان همان شب از بازی خارج خواهد شد.", text)
        self.assertIn("خودش در پایان همان شب از بازی خارج خواهد شد.", text)
        # هشدارها عمومی‌اند — هویت دارندهٔ فعلی نقش‌ها افشا نمی‌شود
        self.assertNotIn("SoldierPerson", text)

    def test_nam10_thirteen_without_soldier_no_warnings(self):
        gm = GameManager()
        game = _nam10_game(gm, max_players=13)
        text = build_counted_night_reminder_text(game, 3)
        self.assertNotIn("⚠️ قوانین مهم اتمام اجباری شب", text)

    def test_counted_text_not_used_for_buttonless_scenarios(self):
        gm = GameManager()
        game = _russian_game(gm)
        self.assertFalse(night_reminder_uses_force_finish(game))

    def test_mozakere_outstanding_count_from_labels(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = False
        from bot.no_host_night_ready import pending_no_host_night_actor_labels

        self.assertEqual(
            night_reminder_outstanding_count(game),
            len(pending_no_host_night_actor_labels(game)),
        )
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.no_host_citizen_night_confirmed_uids = [20]
        self.assertEqual(night_reminder_outstanding_count(game), 0)

    def test_nam10_outstanding_count_from_required_keys(self):
        gm = GameManager()
        game = _nam10_game(
            gm, max_players=13,
            players=[_p(30, "SoldierPerson", Role.SOLDIER, seat=1)],
        )
        from bot.nam10.night2 import night2_required_keys

        self.assertEqual(
            night_reminder_outstanding_count(game),
            len(night2_required_keys(game)),
        )
        self.assertGreaterEqual(night_reminder_outstanding_count(game), 1)


class CountedReminderRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        for code in ("RMZ", "RNM", "RRU"):
            cancel_night_helper_reminder_task(code)

    def _bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=4242))
        bot.edit_message_text = AsyncMock()
        bot.delete_message = AsyncMock()
        return bot

    async def _send_first(self, bot, game, gm):
        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(
            bot, game, gm, generation=gen, night_count=night_reminder_night_stamp_of(game)
        )
        self.assertIsNotNone(game.night_helper_reminder_message_id)

    async def test_mozakere_send_uses_counted_text_and_button(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        await self._send_first(bot, game, gm)
        kwargs = bot.send_message.await_args.kwargs
        text = kwargs.get("text") or ""
        self.assertIn(NIGHT_FINISH_HEADER_HTML, text)
        self.assertIn("اقدام شبانه تکمیل نشده است", text)
        self.assertNotIn("Boss", text)
        kb = kwargs.get("reply_markup")
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])
        self.assertGreaterEqual(game.night_helper_reminder_last_count, 1)

    async def test_mozakere_refresh_edits_in_place_with_button(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "Ctmp", Role.CITIZEN, seat=2))
        # سه الزام ناتمام در ارسال اول (مافیا + شات + شهرونده‌ها)
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        await self._send_first(bot, game, gm)
        self.assertIsNotNone(game.night_helper_reminder_last_count)
        first_message_id = game.night_helper_reminder_message_id
        # شمارندهٔ جدید متفاوت ولی غیرصفر → edit همان پیام با دکمهٔ حفظ‌شده
        game.night_helper_reminder_last_count = 7
        with patch(
            "bot.night_helper_reminder.night_reminder_outstanding_count",
            return_value=3,
        ):
            await refresh_night_helper_reminder(bot, game)
        bot.edit_message_text.assert_awaited_once()
        kwargs = bot.edit_message_text.await_args.kwargs
        self.assertEqual(kwargs.get("chat_id"), 900)
        self.assertEqual(kwargs.get("message_id"), first_message_id)
        text = kwargs.get("text") or ""
        self.assertIn("هنوز ۳ اقدام شبانه تکمیل نشده است", text)
        kb = kwargs.get("reply_markup")
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])
        self.assertEqual(game.night_helper_reminder_last_count, 3)

    async def test_refresh_skips_noop_edit(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        await self._send_first(bot, game, gm)
        await refresh_night_helper_reminder(bot, game)
        bot.edit_message_text.assert_not_awaited()
        bot.delete_message.assert_not_awaited()

    async def test_refresh_deletes_at_zero_count(self):
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = False
        bot = self._bot()
        await self._send_first(bot, game, gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.no_host_citizen_night_confirmed_uids = [20]
        await refresh_night_helper_reminder(bot, game)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.night_helper_reminder_message_id)
        self.assertIsNone(game.night_helper_reminder_last_count)

    async def test_nam10_refresh_edit_and_zero_delete(self):
        gm = GameManager()
        game = _nam10_game(
            gm, max_players=13,
            players=[_p(30, "SoldierPerson", Role.SOLDIER, seat=1)],
        )
        bot = self._bot()
        await self._send_first(bot, game, gm)
        self.assertEqual(game.night_helper_reminder_last_count, 1)
        # بدون تغییر → بدون edit
        await refresh_night_helper_reminder(bot, game)
        bot.edit_message_text.assert_not_awaited()
        # صفر شدن شمارنده (شارژ سرباز + اوکی اجباری) → حذف پیام
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 2
        game.nmnd_night2_soldier_forfeited = True
        game.nmnd_night2_waiting_acked[Role.SOLDIER.value] = [30]
        await refresh_night_helper_reminder(bot, game)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.night_helper_reminder_message_id)


def night_reminder_night_stamp_of(game):
    from bot.night_helper_reminder import night_reminder_night_stamp

    return night_reminder_night_stamp(game)




class MozakereReminderLiveTests(unittest.IsolatedAsyncioTestCase):
    """یادآور شب مذاکره — HTML بولد، شمارندهٔ زنده، حذف/بستن، بازیابی ری‌استارت."""

    async def asyncTearDown(self):
        cancel_night_helper_reminder_task("RMZ")

    def _bot(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=4242))
        bot.edit_message_text = AsyncMock()
        bot.delete_message = AsyncMock()
        return bot

    def _game(self, gm):
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C", Role.CITIZEN, seat=2))
        game.no_host_mafia_night1_done = False
        return game

    async def _send_first(self, bot, game, gm):
        from bot.night_helper_reminder import night_reminder_night_stamp

        gen = game.night_helper_reminder_generation = 1
        await _send_reminder_if_needed(
            bot,
            game,
            gm,
            generation=gen,
            night_count=night_reminder_night_stamp(game),
        )

    async def test_private_reminder_is_html_bold_with_spec_lines(self):
        gm = GameManager()
        game = self._game(gm)
        bot = self._bot()
        await self._send_first(bot, game, gm)
        kwargs = bot.send_message.await_args.kwargs
        text = kwargs.get("text") or ""
        self.assertIn("🌙 <b>قابلیت اتمام شب</b>", text)
        self.assertIn(
            "به دلیل اینکه هنوز", text
        )
        self.assertIn(
            "اقدام شبانه تکمیل نشده است، فاز شب همچنان ادامه دارد.", text
        )
        self.assertIn(
            "لطفاً از بازیکنان بخواهید اقدامات شبانه خود را تکمیل و تأیید کنند.",
            text,
        )
        self.assertIn(
            "در صورت نیاز، می‌توانید با انتخاب گزینه «اتمام شب»، "
            "شب جاری را به پایان برسانید.",
            text,
        )
        self.assertIn(
            "در این حالت، اقدامات تأییدشده محاسبه می‌شوند و اقدامات ناتمام "
            "مطابق قوانین سناریو تعیین تکلیف خواهند شد.",
            text,
        )
        self.assertEqual(kwargs.get("parse_mode"), "HTML")
        # privacy: no names/roles in the reminder
        self.assertNotIn("Boss", text)
        self.assertNotIn("CITIZEN", text)
        # keyboard: only the finish button
        kb = kwargs.get("reply_markup")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])

    async def test_namayande_send_stays_plain_text(self):
        gm = GameManager()
        game = _nam10_game(gm, max_players=13, players=[_p(30, "SoldierPerson", Role.SOLDIER, seat=1)])
        bot = self._bot()
        gen = game.night_helper_reminder_generation = 1
        from bot.night_helper_reminder import night_reminder_night_stamp

        await _send_reminder_if_needed(
            bot,
            game,
            gm,
            generation=gen,
            night_count=night_reminder_night_stamp(game),
        )
        kwargs = bot.send_message.await_args.kwargs
        self.assertNotIn("<b>", kwargs.get("text") or "")
        self.assertEqual(kwargs.get("parse_mode"), None)
        self.assertNotIn("parse_mode", kwargs)

    async def test_counter_decrements_real_confirmations_not_tentative(self):
        gm = GameManager()
        game = self._game(gm)
        bot = self._bot()
        await self._send_first(bot, game, gm)
        self.assertEqual(game.night_helper_reminder_last_count, 2)
        # mafia menu confirmed, shot target picked TENTATIVELY (awaiting confirm)
        from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT

        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.mozakere_negotiation_tonight = False
        game.no_host_negotiator_flow_active = False
        game.no_host_negotiator_pick_confirmed = True
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_shot_pending_uid = 20
        game.no_host_mafia_shot_awaiting_confirm = True
        # tentative selection does NOT decrement the counter
        self.assertEqual(night_reminder_outstanding_count(game), 2)
        # real confirmation → decrement
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_flow_active = False
        self.assertEqual(night_reminder_outstanding_count(game), 1)
        # citizens confirm → 0 → reminder deleted automatically
        game.no_host_citizen_night_confirmed_uids = [20]
        await refresh_night_helper_reminder(bot, game)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.night_helper_reminder_message_id)
        self.assertIsNone(game.night_helper_reminder_last_count)

    async def test_reminder_removed_on_phase_transition(self):
        gm = GameManager()
        game = self._game(gm)
        bot = self._bot()
        await self._send_first(bot, game, gm)
        game.no_host_night_parallel_collect_active = False
        await refresh_night_helper_reminder(bot, game)
        bot.delete_message.assert_awaited()
        self.assertIsNone(game.night_helper_reminder_message_id)
        # stale force-finish press after removal is rejected by the guard
        from bot.mozakere_force_finish_night import (
            mozakere_night_force_finish_collection_active,
        )

        self.assertFalse(mozakere_night_force_finish_collection_active(game))

    async def test_delete_failure_strips_button_and_marks_closed(self):
        gm = GameManager()
        game = self._game(gm)
        bot = self._bot()
        await self._send_first(bot, game, gm)
        from bot.night_helper_reminder import NIGHT_REMINDER_CLOSED_FALLBACK_TEXT

        bot.delete_message = AsyncMock(side_effect=Exception("boom"))
        game.no_host_citizen_night_confirmed_uids = [20]
        from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE

        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
        game.no_host_negotiator_pick_confirmed = True
        game.mozakere_negotiation_tonight = True
        game.no_host_negotiator_flow_active = False
        await refresh_night_helper_reminder(bot, game)
        bot.edit_message_text.assert_awaited()
        ek = bot.edit_message_text.await_args.kwargs
        self.assertEqual(ek.get("text"), NIGHT_REMINDER_CLOSED_FALLBACK_TEXT)
        self.assertIsNone(ek.get("reply_markup"))
        self.assertIsNone(game.night_helper_reminder_message_id)

    async def test_delete_badrequest_also_falls_back_to_closed(self):
        from aiogram.exceptions import TelegramBadRequest

        gm = GameManager()
        game = self._game(gm)
        bot = self._bot()
        await self._send_first(bot, game, gm)
        from bot.night_helper_reminder import NIGHT_REMINDER_CLOSED_FALLBACK_TEXT

        bot.delete_message = AsyncMock(
            side_effect=TelegramBadRequest(method=None, message="x")
        )
        game.no_host_citizen_night_confirmed_uids = [20]
        from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE

        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
        game.no_host_negotiator_pick_confirmed = True
        game.mozakere_negotiation_tonight = True
        game.no_host_negotiator_flow_active = False
        await refresh_night_helper_reminder(bot, game)
        bot.edit_message_text.assert_awaited()
        ek = bot.edit_message_text.await_args.kwargs
        self.assertEqual(ek.get("text"), NIGHT_REMINDER_CLOSED_FALLBACK_TEXT)

    async def test_restart_recovery_sends_immediately_after_elapsed(self):
        import time

        gm = GameManager()
        game = self._game(gm)
        game.night_helper_reminder_night_count = night_reminder_night_stamp_of(game)
        game.night_helper_reminder_scheduled_at = (
            time.time() - REMINDER_DELAY_SEC - 5
        )
        game.night_helper_reminder_generation = 1
        bot = self._bot()
        with patch("bot.app_state.manager", gm):
            from bot.night_helper_reminder import (
                recover_night_helper_reminders_after_restart,
            )

            await recover_night_helper_reminders_after_restart(bot)
        bot.send_message.assert_awaited_once()
        self.assertIsNotNone(game.night_helper_reminder_message_id)
        self.assertEqual(
            bot.send_message.await_args.kwargs.get("parse_mode"), "HTML"
        )

    async def test_restart_recovery_no_duplicate_when_message_persisted(self):
        import time

        gm = GameManager()
        game = self._game(gm)
        bot = self._bot()
        await self._send_first(bot, game, gm)
        message_id = game.night_helper_reminder_message_id
        game.night_helper_reminder_scheduled_at = time.time() - 1
        bot.send_message.reset_mock()
        with patch("bot.app_state.manager", gm):
            from bot.night_helper_reminder import (
                recover_night_helper_reminders_after_restart,
            )

            await recover_night_helper_reminders_after_restart(bot)
        bot.send_message.assert_not_awaited()
        self.assertEqual(game.night_helper_reminder_message_id, message_id)


if __name__ == "__main__":
    unittest.main()
