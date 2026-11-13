"""بازپرس (no_host) — حذف پنل «شب … آغاز شد»، یادآور ۱۲۰ثانیه با شمارندهٔ زنده،
اتمام اجباری شب کمک‌کننده («اتمام شب» + تأیید دومرحله‌ای) و اصلاح پنل هانتر.

ذخیره‌سازی ایزوله؛ هرگز به دیتابیس/اتاق‌های تولیدی دست نمی‌زند.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, Update, User

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import bot.app_state as _app_state
from bot.game import GameManager as _GM

_app_state.manager = _GM()

import bot.db as _db

_db.init_db()

from bot.game import GameManager, bazpors_roles_for_count
from bot.handlers import register_all_handlers
from bot.models import Phase, Player, Role

FINISH_EVENT = "bazpors.force_finish_night"
NIGHT_START_TITLE_MARK = "آغاز شد"


def _force_reset_all_routers():
    from aiogram import Router

    seen = set()
    for mod in list(sys.modules.values()):
        try:
            for attr in vars(mod).values():
                if isinstance(attr, Router) and id(attr) not in seen:
                    seen.add(id(attr))
                    attr._parent_router = None
        except Exception:
            continue


def _make_dispatcher():
    dp = Dispatcher()
    try:
        register_all_handlers(dp)
    except RuntimeError:
        _force_reset_all_routers()
        register_all_handlers(dp)
    return dp


class _RecordingBot:
    id = 42

    def __init__(self):
        self.calls = []

    async def __call__(self, method, *args, **kwargs):
        self.calls.append(method)
        from types import SimpleNamespace

        chat_id = getattr(method, "chat_id", args[0] if args else None)
        return SimpleNamespace(
            message_id=len(self.calls) + 10_000,
            chat=SimpleNamespace(id=chat_id),
            date=datetime.now(timezone.utc),
        )

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _record(*args, **kwargs):
            from types import SimpleNamespace

            m = SimpleNamespace(
                message_id=len(self.calls) + 10_000,
                chat=SimpleNamespace(id=kwargs.get("chat_id", args[0] if args else None)),
                date=datetime.now(timezone.utc),
            )
            m.__dict__["_cls"] = name
            m.__dict__["_rec_args"] = tuple(args)
            m.__dict__["_rec_kwargs"] = dict(kwargs)
            self.calls.append(m)
            return m

        return _record

    def sends(self):
        out = []
        for c in self.calls:
            if type(c).__name__ == "SendMessage":
                out.append((getattr(c, "chat_id", None), getattr(c, "text", "")))
            elif getattr(c, "_cls", None) == "send_message":
                kw = getattr(c, "_rec_kwargs", {}) or {}
                args = getattr(c, "_rec_args", ())
                chat = kw.get("chat_id", args[0] if args else None)
                text = kw.get("text", args[1] if len(args) > 1 else "")
                out.append((chat, text))
        return out

    def texts(self):
        out = []
        for c in self.calls:
            if type(c).__name__ in ("SendMessage", "EditMessageText"):
                out.append(getattr(c, "text", "") or "")
            elif getattr(c, "_cls", None) in ("send_message", "edit_message_text"):
                kw = getattr(c, "_rec_kwargs", {}) or {}
                args = getattr(c, "_rec_args", ())
                out.append(kw.get("text", args[1] if len(args) > 1 else "") or "")
        return out

    def acks(self):
        out = []
        for c in self.calls:
            if type(c).__name__ in ("AnswerCallbackQuery", "CallbackQueryAnswer"):
                out.append(getattr(c, "text", None))
            elif getattr(c, "_cls", None) == "answer_callback_query":
                kw = getattr(c, "_rec_kwargs", {}) or {}
                args = getattr(c, "_rec_args", ())
                out.append(kw.get("text", args[0] if args else None))
        return out

    def send_kwargs_list(self):
        out = []
        for c in self.calls:
            if type(c).__name__ == "SendMessage":
                out.append(
                    {
                        "text": getattr(c, "text", ""),
                        "reply_markup": getattr(c, "reply_markup", None),
                        "parse_mode": getattr(c, "parse_mode", None),
                    }
                )
            elif getattr(c, "_cls", None) == "send_message":
                kw = getattr(c, "_rec_kwargs", {}) or {}
                args = getattr(c, "_rec_args", ())
                out.append(
                    {
                        "text": kw.get("text", args[1] if len(args) > 1 else ""),
                        "reply_markup": kw.get("reply_markup"),
                        "parse_mode": kw.get("parse_mode"),
                    }
                )
        return out


def _audit_force_finish_dispositions(game):
    path = game.audit_log_path
    with open(path, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("event") == "bazpors.force_finish_night":
                return e.get("force_finished_no_action", {})
    return {}


class _BazporsNightHelperBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db = root / "t.sqlite3"
        self._audit = root / "audit"
        self._audit.mkdir()
        self._patches = [
            patch("bot.config.get_database_path", return_value=self._db),
            patch("bot.config.get_game_audit_log_dir", return_value=self._audit),
            patch.dict(
                os.environ,
                {
                    "DATABASE_PATH": str(self._db),
                    "GAME_AUDIT_LOG_DIR": str(self._audit),
                    "GAME_AUDIT_LOG_ENABLED": "1",
                },
                clear=False,
            ),
        ]
        for p in self._patches:
            p.start()
        from bot import db

        db.init_db()
        self.manager = GameManager()
        self.bot = _RecordingBot()
        self.dp = _make_dispatcher()
        import bot.main as main_mod

        self._mgr_patches = [
            patch.object(_app_state, "manager", self.manager),
            patch.object(main_mod, "manager", self.manager),
        ]
        from bot.game import GameManager as _GMc

        for name, mod in list(sys.modules.items()):
            m = getattr(mod, "manager", None)
            if isinstance(m, _GMc) and m is not self.manager:
                self._mgr_patches.append(patch.object(mod, "manager", self.manager))
        for p in self._mgr_patches:
            p.start()
        self._reminder_rooms = set()

    def tearDown(self):
        for code in self._reminder_rooms:
            from bot.night_helper_reminder import cancel_night_helper_reminder_task

            cancel_night_helper_reminder_task(code)
        for p in reversed(self._mgr_patches):
            p.stop()
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    def _room(self, *, night=1, assistant=99, count=12, collect=True):
        from bot.bazpors_narrator import NIGHT_START
        from bot.game_audit_log import init_audit_log

        gm = self.manager
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=count,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for i, role in enumerate(bazpors_roles_for_count(count)):
            uid = -(920000 + i)
            err = gm.add_player(
                game, Player(uid, f"پ-{i}", None, role, seat=i + 1, is_alive=True)
            )
            assert err is None, err
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = assistant
        game.no_host_assistant_narrator_active = True
        game.no_host_night_parallel_collect_active = collect
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = night
        game.no_host_night_entry_dispatched_night = night
        init_audit_log(game)
        self.game = game
        self._reminder_rooms.add(game.room_code)
        return game

    def _role_uid(self, game, role):
        for pl in game.players.values():
            if pl.role == role and pl.is_alive:
                return pl.user_id
        raise AssertionError(f"no {role} player")

    async def _press(self, cbdata, actor_uid):
        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        cq = CallbackQuery(
            id=f"cq-{len(self.bot.calls)}",
            from_user=actor,
            chat_instance="ci",
            data=cbdata,
            message=Message(
                message_id=777,
                date=datetime.now(timezone.utc),
                chat=Chat(id=actor_uid, type=ChatType.PRIVATE),
                from_user=actor,
            ),
        )
        update = Update(
            update_id=4_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    async def _press_pmr(self, act, as_uid, *, tid=0, actor_uid=None):
        from bot.observer_delivery import PlayerMirrorCb

        data = PlayerMirrorCb(
            code=self.game.room_code, act=act, as_uid=as_uid, tid=tid
        ).pack()
        await self._press(data, actor_uid or as_uid)

    async def _press_bzh(self, act, kind, *, actor_uid=99):
        from bot.bazpors_force_finish_night import BazporsHelperCb

        data = BazporsHelperCb(
            code=self.game.room_code, act=act, kind=kind
        ).pack()
        await self._press(data, actor_uid)

    def _audit_events(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    # ----------------------------------------------------------------
    def _confirm_everything(self, game):
        from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT
        from bot.no_host_night_ready import _alive_citizen_uids
        from bot.roles.night_state import yaku_night_state

        game.no_host_citizen_night_confirmed_uids = list(_alive_citizen_uids(game))
        game.no_host_ruintan_night_confirmed = True
        game.no_host_night1_hunter_done = True
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        game.no_host_shiad_pick_confirmed = True
        game.no_host_detective_pick_confirmed = True
        game.no_host_sniper_pick_confirmed = True
        game.no_host_doctor_pick_confirmed = True
        game.no_host_interrog_pick_confirmed = True
        yaku_night_state(game).no_host_done = True
        game.no_host_mafia_nato_done = True


class SuppressionTests(_BazporsNightHelperBase):
    """آیتم ۱: پنل «شب … آغاز شد» دیگر ارسال نمی‌شود (راه‌های refresh هم)."""

    async def test_01_night_start_helper_panel_removed(self):
        from bot.bazpors_narrator import build_host_message_and_keyboard, push_host_step

        game = self._room()
        text, kb = build_host_message_and_keyboard(game, self.manager)
        self.assertEqual((text, kb), ("", None))
        await push_host_step(self.bot, game, self.manager)
        for _chat, body in self.bot.sends():
            self.assertNotIn(NIGHT_START_TITLE_MARK, body)

    async def test_02_legacy_n1_branch_also_suppressed(self):
        from bot.bazpors_narrator import build_host_message_and_keyboard

        # parallel collect off — the old n==1 «هانتر و تیم مافیا» branch
        game = self._room(collect=False)
        text, kb = build_host_message_and_keyboard(game, self.manager)
        self.assertEqual((text, kb), ("", None))

    async def test_03_semi_auto_host_mode_unaffected(self):
        from bot.bazpors_narrator import NIGHT_START, build_host_message_and_keyboard

        gam = self.manager
        game = gam.create_game(
            host_id=1, scenario_name="bazpors", max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        for i, role in enumerate(bazpors_roles_for_count(10)):
            uid = -(930000 + i)
            err = gam.add_player(
                game, Player(uid, f"پ-{i}", None, role, seat=i + 1, is_alive=True)
            )
            assert err is None, err
        game.roles_dealt = True
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 1
        text, _kb = build_host_message_and_keyboard(game, self.manager)
        self.assertNotEqual(text, "")

    async def test_04_other_scenarios_not_suppressed(self):
        from bot.bazpors_narrator import NIGHT_START, build_host_message_and_keyboard

        for scenario, mode in (("masoon", "no_host"), ("russian_mafia", "host_helper")):
            gam = self.manager
            game = gam.create_game(
                host_id=1, scenario_name=scenario,
                max_players=12 if scenario == "masoon" else 8,
                bazpors_host_mode=mode,
            )
            assert game is not None
            game.bazpors_narrator_step = NIGHT_START
            game.bazpors_narrator_night_count = 1
            game.no_host_assistant_narrator_active = True
            game.no_host_night_parallel_collect_active = False
            game.no_host_night1_hunter_done = False
            game.no_host_mafia_night1_done = False
            text, _kb = build_host_message_and_keyboard(game, self.manager)
            self.assertNotEqual(text, "", msg=scenario)


class ReminderTests(_BazporsNightHelperBase):
    """آیتم‌های ۲–۶: یادآور ۱۲۰ثانیه، شمارندهٔ بولد، حذف/بستن بازیابی."""

    async def _send_first_reminder(self, game):
        from bot.night_helper_reminder import (
            _REMINDER_TASKS,
            schedule_night_helper_reminder,
        )

        game.night_helper_reminder_generation = 1
        with patch(
            "bot.night_helper_reminder.asyncio.sleep", new=AsyncMock()
        ):
            schedule_night_helper_reminder(self.bot, game)
            task = _REMINDER_TASKS.get(game.room_code)
            self.assertIsNotNone(task)
            await task
        self.assertIsNotNone(game.night_helper_reminder_message_id)

    async def test_05_reminder_after_120s_html_bold_count_and_button(self):
        from bot.night_helper_reminder import (
            REMINDER_DELAY_SEC,
            counted_night_reminder_header_and_parse_mode,
            night_reminder_uses_counted_text,
            night_reminder_uses_force_finish,
        )
        from bot.no_host_night_ready import pending_no_host_night_actor_labels

        game = self._room()
        self.assertEqual(REMINDER_DELAY_SEC, 120.0)
        self.assertTrue(night_reminder_uses_force_finish(game))
        self.assertTrue(night_reminder_uses_counted_text(game))
        self.assertEqual(
            counted_night_reminder_header_and_parse_mode(game),
            ("🌙 <b>قابلیت اتمام شب</b>", "HTML"),
        )
        await self._send_first_reminder(game)
        kw = self.bot.send_kwargs_list()[-1]
        text = kw["text"]
        self.assertIn("🌙 <b>قابلیت اتمام شب</b>", text)
        self.assertIn("هنوز <b>", text)
        self.assertIn("اقدام شبانه</b> تکمیل نشده است", text)
        self.assertEqual(kw["parse_mode"], "HTML")
        kb = kw["reply_markup"]
        buttons = [b.text for row in kb.inline_keyboard for b in row]
        self.assertEqual(buttons, ["🌙 اتمام شب"])
        self.assertEqual(
            game.night_helper_reminder_last_count,
            len(pending_no_host_night_actor_labels(game)),
        )
        self.assertGreaterEqual(game.night_helper_reminder_last_count, 1)
        # sent to the authorised bot helper only (chat 99)
        chat_id = self.bot.sends()[-1][0]
        self.assertEqual(chat_id, 99)

    async def test_06_no_identities_in_reminder(self):
        game = self._room()
        await self._send_first_reminder(game)
        text = self.bot.send_kwargs_list()[-1]["text"]
        for banned in (
            "پ-", "هانتر", "پزشک", "شیاد", "کارآگاه", "اسنایپر",
            "بازپرس", "تیم مافیا", "شهروند", "رویین",
        ):
            self.assertNotIn(banned, text)

    async def test_07_tentative_not_counted_real_confirm_decrements(self):
        from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT
        from bot.night_helper_reminder import night_reminder_outstanding_count

        game = self._room()
        game.night_helper_reminder_generation = 1
        await self._send_first_reminder(game)
        count0 = night_reminder_outstanding_count(game)
        # mafia menu confirmed, but the target only TENTATIVELY picked
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_shot_pending_uid = 10
        game.no_host_mafia_shot_awaiting_confirm = True
        count1 = night_reminder_outstanding_count(game)
        # a tentative selection must NOT lower the count
        self.assertEqual(count0, count1)
        # a real confirmation (shot registered) → decremented by exactly 1
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_flow_active = False
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        self.assertEqual(
            night_reminder_outstanding_count(game), count1 - 1
        )

    async def test_08_removed_at_zero_and_phase_exit(self):
        from bot.night_helper_reminder import refresh_night_helper_reminder

        # (a) count reaches zero → delete
        game = self._room()
        await self._send_first_reminder(game)
        self._confirm_everything(game)
        await refresh_night_helper_reminder(self.bot, game)
        self.assertIsNone(game.night_helper_reminder_message_id)
        self.assertIsNone(game.night_helper_reminder_last_count)

        # (b) phase leaves the collect window → delete
        game2 = self._room(night=2)
        await self._send_first_reminder(game2)
        game2.no_host_night_parallel_collect_active = False
        await refresh_night_helper_reminder(self.bot, game2)
        self.assertIsNone(game2.night_helper_reminder_message_id)
        # stale force-finish press after removal is rejected
        from bot.bazpors_force_finish_night import (
            bazpors_night_force_finish_collection_active,
        )

        self.assertFalse(bazpors_night_force_finish_collection_active(game2))

    async def test_09_delete_failure_strips_button_and_closes(self):
        from bot.night_helper_reminder import (
            NIGHT_REMINDER_CLOSED_FALLBACK_TEXT,
            refresh_night_helper_reminder,
        )

        game = self._room()
        await self._send_first_reminder(game)
        self._confirm_everything(game)

        delete_calls = []

        async def _boom_delete(**kwargs):
            delete_calls.append(kwargs)
            raise Exception("telegram down")

        class _BrokenDeleteBot(_RecordingBot):
            def __getattr__(self, name):
                if name == "delete_message":
                    return _boom_delete
                return super().__getattr__(name)

        broken = _BrokenDeleteBot()
        self.bot.calls.clear()
        broken.calls = self.bot.calls
        await refresh_night_helper_reminder(broken, game)
        self.assertEqual(len(delete_calls), 1)
        edits = [
            dict(getattr(c, "_rec_kwargs", {}) or {})
            for c in self.bot.calls
            if getattr(c, "_cls", None) == "edit_message_text"
            or type(c).__name__ == "EditMessageText"
        ]
        self.assertTrue(edits)
        self.assertEqual(
            edits[0].get("text"), NIGHT_REMINDER_CLOSED_FALLBACK_TEXT
        )
        self.assertIsNone(edits[0].get("reply_markup"))
        self.assertIsNone(game.night_helper_reminder_message_id)


class ForceFinishFlowTests(_BazporsNightHelperBase):
    """آیتم‌های ۷–۱۸: دکمهٔ «اتمام شب»، تأیید دومرحله‌ای، پیش‌فرض‌های نقش‌ها."""

    async def test_10_button_helper_only_and_opens_confirm(self):
        from bot.bazpors_force_finish_night import (
            find_bazpors_bot_assistant_game,
        )

        game = self._room()
        self.assertIsNotNone(find_bazpors_bot_assistant_game(99, self.manager))
        self.assertIsNone(find_bazpors_bot_assistant_game(555, self.manager))

        # non-assistant press is rejected, nothing sent
        self.bot.calls.clear()
        await self._press_bzh("go", "force_night_btn", actor_uid=555)
        self.assertIn("فقط کمک‌کننده ربات.", self.bot.acks())
        self.assertFalse(game.bazpors_night_force_finished)

        # assistant press opens the confirm panel
        self.bot.calls.clear()
        await self._press_bzh("go", "force_night_btn", actor_uid=99)
        kw = self.bot.send_kwargs_list()[-1]
        self.assertIn("⚠️ تأیید اتمام شب", kw["text"])
        self.assertIn(
            "آیا مطمئن هستید که می‌خواهید شب جاری را به پایان برسانید؟",
            kw["text"],
        )
        self.assertIn(
            "اقدامات تأییدشده محاسبه می‌شوند و اقداماتی که هنوز تأیید نشده‌اند، "
            "بدون اثر در نظر گرفته خواهند شد.",
            kw["text"],
        )
        kb = kw["reply_markup"]
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertEqual(labels, ["✅ بله، اتمام شب", "❌ انصراف"])
        self.assertEqual(getattr(kb.inline_keyboard[0][0], "style", None), "success")
        self.assertIsNone(getattr(kb.inline_keyboard[0][1], "style", None))
        self.assertFalse(game.bazpors_night_force_finished)
        self.assertTrue(game.no_host_night_parallel_collect_active)

    async def test_11_cancel_makes_no_changes(self):
        from bot.bazpors_force_finish_night import _force_finish_confirm_keyboard
        from bot.no_host_night_ready import _mafia_night1_parallel_ready

        game = self._room()
        kb = _force_finish_confirm_keyboard(game)
        cancel_data = kb.inline_keyboard[0][1].callback_data
        await self._press(cancel_data, 99)
        # an answer was produced and the message was edited to the cancel text
        self.assertTrue(self.bot.acks())
        self.assertFalse(game.bazpors_night_force_finished)
        self.assertTrue(game.no_host_night_parallel_collect_active)
        # unconfirmed actions were NOT auto-confirmed
        self.assertFalse(_mafia_night1_parallel_ready(game))

    async def test_12_confirm_finishes_night_once_via_existing_pipeline(self):
        from bot import no_host_night_ready as readiness
        from bot.bazpors_force_finish_night import _force_finish_confirm_keyboard

        game = self._room()
        kb = _force_finish_confirm_keyboard(game)
        yes_data = kb.inline_keyboard[0][0].callback_data
        with patch.object(
            readiness,
            "finish_no_host_parallel_night_collect",
            new=AsyncMock(return_value=True),
        ) as finish:
            await self._press(yes_data, 99)
            self.assertIn("شب به پایان رسید", " ".join(a or "" for a in self.bot.acks()))
            finish.assert_awaited_once()
        self.assertTrue(game.bazpors_night_force_finished)
        self.assertIn(FINISH_EVENT, [e.get("event") for e in self._audit_events()])

        # duplicate / stale press after finish is rejected, no second run
        self.bot.calls.clear()
        with patch.object(
            readiness,
            "finish_no_host_parallel_night_collect",
            new=AsyncMock(return_value=True),
        ) as finish2:
            await self._press(yes_data, 99)
            finish2.assert_not_awaited()
        self.assertIn("فاز شب به پایان رسیده است", self.bot.acks()[0])

    async def test_13_mafia_confirmed_shot_preserved_unconfirmed_none(self):
        from bot.bazpors_force_finish_night import (
            force_finish_bazpors_night,
            normalize_pending_bazpors_night_actions,
        )
        from bot import no_host_night_ready as readiness
        from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT

        # (a) confirmed shot survives force-finish untouched
        game = self._room()
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_shot_flow_active = False
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        dispositions = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertNotIn("mafia_shot", dispositions)
        self.assertFalse(game.bazpors_mafia_shot_registered)

        # (b) unconfirmed shot → no-action, no invented target
        game2 = self._room()
        game2.no_host_mafia_night1_done = True
        game2.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game2.no_host_mafia_night1_flow_active = True
        game2.no_host_mafia_shot_flow_active = True
        game2.no_host_mafia_shot_pending_uid = 10
        game2.no_host_mafia_shot_awaiting_confirm = True
        dispositions2 = normalize_pending_bazpors_night_actions(game2, self.manager)
        self.assertIn("mafia_shot", dispositions2)
        self.assertTrue(game2.no_host_mafia_shot_done)
        self.assertIsNone(game2.no_host_mafia_shot_pending_uid)
        self.assertFalse(game2.no_host_mafia_shot_awaiting_confirm)
        self.assertFalse(game2.bazpors_mafia_shot_registered)

        # (c) menu never confirmed → no shot either, force-finish is idempotent
        game3 = self._room()
        game3.no_host_mafia_night1_done = False
        with patch.object(
            readiness,
            "finish_no_host_parallel_night_collect",
            new=AsyncMock(return_value=True),
        ) as finish3:
            await force_finish_bazpors_night(self.bot, game3, self.manager)
            await force_finish_bazpors_night(self.bot, game3, self.manager)
            finish3.assert_awaited_once()
        self.assertTrue(game3.no_host_mafia_night1_done)
        self.assertTrue(game3.no_host_mafia_shot_done)
        self.assertIsNone(game3.no_host_mafia_shot_pending_uid)

    async def test_14_doctor_sniper_no_effect_ammo_preserved(self):
        from bot.bazpors_force_finish_night import (
            normalize_pending_bazpors_night_actions,
        )
        from bot.roles.sniper import bullet_used

        game = self._room()
        doctor_uid = self._role_uid(game, Role.DOCTOR)
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_pending_save_uids = [doctor_uid]
        game.no_host_doctor_pending_none = False
        dispositions = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertIn("doctor", dispositions)
        self.assertTrue(game.no_host_doctor_pick_confirmed)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [])
        # no invented save / heal
        self.assertFalse(game.bazpors_doctor_save_uids)

        # sniper: unconfirmed pick → cleared; one-shot ammo NOT consumed
        game.no_host_sniper_flow_active = True
        game.no_host_sniper_pending_target_uid = 10
        game.no_host_sniper_pick_confirmed = False
        dispositions2 = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertIn("sniper", dispositions2)
        self.assertFalse(bullet_used(game))
        self.assertIsNone(game.no_host_sniper_pending_target_uid)
        self.assertTrue(game.no_host_sniper_pick_confirmed)

    async def test_15_shiad_interrogator_hunter_defaults(self):
        from bot.bazpors_force_finish_night import (
            normalize_pending_bazpors_night_actions,
        )
        from bot.roles.night_state import hunter_night_state

        game = self._room()
        # shiad: tentative target → cleared, no interference
        game.no_host_shiad_flow_active = True
        game.no_host_shiad_pending_tid = 10
        game.no_host_shiad_pick_confirmed = False
        dispositions = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertIn("shiad", dispositions)
        self.assertTrue(game.no_host_shiad_pick_confirmed)
        self.assertIsNone(game.no_host_shiad_pending_tid)
        self.assertIsNone(game.bazpors_shiad_target_uid)

        # interrogator: unconfirmed pick → cleared
        game.no_host_interrog_flow_active = True
        game.no_host_interrog_ui_phase = "pick"
        game.no_host_interrog_pick_confirmed = False
        dispositions2 = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertIn("interrogator", dispositions2)
        self.assertTrue(game.no_host_interrog_pick_confirmed)
        self.assertIsNone(game.no_host_interrog_ui_phase)

        # hunter: unconfirmed → done, no link
        game.no_host_night1_hunter_flow_active = True
        game.no_host_night1_hunter_done = False
        game.no_host_hunter_pending_pick_uid = 10
        game.no_host_hunter_awaiting_confirm = True
        dispositions3 = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertIn("hunter", dispositions3)
        self.assertTrue(game.no_host_night1_hunter_done)
        self.assertIsNone(game.no_host_hunter_pending_pick_uid)
        self.assertFalse(hunter_night_state(game).linked_this_night)

    async def test_16_nato_yaku_defaults_no_effect(self):
        from bot.bazpors_force_finish_night import (
            normalize_pending_bazpors_night_actions,
        )
        from bot.no_host_mafia_night1 import MAFIA_ACTION_NATO, MAFIA_ACTION_YAKU
        from bot.roles.night_state import yaku_night_state

        game = self._room()
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NATO
        game.no_host_mafia_nato_flow_active = True
        game.no_host_mafia_nato_pending_role = "civ"
        game.no_host_mafia_nato_pending_target_uid = 10
        dispositions = normalize_pending_bazpors_night_actions(game, self.manager)
        self.assertIn("nato", dispositions)
        self.assertTrue(game.no_host_mafia_nato_done)
        self.assertIsNone(game.no_host_mafia_nato_pending_role)
        self.assertIsNone(game.no_host_mafia_nato_pending_target_uid)

        game2 = self._room()
        game2.no_host_mafia_night1_done = True
        game2.no_host_mafia_night1_chosen_action = MAFIA_ACTION_YAKU
        state = yaku_night_state(game2)
        state.no_host_flow_active = True
        state.no_host_phase = "sac"
        state.no_host_pending_sac_uid = 10
        dispositions2 = normalize_pending_bazpors_night_actions(game2, self.manager)
        self.assertIn("yaku", dispositions2)
        self.assertTrue(state.no_host_done)
        self.assertIsNone(state.no_host_phase)
        self.assertIsNone(state.no_host_pending_sac_uid)

    async def test_17_citizen_ruintan_ack_defaults(self):
        from bot.bazpors_force_finish_night import force_finish_bazpors_night
        from bot import no_host_night_ready as readiness

        game = self._room()
        citizen_uid = self._role_uid(game, Role.CITIZEN)
        self.assertNotIn(
            citizen_uid, game.no_host_citizen_night_confirmed_uids
        )
        self.assertFalse(game.no_host_ruintan_night_confirmed)
        with patch.object(
            readiness,
            "finish_no_host_parallel_night_collect",
            new=AsyncMock(return_value=True),
        ):
            await force_finish_bazpors_night(self.bot, game, self.manager)
        self.assertIn(citizen_uid, game.no_host_citizen_night_confirmed_uids)
        self.assertTrue(game.no_host_ruintan_night_confirmed)
        dispositions = _audit_force_finish_dispositions(game)
        self.assertIn("citizen", dispositions)
        self.assertIn("ruintan", dispositions)

    async def test_18_night_acts_closed_list_and_stale_pmr_rejected(self):
        from bot.bazpors_force_finish_night import (
            BAZPORS_NIGHT_CLOSED_ACTS,
            BAZPORS_NIGHT_PHASE_ENDED_TEXT,
            bazpors_night_act_is_closed_for_game,
        )

        game = self._room()
        self.assertFalse(bazpors_night_act_is_closed_for_game(game, "cic"))
        self.assertFalse(bazpors_night_act_is_closed_for_game(game, "hnp"))
        # Room 91 hotfix: the latch is night-scoped — a REAL force-finish now
        # records the latched night; latching the CURRENT night keeps the
        # closed-acts contract below intact (legacy latches without a night
        # identifier open again once parallel collection is active).
        game.bazpors_night_force_finished = True
        game.bazpors_night_force_finished_night = game.bazpors_narrator_night_count
        for act in (
            "nms", "nmg", "nmc", "nmb", "nmy", "nmn",
            "msk", "msb", "msc",
            "dkt", "dkn", "dkc", "dkb", "dko", "dkng",
            "ndp", "ndc", "ndb",
            "skt", "skn", "skc", "skb",
            "cic", "ruc",
            "hnp", "hns", "hnc", "hnb",
            "sgt", "sgc", "sgb",
            "nii1", "nii1s", "nii2", "nii2a", "nii2r", "niisk",
            "n1c", "n1b", "n2p", "n2c", "n2b",
            "ysp", "ysb", "ysc", "ycp", "ycb", "ycc",
        ):
            self.assertIn(act, BAZPORS_NIGHT_CLOSED_ACTS, msg=act)
            self.assertTrue(
                bazpors_night_act_is_closed_for_game(game, act), msg=act
            )
        self.assertTrue(
            bazpors_night_act_is_closed_for_game(game, f"n1r-{Role.DETECTIVE.value}")
        )
        # day-phase acts stay open
        self.assertFalse(bazpors_night_act_is_closed_for_game(game, "d1dn"))
        self.assertFalse(bazpors_night_act_is_closed_for_game(game, "d1dt"))

        # stale pmr press after force-finish → rejected, not consumed
        citizen_uid = self._role_uid(game, Role.CITIZEN)
        self.bot.calls.clear()
        await self._press_pmr("cic", citizen_uid)
        self.assertIn(BAZPORS_NIGHT_PHASE_ENDED_TEXT, self.bot.acks())
        self.assertNotIn(
            citizen_uid, game.no_host_citizen_night_confirmed_uids
        )


class HunterPanelTests(_BazporsNightHelperBase):
    """آیتم ۵ و ۱۴: پنل هانتر — آمادگی، ثبت یک‌باره، پاکسازی ناظر."""

    async def test_19_night_signature_prevents_redispatch(self):
        from bot.no_host_night1 import start_no_host_night1_hunter_flow

        game = self._room()
        self._role_uid(game, Role.HUNTER)
        self.assertIsNone(game.no_host_hunter1_dm_signature)
        await start_no_host_night1_hunter_flow(self.bot, game, self.manager)
        self.assertEqual(
            game.no_host_hunter1_dm_signature,
            f"{game.bazpors_narrator_night_count}:hunter:n1",
        )
        first = len(self.bot.calls)
        await start_no_host_night1_hunter_flow(self.bot, game, self.manager)
        self.assertEqual(len(self.bot.calls), first)

    async def test_20_reconcile_does_not_restore_after_signature_no_helper_panel(self):
        from bot.no_host_night_reconcile import reconcile_no_host_night_readiness

        game = self._room()
        # hunter still pending but its panel was delivered this night
        game.no_host_hunter1_dm_signature = (
            f"{game.bazpors_narrator_night_count}:hunter:n1"
        )
        self.bot.calls.clear()
        result = await reconcile_no_host_night_readiness(
            self.bot, game, self.manager, reason="test"
        )
        self.assertFalse(result)
        hunter_events = [
            e
            for e in self._audit_events()
            if e.get("event") == "no_host.night_ready_auto_resolve"
            and str(e.get("role", "")).lower() == "hunter"
        ]
        self.assertEqual(hunter_events, [])
        # suppression also covers the reconcile refresh path
        for _chat, body in self.bot.sends():
            self.assertNotIn(NIGHT_START_TITLE_MARK, body)

    async def test_21_finalize_closes_mirror_pair_for_synthetic_hunter(self):
        from bot.no_host_night1 import _finalize_hunter_night1, _hunter_night1_ui_key
        from bot.no_host_night_common import finalize_no_host_role_pick_message

        game = self._room()
        hunter_uid = self._role_uid(game, Role.HUNTER)
        ui_key = _hunter_night1_ui_key(game, hunter_uid)
        game.mirror_prompt_messages[ui_key] = {
            "player": (hunter_uid, 101),
            "observer": (86299999, 202),
        }
        # hunter is synthetic (dev-fill uid) — the old gate would skip this
        with patch(
            "bot.no_host_night_common.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ) as fin:
            await _finalize_hunter_night1(self.bot, game, self.manager, None)
            self.assertTrue(game.no_host_night1_hunter_done)
            fin.assert_awaited_once()
        # a second finalize is a no-op
        with patch(
            "bot.no_host_night_common.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ) as fin2:
            await _finalize_hunter_night1(self.bot, game, self.manager, None)
            fin2.assert_not_awaited()


class PlayerCountMatrixTests(_BazporsNightHelperBase):
    """آیتم ۱۹: همهٔ ترکیب‌های بازپرس (۱۰، ۱۱، ۱۲، ۱۳، ۱۵)."""

    async def test_all_supported_counts(self):
        from bot.bazpors_force_finish_night import (
            bazpors_force_finish_button_keyboard,
            bazpors_night_force_finish_collection_active,
        )
        from bot.night_helper_reminder import (
            _mode,
            night_reminder_outstanding_count,
            night_reminder_uses_force_finish,
        )

        for count in (10, 11, 12, 13):
            with self.subTest(count=count):
                game = self._room(count=count)
                self.assertEqual(_mode(game), "no_host_collect")
                self.assertTrue(night_reminder_uses_force_finish(game))
                self.assertGreaterEqual(
                    night_reminder_outstanding_count(game), 1
                )
                self.assertTrue(
                    bazpors_night_force_finish_collection_active(game)
                )
                kb = bazpors_force_finish_button_keyboard(game)
                labels = [b.text for row in kb.inline_keyboard for b in row]
                self.assertEqual(labels, ["🌙 اتمام شب"])


class OtherScenariosUntouchedTests(_BazporsNightHelperBase):
    """آیتم ۲۰: مذاکره/ماسون/روسی — رفتار قبلی دست‌نخورده."""

    async def test_mozakere_counted_text_still_plain_count_line(self):
        from bot.night_helper_reminder import (
            build_counted_night_reminder_text,
            counted_night_reminder_header_and_parse_mode,
        )

        gam = self.manager
        game = gam.create_game(
            host_id=1, scenario_name="mozakere", max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_step = "night_actions"
        game.bazpors_narrator_night_count = 1
        game.no_host_night_parallel_collect_active = True
        game.no_host_night_entry_dispatched_night = 1
        text = build_counted_night_reminder_text(game, 4)
        self.assertIn("به دلیل اینکه هنوز ۴ اقدام شبانه تکمیل نشده است", text)
        self.assertNotIn("<b>۴", text)
        self.assertEqual(
            counted_night_reminder_header_and_parse_mode(game),
            ("🌙 <b>قابلیت اتمام شب</b>", "HTML"),
        )

    async def test_bazpors_finish_flag_isolated_from_other_scenarios(self):
        game = self._room()
        game.bazpors_night_force_finished = True
        game.bazpors_night_force_finished_night = (
            game.bazpors_narrator_night_count
        )
        gam = self.manager
        moz = gam.create_game(
            host_id=1, scenario_name="mozakere", max_players=12,
            bazpors_host_mode="no_host",
        )
        assert moz is not None
        self.assertFalse(moz.bazpors_night_force_finished)
        from bot.bazpors_force_finish_night import (
            bazpors_night_act_is_closed_for_game,
        )

        self.assertFalse(bazpors_night_act_is_closed_for_game(moz, "msk"))


if __name__ == "__main__":
    unittest.main()
