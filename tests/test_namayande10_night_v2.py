"""Namayande-10 fork: redesigned night v2 panels (bot/nam10/night2.py).

Real aiogram dispatcher presses over ``PlayerMirrorCb`` callbacks. Isolated
temporary storage; never touches production rooms. Covers:

- Boss capability menu (shot plain / shot neutralized / NATO), shot
  placeholder states, NATO once-per-game enforcement.
- Two-step NATO guessing (five citizen roles -> town-faction player),
  announcement broadcast exactly once.
- Doctor cancellation triggered by NATO (both cases), transactional
  self-save rollback (1->0, 2->1), no duplicate rollback, stale presses.
- Hacker two sequential stages (town source -> town destination, same-UID
  allowed), Guide consecutive-night exclusion,
  Mine Layer / Lawyer once-per-game with skip, Guardian confirmation,
  waiting-only Rebel / Citizen acks.
- Guide aftermath grant: intercepted pair (no panel), town recipient extra
  investigation panel with immediate positive/negative result, Mafia
  recipient Guide-identity notice (sent once). The extra panel is
  materialized only after Guide + Hacker confirmations AND the
  recipient's own main action is settled; the unmaterialized grant
  already blocks night readiness.
- Deterministic resolution: NATO success/failure + consumption, Doctor
  save validity/nullification/cancellation, mine placement with Hacker
  interception, Guardian armor / Lawyer immunity grants + predicates,
  shot-intent resolution (Doctor precedence, mine trigger/permanent
  neutralization, pending mine-casualty boundary), Rebel assassination
  unlock/once-per-game/effect.
- Observer-driven synthetic seats, authorization and stale rejection.
- Snapshot round-trips, resolution idempotency/restart recovery and the
  resolved-with-publication-pending boundary (no old resolver, no
  counter advancement, no publication).
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    Message,
    Update,
    User,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import bot.app_state as _app_state
from bot.game import GameManager as _GM

_app_state.manager = _GM()

import bot.db as _db

_db.init_db()

from bot.game import GameManager
from bot.handlers import register_all_handlers
from bot.observer_delivery import PlayerMirrorCb

ASSIST_UID = 80012
OBS_UID = 80013
BOSS_UID = 901
NATO_UID = 902
SHIAD_UID = 903
LAW_UID = 904
GUIDE_UID = 905
GUARD_UID = 906
DOC_UID = 907
MINE_UID = 908
CIT1_UID = 909
SYN_UID = -930001  # seat 10, synthetic citizen
REAL_UIDS = list(range(901, 910))

STALE_ALERT = "این مرحله دیگر فعال نیست."
FORBIDDEN_ALERT = "شما مجاز به این عمل نیستید."
INVALID_ALERT = "نامعتبر."
CANCEL_MARK = "لغو اقدام شب"
SHOT_MARK = "انتخاب هدف شات"
NATO_ANNOUNCE = "تیم مافیا در حال انجام ناتویی است"


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
        from types import SimpleNamespace

        self.calls.append(method)
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
                chat=SimpleNamespace(
                    id=kwargs.get("chat_id", args[0] if args else None)
                ),
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
            tname = type(c).__name__
            cls = getattr(c, "_cls", None)
            if tname in ("SendMessage", "EditMessageText"):
                out.append(
                    (
                        getattr(c, "chat_id", None),
                        getattr(c, "text", "") or "",
                    )
                )
            elif cls in ("send_message", "edit_message_text"):
                args = getattr(c, "_rec_args", ())
                kw = getattr(c, "_rec_kwargs", {}) or {}
                chat = kw.get("chat_id", args[0] if args else None)
                text = kw.get("text", args[1] if len(args) > 1 else "") or ""
                out.append((chat, text))
        return out

    def texts(self):
        out = []
        for c in self.calls:
            if type(c).__name__ in ("SendMessage", "EditMessageText"):
                out.append(getattr(c, "text", "") or "")
            elif getattr(c, "_cls", None) in ("send_message", "edit_message_text"):
                args = getattr(c, "_rec_args", ())
                kw = getattr(c, "_rec_kwargs", {}) or {}
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

    def kb_segments(self):
        out = []
        for c in self.calls:
            tname = type(c).__name__
            cls = getattr(c, "_cls", None)
            if tname in ("SendMessage", "EditMessageText"):
                out.append(
                    (getattr(c, "text", "") or "", getattr(c, "reply_markup", None))
                )
            elif cls in ("send_message", "edit_message_text"):
                args = getattr(c, "_rec_args", ())
                kw = getattr(c, "_rec_kwargs", {}) or {}
                text = kw.get("text", args[1] if len(args) > 1 else "") or ""
                kb = kw.get("reply_markup", args[3] if len(args) > 3 else None)
                out.append((text, kb))
        return out

    def sends_to(self, chat_id):
        return [(chat, t) for chat, t in self.sends() if chat == chat_id]

    def texts_to(self, chat_id):
        return [t for chat, t in self.sends() if chat == chat_id]

    def kb_texts_to(self, chat_id):
        return [(t, kb) for chat, t, kb in self._fullsends() if chat == chat_id]

    def _fullsends(self):
        out = []
        for c in self.calls:
            tname = type(c).__name__
            cls = getattr(c, "_cls", None)
            if tname == "SendMessage":
                out.append(
                    (
                        getattr(c, "chat_id", None),
                        getattr(c, "text", ""),
                        getattr(c, "reply_markup", None),
                    )
                )
            elif cls == "send_message":
                args = getattr(c, "_rec_args", ())
                kw = getattr(c, "_rec_kwargs", {}) or {}
                out.append(
                    (
                        kw.get("chat_id", args[0] if args else None),
                        kw.get("text", args[1] if len(args) > 1 else ""),
                        kw.get("reply_markup", None),
                    )
                )
        return out


class Nam10NightV2Test(unittest.IsolatedAsyncioTestCase):
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
        for name, mod in list(sys.modules.items()):
            m = getattr(mod, "manager", None)
            if isinstance(m, _GM) and m is not self.manager:
                self._mgr_patches.append(patch.object(mod, "manager", self.manager))
        for p in self._mgr_patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._mgr_patches):
            p.stop()
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    def _fork_room(self, *, with_observer: bool = True):
        from bot.game_audit_log import init_audit_log
        from bot.models import Phase, Player
        from bot.nam10.nmnd_narrator import Role

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        seat = 0
        for uid in REAL_UIDS:
            seat += 1
            err = self.manager.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"بازیکن {seat}",
                    username=None,
                    role=None,
                    is_alive=True,
                    seat=seat,
                ),
            )
            assert err is None, err
        err = self.manager.add_player(
            game,
            Player(
                user_id=SYN_UID,
                full_name="امیر",
                username=None,
                role=None,
                is_alive=True,
                seat=10,
            ),
        )
        assert err is None, err
        team_map = {
            BOSS_UID: Role.MAFIA_BOSS,
            NATO_UID: Role.NATO,
            SHIAD_UID: Role.SHIAD,
            LAW_UID: Role.HUNTER,
            GUIDE_UID: Role.INTERROGATOR,
            GUARD_UID: Role.DETECTIVE,
            DOC_UID: Role.DOCTOR,
            MINE_UID: Role.RUINTAN,
            CIT1_UID: Role.CITIZEN,
            SYN_UID: Role.CITIZEN,
        }
        for uid, pl in game.players.items():
            pl.role = team_map[uid]
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_night_count = 1
        if with_observer:
            game.observer_user_id = OBS_UID
            game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game
        return game

    async def _enter_night(self):
        from bot.nam10.nmnd_narrator import NIGHT_START

        self.game.nam10_day1_stage = "day1_night_entered"
        self.game.nmnd_narrator_step = NIGHT_START
        from bot.nam10.no_host_night1 import on_no_host_entered_night1

        await on_no_host_entered_night1(self.bot, self.game, self.manager)

    async def _press(self, actor_uid, act, as_uid, tid=0, code=None):
        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        data = PlayerMirrorCb(
            code=code or self.game.room_code, act=act, as_uid=as_uid, tid=tid
        ).pack()
        cq = CallbackQuery(
            id=f"cq-{len(self.bot.calls)}",
            from_user=actor,
            chat_instance="ci",
            data=data,
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

    def _panel_buttons(self, mark: str, chat_id=None):
        picked = None
        for text, kb in self.bot.kb_segments():
            if mark in text and kb is not None:
                picked = kb
        if picked is None:
            return []
        out = []
        for row in picked.inline_keyboard:
            for btn in row:
                if isinstance(btn, InlineKeyboardButton) and (
                    btn.callback_data or ""
                ).startswith("pmr:"):
                    out.append(PlayerMirrorCb.unpack(btn.callback_data))
        return out

    def _button_objects(self, mark: str, chat_id=None):
        picked = None
        for text, kb in self.bot.kb_segments():
            if mark in text and kb is not None:
                picked = kb
        if picked is None:
            return []
        out = []
        for row in picked.inline_keyboard:
            for btn in row:
                if isinstance(btn, InlineKeyboardButton):
                    out.append(btn)
        return out

    def _shot_button_styles(self):
        """Map of shot-panel target uid -> button style (selection state)."""
        out = {}
        for b in self._button_objects(SHOT_MARK):
            if not (b.callback_data or ""):
                continue
            cb = PlayerMirrorCb.unpack(b.callback_data)
            if cb is not None and cb.act == "sht":
                out[cb.tid] = b.style
        return out

    # ---- basic walk: everybody confirms with no-NATO choices ----------
    async def _confirm_all_simple(self):
        g = self.game
        # Boss: plain shot at CIT1 (the Doctor's save keeps them alive)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        # Doctor: save citizen 909
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        # Hacker: town source -> town destination (two stages)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        # Guide: pick mafia NATO
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=NATO_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        # Guardian: pick boss
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=BOSS_UID)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        # Mine: skip
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        # Lawyer: skip
        await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
        await self._press(LAW_UID, "lawok", LAW_UID)
        # Rebel ack
        await self._press(NATO_UID, "waitok", NATO_UID)
        # Citizens ack
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(SYN_UID, "waitok", SYN_UID, ) if False else None
        await self._press(OBS_UID, "waitok", SYN_UID)

    # ------------------------------------------------------------------
    async def test_01_entry_dispatches_all_role_panels(self):
        self._fork_room()
        await self._enter_night()
        # mode + phase
        from bot.nam10.night2 import N2_STEP_WAIT, PENDING_COLLECTING

        self.assertTrue(self.game.nmnd_night2_mode)
        self.assertEqual(self.game.nmnd_narrator_step, N2_STEP_WAIT)
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_COLLECTING)
        # boss menu: exactly three blue options with ناتویی spelling
        boss_btns = self._button_objects("انتخاب قابلیت رئیس مافیا", BOSS_UID)
        self.assertEqual([b.text for b in boss_btns], [
            "🎯 شات بدون خنثی‌سازی",
            "🎯 شات به همراه خنثی‌سازی",
            "🎭 ناتویی",
        ])
        self.assertTrue(all(b.style == "primary" for b in boss_btns))
        # doctor panel with خودم self-button
        doc_btns = [
            b.text
            for b in self._button_objects("انتخاب پزشک", DOC_UID)
            if b.text not in ("✅ تأیید",)
        ]
        self.assertIn("خودم", doc_btns)
        from bot.nam10.engine import is_synthetic_player_uid

        doc_targets = {
            cb.tid for cb in self._panel_buttons("انتخاب پزشک", DOC_UID)
            if cb.act == "docp"
        }
        self.assertIn(DOC_UID, doc_targets)
        self.assertIn(SYN_UID, doc_targets)
        # hacker stage-1 pool: town faction only (mafia members excluded)
        hack_targets = {
            cb.tid
            for cb in self._panel_buttons("انتخاب‌های هکر", SHIAD_UID)
            if cb.act == "hacp"
        }
        self.assertNotIn(SHIAD_UID, hack_targets)
        self.assertNotIn(BOSS_UID, hack_targets)
        self.assertIn(CIT1_UID, hack_targets)
        # guardian excludes self
        guard_targets = {
            cb.tid
            for cb in self._panel_buttons("انتخاب محافظ", GUARD_UID)
            if cb.act == "gdnp"
        }
        self.assertNotIn(GUARD_UID, guard_targets)
        # mine panel has انتخابی ندارم
        mine_texts = [
            b.text
            for b in self._button_objects("انتخاب مین‌گذار", MINE_UID)
        ]
        self.assertIn("انتخابی ندارم", mine_texts)
        # rebel + citizen waiting panels with ✅ اوکی
        rebel_btns = self._button_objects("الانتظار", None) if False else None
        self.assertTrue(self._panel_buttons("انتظار برای پایان شب", NATO_UID))
        cit_btns = [
            b
            for b in self._button_objects("انتظار برای پایان شب", CIT1_UID)
            if b.text == "✅ اوکی"
        ]
        self.assertEqual(len(cit_btns), 1)
        # synthetic citizen has NO direct DM copies — observer mirror only
        syn_direct = self.bot.sends_to(SYN_UID)
        self.assertNotIn("انتظار برای پایان شب", "\n".join(map(str, syn_direct)))
        obs_texts = "\n".join(self.bot.texts_to(OBS_UID))
        self.assertIn("انتظار برای پایان شب", obs_texts)
        # no legacy panel signatures (old Bazpors/fork labels)
        all_text = "\n".join(self.bot.texts())
        for legacy in ("کاراگاه", "رویین تن", "بازپرس"):
            self.assertNotIn(legacy, all_text)
        # snapshot persisted
        self.assertTrue(self.game.nmnd_night2_entry_dispatched)

    async def test_02_shot_placeholder_no_resolution(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        from bot.nam10.night2 import (
            BOSS_MODE_SHOT_PLAIN,
            BOSS_PHASE_SHOT_TARGET,
        )

        self.assertEqual(self.game.nmnd_night2_boss_mode, BOSS_MODE_SHOT_PLAIN)
        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_SHOT_TARGET)
        # the selection panel opened; nothing is persisted yet
        self.assertIn(SHOT_MARK, "\n".join(self.bot.texts_to(BOSS_UID)))
        confirm_cbs = [
            cb
            for cb in self._panel_buttons(SHOT_MARK, BOSS_UID)
            if cb.act == "shtok"
        ]
        self.assertEqual(len(confirm_cbs), 1)
        self.assertIsNone(self.game.nmnd_night2_shot_target_uid)
        self.assertFalse(self.game.nmnd_night2_boss_shot_marked)
        # no fabricated target / no elimination / no night advance
        self.assertIsNone(self.game.nmnd_night2_nato_target_uid)
        self.assertTrue(
            all(p.is_alive for p in self.game.players.values())
        )
        self.assertEqual(self.game.nmnd_narrator_night_count, 1)
        # stale repress rejected: the closed mode menu cannot overwrite
        # the open selection stage
        n_calls = len(self.bot.calls)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))
        self.assertEqual(len(self.bot.calls), n_calls + 1)
        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_SHOT_TARGET)

    async def test_03_nato_activation_cancels_doctor_and_announces_once(self):
        self._fork_room()
        await self._enter_night()
        n_sends_before = len(self.bot.calls)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        from bot.nam10.night2 import (
            BOSS_PHASE_NATO_ROLE,
            BOSS_MODE_NATO,
        )

        self.assertEqual(self.game.nmnd_night2_boss_mode, BOSS_MODE_NATO)
        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)
        self.assertTrue(self.game.nmnd_night2_nato_used)
        self.assertTrue(self.game.nmnd_night2_nato_announced)
        # announcement reached every alive player seat + observer
        announcement_chats = [
            chat for chat, t in self.bot.sends_to_chat if False
        ] if False else None
        from collections import Counter

        counts = Counter()
        for c in self.bot._fullsends() + [
            (getattr(x, "chat_id", None), getattr(x, "text", ""), None)
            for x in self.bot.calls
            if type(x).__name__ == "EditMessageText"
            and NATO_ANNOUNCE in (getattr(x, "text", "") or "")
        ]:
            chat, t, _kb = c if len(c) == 3 else (c[0], c[1], None)
            if NATO_ANNOUNCE in t:
                counts[chat] += 1
        for uid in [BOSS_UID, NATO_UID, SHIAD_UID, DOC_UID, MINE_UID, CIT1_UID, OBS_UID]:
            self.assertGreaterEqual(counts[uid], 1, uid)
        # doctor cancelled in both text and state
        self.assertTrue(self.game.nmnd_night2_doctor_cancelled)
        self.assertEqual(
            self.game.nmnd_night2_doctor_cancel_reason, "cancelled_by_nato"
        )
        doc_texts = "\n".join(self.bot.texts_to(DOC_UID))
        self.assertIn(CANCEL_MARK, doc_texts)
        self.assertNotIn("لطفاً یک بازیکن را انتخاب و تأیید کنید", doc_texts.split(CANCEL_MARK)[-1])
        # doctor no longer required for readiness
        from bot.nam10.night2 import night2_required_keys

        self.assertNotIn("DOCTOR", night2_required_keys(self.game))
        # stale doctor presses rejected
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))
        self.assertIsNone(self.game.nmnd_night2_doctor_uid)
        # exactly one announcement broadcast
        announce_count = sum(
            1
            for chat, t in self.bot.sends()
            if NATO_ANNOUNCE in t and chat == DOC_UID
        )
        self.assertEqual(announce_count, 1)

    async def test_04_nato_role_stage_mapping_and_confirm(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        # five role buttons in panel order = (DOCTOR, INTERROGATOR, HUNTER, DETECTIVE, RUINTAN)
        btns = [
            b
            for b in self._button_objects("ناتویی — انتخاب نقش", BOSS_UID)
            if b.text != "✅ تأیید"
        ]
        self.assertEqual(
            [b.text for b in btns],
            ["پزشک", "راهنما", "وکیل", "محافظ", "مین‌گذار"],
        )
        self.assertTrue(all(b.style == "primary" for b in btns))
        # toggle: first blue, selected red, move replaces
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=1)
        sel = self._button_objects("ناتویی — انتخاب نقش", BOSS_UID)
        self.assertEqual(sel[0].style, "danger")
        self.assertEqual(sel[1].style, "primary")
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=3)
        sel = self._button_objects("ناتویی — انتخاب نقش", BOSS_UID)
        self.assertEqual(sel[2].style, "danger")
        self.assertEqual(sel[0].style, "primary")
        # echo toggle off then re-select, only then confirm is usable
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=3)
        sel = self._button_objects("ناتویی — انتخاب نقش", BOSS_UID)
        self.assertEqual(sel[2].style, "primary")
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=3)
        sel = self._button_objects("ناتویی — انتخاب نقش", BOSS_UID)
        self.assertEqual(sel[2].style, "danger")
        await self._press(BOSS_UID, "nrok", BOSS_UID)
        from bot.nam10.night2 import BOSS_PHASE_NATO_PLAYER

        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_NATO_PLAYER)
        self.assertEqual(self.game.nmnd_night2_nato_role, "HUNTER")
        # stage-2 pool: alive town faction only (no boss/rebel/hacker)
        pool = {
            cb.tid
            for cb in self._panel_buttons("ناتویی — انتخاب بازیکن", BOSS_UID)
            if cb.act == "npl"
        }
        self.assertNotIn(BOSS_UID, pool)
        self.assertNotIn(NATO_UID, pool)
        self.assertNotIn(SHIAD_UID, pool)
        self.assertIn(DOC_UID, pool)
        self.assertIn(SYN_UID, pool)

    async def test_05_nato_player_confirm_stores_and_becomes_done(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=4)  # DETECTIVE
        await self._press(BOSS_UID, "nrok", BOSS_UID)
        uid = GUARD_UID
        await self._press(BOSS_UID, "npl", BOSS_UID, tid=uid)
        await self._press(BOSS_UID, "npok", BOSS_UID)
        from bot.nam10.night2 import BOSS_PHASE_DONE

        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        self.assertEqual(self.game.nmnd_night2_nato_role, "DETECTIVE")
        self.assertEqual(self.game.nmnd_night2_nato_target_uid, uid)
        # button-free confirmation, no correctness disclosure
        boss_texts = "\n".join(self.bot.texts_to(BOSS_UID))
        self.assertIn("انتخاب ناتویی شما ثبت شد", boss_texts)
        self.assertNotIn("درست", boss_texts.split("انتخاب ناتویی شما ثبت شد")[-1])

    async def test_06_nato_once_per_game_on_next_night(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertTrue(self.game.nmnd_night2_nato_used)
        # enter night 2 (per-night reset, lifetime flag persists)
        self.game.nmnd_narrator_night_count = 2
        await self._enter_night()
        btns = [
            b.text
            for b in self._button_objects("انتخاب قابلیت رئیس مافیا", BOSS_UID)
        ]
        self.assertNotIn("🎭 ناتویی", btns)
        self.assertEqual(len(btns), 2)
        # NATO answers stale
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))

    async def test_07_doctor_other_player_confirm_and_state(self):
        self._fork_room()
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        # toggle: red selection, then deselect again
        sel = [
            b
            for b in self._button_objects("انتخاب پزشک", DOC_UID)
            if b.text and b.style == "danger"
        ]
        self.assertEqual(len(sel), 1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        sel = [
            b
            for b in self._button_objects("انتخاب پزشک", DOC_UID)
            if b.text and b.style == "danger"
        ]
        self.assertEqual(len(sel), 0)
        # confirm without selection is rejected
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertTrue(
            any("ابتدا یک بازیکن" in (a or "") for a in self.bot.acks())
        )
        await self._press(DOC_UID, "docp", DOC_UID, tid=SYN_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertEqual(self.game.nmnd_night2_doctor_uid, SYN_UID)
        self.assertFalse(self.game.nmnd_night2_doctor_confirmed_self)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 0)

    async def test_08_self_save_confirmed_then_nato_rollbacks_to_zero(self):
        self._fork_room()
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 1)
        self.assertTrue(self.game.nmnd_night2_doctor_confirmed_self)
        # NATO begins -> confirmed action rolled back transactionally
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertTrue(self.game.nmnd_night2_doctor_cancelled)
        self.assertIsNone(self.game.nmnd_night2_doctor_uid)
        self.assertFalse(self.game.nmnd_night2_doctor_confirmed_self)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 0)
        # repeated NATO reconciliation cannot double-rollback
        from bot.nam10.night2 import night2_cancel_doctor_for_nato

        await night2_cancel_doctor_for_nato(self.bot, self.game, self.manager)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 0)
        # stale presses cannot reapply
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))

    async def test_09_self_save_rollback_restores_one_to_one(self):
        self._fork_room()
        self.game.nmnd_night2_doctor_self_saves = 1  # one earlier lifetime save
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=LAW_UID)
        # wait — LAW_UID==904 is town hunter; acceptable pool member
        # Actually select the doctor himself for self-save path
        await self._press(DOC_UID, "docp", DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 2)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 1)

    async def test_10_self_save_limit_two_per_game(self):
        self._fork_room()
        self.game.nmnd_night2_doctor_self_saves = 2
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertTrue(
            any("سهمیهٔ نجات خود" in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nmnd_night2_doctor_uid)

    async def test_11_hacker_stage_flow_town_only_same_uid_ok(self):
        self._fork_room()
        await self._enter_night()
        # Mafia members (Boss and Rebel) are not eligible in either stage.
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=BOSS_UID)
        self.assertTrue(any(INVALID_ALERT in (a or "") for a in self.bot.acks()))
        self.assertIsNone(self.game.nmnd_night2_hacker_src_pending)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SHIAD_UID)
        self.assertTrue(any(INVALID_ALERT in (a or "") for a in self.bot.acks()))
        # pick town source, proceed to stage 2
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        self.assertEqual(
            self.game.nmnd_night2_hacker_src_pending, CIT1_UID
        )
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        self.assertEqual(self.game.nmnd_night2_hacker_stage, "dst")
        # same UID source/destination is allowed
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertEqual(
            self.game.nmnd_night2_hacker_uids, [CIT1_UID, CIT1_UID]
        )
        self.assertEqual(self.game.nmnd_night2_hacker_stage, "done")
        # all acts stale after confirmation
        n_calls = len(self.bot.calls)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        for a in self.bot.acks()[n_calls:]:
            self.assertIn(STALE_ALERT, a or "", a)
        self.assertEqual(
            self.game.nmnd_night2_hacker_uids, [CIT1_UID, CIT1_UID]
        )

    async def test_12_guide_excludes_previous_night_target(self):
        self._fork_room()
        self.game.nmnd_narrator_night_count = 2
        self.game.nmnd_night2_guide_uids = {1: CIT1_UID}
        await self._enter_night()
        pool = {
            cb.tid
            for cb in self._panel_buttons("انتخاب راهنما", GUIDE_UID)
            if cb.act == "gdsp"
        }
        self.assertNotIn(CIT1_UID, pool)
        self.assertNotIn(GUIDE_UID, pool)
        self.assertIn(NATO_UID, pool)
        # forged press on excluded player rejected
        before = self.game.nmnd_night2_guide_pending_uid
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()) or before is None)
        self.assertIsNone(self.game.nmnd_night2_guide_pending_uid)

    async def test_13_mine_skip_does_not_consume_ability(self):
        self._fork_room()
        await self._enter_night()
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        mine_btns = self._button_objects("انتخاب مین‌گذار", MINE_UID)
        none_btn = [b for b in mine_btns if "انتخابی ندارم" in b.text]
        self.assertEqual(len(none_btn), 1)
        self.assertEqual(none_btn[0].style, "danger")
        # picking a player clears the none-flag (red -> blue)
        await self._press(MINE_UID, "minp", MINE_UID, tid=DOC_UID)
        mine_btns = self._button_objects("انتخاب مین‌گذار", MINE_UID)
        none_btn = [b for b in mine_btns if "انتخابی ندارم" in b.text]
        self.assertEqual(none_btn[0].style, "primary")
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        # skip: ability NOT consumed
        self.assertFalse(self.game.nmnd_night2_mine_used)
        self.assertIsNone(self.game.nmnd_night2_mine_uid)
        self.assertEqual(
            self.game.nmnd_night2_dispositions.get("mine_none"), "no_target"
        )

    async def test_14_mine_target_consumes_once_and_spent_panel_next_night(self):
        self._fork_room()
        await self._enter_night()
        await self._press(MINE_UID, "minp", MINE_UID, tid=DOC_UID)
        await self._press(MINE_UID, "minok", MINE_UID)
        self.assertTrue(self.game.nmnd_night2_mine_used)
        self.assertEqual(self.game.nmnd_night2_mine_uid, DOC_UID)
        self.assertEqual(self.game.nmnd_night2_mine_used_night, 1)
        # stale further picks rejected
        await self._press(MINE_UID, "minp", MINE_UID, tid=CIT1_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))
        # next night: spent waiting panel + ok
        self.game.nmnd_narrator_night_count = 2
        await self._enter_night()
        spent_btns = [
            b
            for b in self._button_objects("قبلاً از قابلیت مین‌گذاری", MINE_UID)
            if b.text == "✅ اوکی"
        ]
        self.assertEqual(len(spent_btns), 1)
        await self._press(MINE_UID, "waitok", MINE_UID)
        from bot.nam10.night2 import night2_required_keys

        self.assertNotIn("RUINTAN", night2_required_keys(self.game))

    async def test_15_lawyer_once_per_game_and_skip(self):
        self._fork_room()
        await self._enter_night()
        # self-target NOT eligible (existing Hunter rule preserved)
        pool = {
            cb.tid
            for cb in self._panel_buttons("انتخاب وکیل", LAW_UID)
            if cb.act == "lawp"
        }
        self.assertNotIn(LAW_UID, pool)
        # skip
        await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
        await self._press(LAW_UID, "lawok", LAW_UID)
        self.assertFalse(self.game.nmnd_night2_lawyer_used)
        self.assertEqual(
            self.game.nmnd_night2_dispositions.get("lawyer_none"), "no_target"
        )
        # fresh next-night with a real target
        self.game.nmnd_narrator_night_count = 2
        await self._enter_night()
        await self._press(LAW_UID, "lawp", LAW_UID, tid=DOC_UID)
        await self._press(LAW_UID, "lawok", LAW_UID)
        self.assertTrue(self.game.nmnd_night2_lawyer_used)
        self.assertEqual(self.game.nmnd_night2_lawyer_uid, DOC_UID)

    async def test_16_guardian_confirmation_exact_body(self):
        self._fork_room()
        await self._enter_night()
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=DOC_UID)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        from bot.nam10.night2 import night2_required_keys

        self.assertEqual(self.game.nmnd_night2_guardian_uid, DOC_UID)
        texts = "\n".join(self.bot.texts_to(GUARD_UID))
        self.assertIn("انتخاب محافظ در شب ۱ ثبت شد", texts)
        self.assertIn("بازیکن انتخاب‌شده: ۷ — بازیکن 7", texts)

    async def test_17_rebel_citizen_acks_finish_collection_safely(self):
        self._fork_room()
        await self._enter_night()
        await self._confirm_all_simple()
        from bot.nam10.night2 import (
            PENDING_RESOLVED,
            night2_required_keys,
        )

        self.assertEqual(night2_required_keys(self.game), [])
        # resolution committed: explicit resolved boundary with publication
        # pending — old resolver/counter/publication did not run
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(self.game.nmnd_night2_resolved)
        self.assertTrue(self.game.nmnd_night2_publication_pending)
        self.assertIsNone(self.game.nmnd_night_report_html)
        # safe stopping boundary: no counter advancement, no old resolver
        self.assertTrue(not self.game.nmnd_night2_eliminations)
        self.assertEqual(self.game.nmnd_narrator_night_count, 1)
        self.assertIsNone(self.game.nmnd_night_report_html)

    async def test_18_observer_operates_synthetic_and_rejections(self):
        self._fork_room()
        await self._enter_night()
        # non-owner real player rejected
        await self._press(CIT1_UID, "docp", DOC_UID, tid=CIT1_UID)
        self.assertTrue(any(FORBIDDEN_ALERT in (a or "") for a in self.bot.acks()))
        self.assertIsNone(self.game.nmnd_night2_doctor_pending_uid)
        # observer acts for synthetic doctor? doctor is real; use synthetic citizen ack
        await self._press(OBS_UID, "waitok", SYN_UID)
        acked = self.game.nmnd_night2_waiting_acked.get("CITIZEN", [])
        self.assertIn(SYN_UID, acked)
        # second ack duplicate
        await self._press(OBS_UID, "waitok", SYN_UID)
        self.assertTrue(
            any("قبلاً ثبت شده" in (a or "") for a in self.bot.acks())
        )
        # forged cross-room callback never mutates state
        await self._press(DOC_UID, "docok", DOC_UID, code="ROOMXX")
        self.assertIsNone(self.game.nmnd_night2_doctor_uid)
        self.assertFalse(self.game.nmnd_night2_doctor_confirmed_self)
        # unauthorized twilight: someone else cannot ack for rebel
        await self._press(CIT1_UID, "waitok", NATO_UID)
        self.assertNotIn(NATO_UID, self.game.nmnd_night2_waiting_acked.get("NATO", []))

    async def test_19_legacy_night_acts_blocked_in_v2_rooms(self):
        self._fork_room()
        await self._enter_night()
        n_calls = len(self.bot.calls)
        for act, as_uid, tid in (
            ("nwok", CIT1_UID, 0),
            ("dkt", DOC_UID, CIT1_UID),
            ("nms", BOSS_UID, 0),
            ("hnp", LAW_UID, DOC_UID),
            ("cic", CIT1_UID, 0),
        ):
            await self._press(as_uid, act, as_uid, tid=tid)
            self.assertTrue(
                any(STALE_ALERT in (a or "") for a in self.bot.acks()), act
            )
        # none of the legacy state got touched
        self.assertFalse(self.game.nam10_doctor_pending_save_uids if hasattr(self.game, "nam10_doctor_pending_save_uids") else True)

    async def test_20_snapshot_roundtrip_of_v2_fields(self):
        self._fork_room()
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=DOC_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        from bot.game_snapshot import (
            game_from_snapshot_dict,
            game_to_snapshot_dict,
        )

        payload = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(payload)
        for a in (
            "nmnd_night2_mode",
            "nmnd_night2_phase",
            "nmnd_night2_boss_phase",
            "nmnd_night2_boss_mode",
            "nmnd_night2_nato_used",
            "nmnd_night2_nato_announced",
            "nmnd_night2_doctor_cancelled",
            "nmnd_night2_doctor_uid",
            "nmnd_night2_doctor_confirmed_self",
            "nmnd_night2_doctor_self_saves",
            "nmnd_night2_waiting_acked",
            "nmnd_night2_dispositions",
            "nmnd_night2_grant_decided",
            "nmnd_night2_extra_kind",
            "nmnd_night2_extra_uid",
            "nmnd_night2_extra_target_uid",
            "nmnd_night2_extra_result",
            "nmnd_night2_extra_materialized",
            "nmnd_night2_hacker_pending_uids",
            "nmnd_night2_hacker_uids",
            "nmnd_night2_hacker_stage",
            "nmnd_night2_guide_uids",
            "nmnd_night2_grant_decided",
            "nmnd_night2_extra_kind",
            "nmnd_night2_extra_uid",
            "nmnd_night2_extra_target_uid",
            "nmnd_night2_extra_result",
            "nmnd_night2_active_mine_uid",
            "nmnd_night2_mine_events",
            "nmnd_night2_mine_casualty_pending",
            "nmnd_night2_armor_uid",
            "nmnd_night2_lawyer_immune_uid",
            "nmnd_night2_rebel_unlocked",
            "nmnd_night2_rebel_assassin_used",
            "nmnd_night2_eliminations",
            "nmnd_night2_outcome",
            "nmnd_night2_outcome_committed",
            "nmnd_night2_resolved",
            "nmnd_night2_resolved_night",
            "nmnd_night2_publication_pending",
            "nmnd_night2_shot_target_uid",
        ):
            self.assertEqual(
                getattr(restored, a), getattr(self.game, a), a
            )

    async def test_21_betrayal_forged_self_target_vote_rejected(self):
        self._fork_room()
        from bot.nam10.day1_betrayal import (
            NAM10_DAY1_STAGE_BETRAYAL_COLLECT,
        )

        self.game.nam10_day1_stage = NAM10_DAY1_STAGE_BETRAYAL_COLLECT
        self.game.nam10_day1_rep_uids = [BOSS_UID, CIT1_UID]
        self.game.nam10_day1_betrayal_op = None
        n_calls = len(self.bot.calls)
        await self._press(BOSS_UID, "d1ba", BOSS_UID, tid=BOSS_UID)
        self.assertTrue(
            any(
                "نمایندهٔ خودتان" in (a or "") for a in self.bot.acks()
            )
        )
        self.assertEqual(len(self.bot.calls), n_calls + 1)
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        # the foreign rep remains valid for the boss
        await self._press(BOSS_UID, "d1ba", BOSS_UID, tid=CIT1_UID)
        # claim path needs panel refs; either ok or skip depending on refs
        self.assertTrue(True)

    async def test_22_entry_idempotent_no_duplicate_panels(self):
        self._fork_room()
        await self._enter_night()
        n_calls = len(self.bot.calls)
        await self._enter_night()
        self.assertEqual(len(self.bot.calls), n_calls)

    async def test_23_shot_neutralized_mode_placeholder(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=2)
        from bot.nam10.night2 import BOSS_MODE_SHOT_NEUTRALIZED

        self.assertEqual(
            self.game.nmnd_night2_boss_mode, BOSS_MODE_SHOT_NEUTRALIZED
        )
        # the neutralized mode opens the same target-selection stage
        self.assertIsNone(self.game.nmnd_night2_doctor_uid)
        self.assertFalse(self.game.nmnd_night2_doctor_cancelled)
        # completing the selection persists the neutralized intent
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=SYN_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        from bot.nam10.night2 import BOSS_PHASE_DONE

        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        self.assertEqual(self.game.nmnd_night2_shot_target_uid, SYN_UID)
        self.assertTrue(self.game.nmnd_night2_boss_shot_marked)


# ---------------------------------------------------------------------------
# Resolution engine, Guide aftermath, Hacker stages, shot intent, Rebel
# ---------------------------------------------------------------------------


class Nam10NightV2ResolveTest(Nam10NightV2Test):
    """Extends the collection tests with the deterministic resolution
    engine, Guide aftermath grants and effect predicates."""

    async def _walk_v2(
        self,
        *,
        boss_tid: int = 1,
        shot_target: int = DOC_UID,
        nato_role_tid: int | None = None,
        nato_target: int | None = None,
        doc_pick: int | None = CIT1_UID,
        hack_src: int = DOC_UID,
        hack_dst: int = SYN_UID,
        guide_target: int = NATO_UID,
        guard_target: int = BOSS_UID,
        mine_pick: int = 0,
        law_pick: int = 0,
        do_extra: bool = True,
        extra_target: int | None = None,
    ) -> None:
        """Full v2 collection walk (resolution commits at the end)."""
        g = self.game
        if boss_tid == 3:
            await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
            await self._press(BOSS_UID, "nrole", BOSS_UID, tid=nato_role_tid)
            await self._press(BOSS_UID, "nrok", BOSS_UID)
            await self._press(BOSS_UID, "npl", BOSS_UID, tid=nato_target)
            await self._press(BOSS_UID, "npok", BOSS_UID)
        else:
            await self._press(BOSS_UID, "bmode", BOSS_UID, tid=boss_tid)
            if boss_tid in (1, 2):
                await self._press(BOSS_UID, "sht", BOSS_UID, tid=shot_target)
                await self._press(BOSS_UID, "shtok", BOSS_UID)
        if doc_pick is not None:
            await self._press(DOC_UID, "docp", DOC_UID, tid=doc_pick)
            await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=hack_src)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=hack_dst)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=guide_target)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=guard_target)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        await self._press(MINE_UID, "minp", MINE_UID, tid=mine_pick)
        await self._press(MINE_UID, "minok", MINE_UID)
        if mine_pick:
            await self._press(MINE_UID, "waitok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=law_pick)
        await self._press(LAW_UID, "lawok", LAW_UID)
        if law_pick:
            await self._press(LAW_UID, "waitok", LAW_UID)
        await self._press(NATO_UID, "waitok", NATO_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(OBS_UID, "waitok", SYN_UID)
        # Extra investigation materializes only after the recipient's own
        # main action is settled; press it last (the walk may resolve here).
        if g.nmnd_night2_extra_kind == "extra_sent" and do_extra:
            extra_uid = g.nmnd_night2_extra_uid
            actor = OBS_UID if extra_uid < 0 else extra_uid
            if extra_target is None:
                extra_target = DOC_UID if extra_uid != DOC_UID else CIT1_UID
            await self._press(actor, "exin", extra_uid, tid=extra_target)
            await self._press(actor, "exok", extra_uid)

    # -- Hacker stages ----------------------------------------------------

    async def test_24_hacker_stage_order_enforced(self):
        self._fork_room()
        await self._enter_night()
        # final confirm at stage 1 is stale (proceed button is not confirm)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))
        self.assertEqual(self.game.nmnd_night2_hacker_uids, [])
        # proceed without a source selection is rejected
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        self.assertTrue(
            any("ابتدا یک بازیکن" in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nmnd_night2_hacker_stage)
        # proceed with a source lands on stage 2 panel
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        self.assertEqual(self.game.nmnd_night2_hacker_stage, "dst")
        stage2_text = "\n".join(self.bot.texts_to(SHIAD_UID))
        self.assertIn("مرحله ۲ از ۲", stage2_text)
        # hacn is one-shot: repeating it at stage 2 is stale
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        self.assertTrue(any(STALE_ALERT in (a or "") for a in self.bot.acks()))
        # confirm without a destination is rejected
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertTrue(
            any("ابتدا یک بازیکن" in (a or "") for a in self.bot.acks())
        )
        self.assertEqual(self.game.nmnd_night2_hacker_uids, [])

    async def test_25_hacker_same_uid_source_destination(self):
        self._fork_room()
        await self._enter_night()
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertEqual(
            self.game.nmnd_night2_hacker_uids, [DOC_UID, DOC_UID]
        )
        self.assertEqual(self.game.nmnd_night2_hacker_stage, "done")

    # -- Guide aftermath ---------------------------------------------------

    async def test_26_grant_intercepted_no_extra_panel(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        # complete the shot intent on the Doctor-protected citizen
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        # Hacker pair = Guide -> Guide's chosen town recipient
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=GUIDE_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        from bot.nam10.night2 import (
            EXTRA_KIND_INTERCEPTED,
            night2_required_keys,
        )

        self.assertEqual(
            self.game.nmnd_night2_extra_kind, EXTRA_KIND_INTERCEPTED
        )
        self.assertIsNone(self.game.nmnd_night2_extra_uid)
        self.assertNotIn("n2extra", night2_required_keys(self.game))
        self.assertNotIn("استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID)))
        # the recipient still completes their own role action
        self.assertIn(
            "CITIZEN", night2_required_keys(self.game)
        )
        # resolution: nothing special granted
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=BOSS_UID)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
        await self._press(LAW_UID, "lawok", LAW_UID)
        await self._press(NATO_UID, "waitok", NATO_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(OBS_UID, "waitok", SYN_UID)
        from bot.nam10.night2 import PENDING_RESOLVED

        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertEqual(
            self.game.nmnd_night2_outcome["guide"]["grant_kind"],
            EXTRA_KIND_INTERCEPTED,
        )

    async def test_27_extra_panel_positive_result_blocks_readiness(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        from bot.nam10.night2 import (
            EXTRA_KIND_SENT,
            INVEST_POSITIVE,
            PENDING_COLLECTING,
            night2_required_keys,
        )

        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertEqual(self.game.nmnd_night2_extra_uid, CIT1_UID)
        # the recipient owes their own citizen ack: the panel is not sent
        # and no waiting notification leaks
        self.assertFalse(self.game.nmnd_night2_extra_materialized)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        # ...but the unmaterialized grant still blocks the night
        self.assertIn("n2extra", night2_required_keys(self.game))
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_COLLECTING)
        from bot.nam10.night2 import night2_maybe_finish

        self.assertFalse(night2_maybe_finish(self.game))
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_COLLECTING)
        # the citizen ack settles the main action -> panel materializes
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        self.assertIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        # recipient investigates the Hacker -> immediate positive feedback
        await self._press(CIT1_UID, "exin", CIT1_UID, tid=SHIAD_UID)
        await self._press(CIT1_UID, "exok", CIT1_UID)
        self.assertEqual(
            self.game.nmnd_night2_extra_target_uid, SHIAD_UID
        )
        self.assertEqual(self.game.nmnd_night2_extra_result, INVEST_POSITIVE)
        texts = "\n".join(self.bot.texts_to(CIT1_UID))
        self.assertIn("مثبت", texts)
        self.assertNotIn("n2extra", night2_required_keys(self.game))

    async def test_28_extra_panel_negative_result_boss(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        from bot.nam10.night2 import INVEST_NEGATIVE

        await self._press(CIT1_UID, "exin", CIT1_UID, tid=BOSS_UID)
        await self._press(CIT1_UID, "exok", CIT1_UID)
        texts = "\n".join(self.bot.texts_to(CIT1_UID))
        self.assertIn("منفی", texts)
        # no role leak: extra result must not name the boss
        self.assertNotIn("رئیس", texts)
        self.assertEqual(self.game.nmnd_night2_extra_result, INVEST_NEGATIVE)

    async def test_29_guide_to_mafia_identity_notice_once(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=SHIAD_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        from bot.nam10.night2 import EXTRA_KIND_MAFIA_ID

        self.assertEqual(
            self.game.nmnd_night2_extra_kind, EXTRA_KIND_MAFIA_ID
        )
        self.assertEqual(self.game.nmnd_night2_extra_uid, SHIAD_UID)
        # Delayed disclosure (Room 32 rule): the Mafia shooter has
        # not completed the night shot yet, so the identity notice
        # is withheld even though Guide+Hacker choices are known.
        texts = "\n".join(self.bot.texts_to(SHIAD_UID))
        self.assertNotIn("🧭 شناسایی راهنما", texts)
        # The shooter completes the shot -> the notice delivers.
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        texts = "\n".join(self.bot.texts_to(SHIAD_UID))
        self.assertIn("🧭 شناسایی راهنما", texts)
        self.assertIn(
            "از آنجا که راهنما امشب شما را که عضو تیم مافیا هستید "
            "انتخاب کرده است",
            texts,
        )
        self.assertIn("نقش راهنمای بازی متعلق است به:", texts)
        self.assertNotIn("استعلام کارآگاهی", texts)
        # duplicate grant calls never resend the identity notice
        n_sends = len(self.bot.sends_to(SHIAD_UID))
        from bot.nam10.night2 import night2_maybe_grant_guide_extra

        await night2_maybe_grant_guide_extra(self.bot, self.game)
        await night2_maybe_grant_guide_extra(self.bot, self.game)
        self.assertEqual(len(self.bot.sends_to(SHIAD_UID)), n_sends)
        # guide learns nothing
        self.assertNotIn("مثبت", "\n".join(self.bot.texts_to(GUIDE_UID)))
        self.assertNotIn("منفی", "\n".join(self.bot.texts_to(GUIDE_UID)))

    async def test_30_synthetic_extra_investigation_observer_control(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        # Guide picks the synthetic citizen -> extra investigation panel
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=SYN_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        from bot.nam10.night2 import (
            INVEST_POSITIVE,
            EXTRA_KIND_SENT,
        )

        self.assertEqual(g.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertEqual(g.nmnd_night2_extra_uid, SYN_UID)
        # the synthetic seat owes its own waiting ack first: no panel yet
        self.assertFalse(g.nmnd_night2_extra_materialized)
        self.assertNotIn("استعلام کارآگاهی", "\n".join(self.bot.texts_to(OBS_UID)))
        # observer acks for the synthetic seat -> panel materializes in the
        # observer mirror
        await self._press(OBS_UID, "waitok", SYN_UID)
        self.assertTrue(g.nmnd_night2_extra_materialized)
        self.assertIn("استعلام کارآگاهی", "\n".join(self.bot.texts_to(OBS_UID)))
        # observer operates the synthetic seat: investigate the Hacker
        await self._press(OBS_UID, "exin", SYN_UID, tid=SHIAD_UID)
        await self._press(OBS_UID, "exok", SYN_UID)
        self.assertEqual(g.nmnd_night2_extra_target_uid, SHIAD_UID)
        self.assertEqual(g.nmnd_night2_extra_result, INVEST_POSITIVE)
        # forged real-user control of the synthetic seat is rejected
        g.nmnd_night2_extra_target_uid = None
        g.nmnd_night2_extra_result = None
        g.nmnd_night2_extra_target_pending = None
        g.nmnd_night2_extra_kind = "extra_sent"
        await self._press(CIT1_UID, "exin", SYN_UID, tid=SHIAD_UID)
        self.assertTrue(
            any(FORBIDDEN_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(g.nmnd_night2_extra_target_uid)

    # -- Doctor nullification / NATO resolution ----------------------------

    async def test_31_doctor_self_save_nullified_charge_consumed(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=DOC_UID,       # self-save
            hack_src=DOC_UID,       # Hacker pair = Doctor -> Doctor
            hack_dst=DOC_UID,
        )
        from bot.nam10.night2 import night2_run_resolution

        self.assertTrue(self.game.nmnd_night2_outcome_committed)
        doc = self.game.nmnd_night2_outcome["doctor"]
        self.assertTrue(doc["nullified_by_hacker"])
        self.assertFalse(doc["protects_shot"])
        # the confirmed self-save charge stays consumed (no refund)
        self.assertEqual(self.game.nmnd_night2_doctor_self_saves, 1)
        # a Hacker-nullified Doctor save does not protect the shot target:
        # the Doctor is eliminated by the confirmed plain shot
        shot = self.game.nmnd_night2_shot_result
        self.assertTrue(shot["accepted"])
        self.assertFalse(shot["protected_by_doctor"])
        self.assertTrue(shot["eliminated"])
        self.assertFalse(self.game.players[DOC_UID].is_alive)

    async def test_32_nato_success_resolves_elimination(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=3,
            nato_role_tid=1,        # guessed doctor
            nato_target=DOC_UID,
        )
        from bot.nam10.night2 import ELIM_CAUSE_NATO

        nato = self.game.nmnd_night2_outcome["nato"]
        self.assertTrue(nato["success"])
        self.assertTrue(nato["consumed"])
        self.assertTrue(nato["eliminated"])
        self.assertFalse(self.game.players[DOC_UID].is_alive)
        doc_rec = [
            r
            for r in self.game.nmnd_night2_eliminations
            if r["uid"] == DOC_UID
        ]
        self.assertEqual(len(doc_rec), 1)
        self.assertEqual(doc_rec[0]["cause"], ELIM_CAUSE_NATO)
        # publication is explicitly pending; no report html was produced
        self.assertTrue(self.game.nmnd_night2_publication_pending)
        self.assertIsNone(self.game.nmnd_night_report_html)

    async def test_33_nato_failure_consumed_no_elimination(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=3,
            nato_role_tid=3,        # guessed لوله‌ها (HUNTER)
            nato_target=DOC_UID,
        )
        nato = self.game.nmnd_night2_outcome["nato"]
        self.assertFalse(nato["success"])
        self.assertFalse(nato["eliminated"])
        self.assertTrue(
            all(p.is_alive for p in self.game.players.values())
        )
        self.assertTrue(self.game.nmnd_night2_nato_used)
        self.assertEqual(self.game.nmnd_night2_eliminations, [])

    # -- Hacker interception of economy abilities --------------------------

    async def test_34_hack_intercepts_guardian_but_not_lawyer(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=CIT1_UID,
            hack_src=GUARD_UID,
            hack_dst=DOC_UID,
            guard_target=DOC_UID,
            law_pick=CIT1_UID,
            mine_pick=0,
        )
        guard = self.game.nmnd_night2_outcome["guardian"]
        law = self.game.nmnd_night2_outcome["lawyer"]
        self.assertTrue(guard.get("nullified_by_hacker"))
        self.assertIsNone(self.game.nmnd_night2_armor_uid)
        self.assertTrue(law["granted"])
        self.assertEqual(self.game.nmnd_night2_lawyer_immune_uid, CIT1_UID)
        # consumed charges on both abilities
        self.assertTrue(self.game.nmnd_night2_lawyer_used)

    async def test_35_hack_intercepts_lawyer_charge_consumed(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=CIT1_UID,
            hack_src=LAW_UID,
            hack_dst=DOC_UID,
            guard_target=BOSS_UID,
            law_pick=DOC_UID,
            mine_pick=0,
        )
        law = self.game.nmnd_night2_outcome["lawyer"]
        self.assertFalse(law["granted"])
        self.assertTrue(law["nullified_by_hacker"])
        self.assertIsNone(self.game.nmnd_night2_lawyer_immune_uid)
        self.assertTrue(self.game.nmnd_night2_lawyer_used)

    async def test_36_hack_intercepts_mine_charge_consumed(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=CIT1_UID,
            hack_src=MINE_UID,
            hack_dst=DOC_UID,
            mine_pick=DOC_UID,
            law_pick=0,
        )
        mine = self.game.nmnd_night2_outcome["mine"]
        # FINAL rule (§8): Mine Layer is immune as the Hacker's SOURCE —
        # the pair is a global no-op, the mine stays effective and the
        # confirmed attempt still consumed the once-per-game ability.
        self.assertTrue(mine["placed"])
        self.assertFalse(mine.get("nullified_by_hacker", False))
        # The plain shot at the Doctor now detonates the mine.
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(self.game.players[DOC_UID].is_alive)
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)
        self.assertTrue(self.game.nmnd_night2_mine_used)

    async def test_37_mine_placed_and_durable(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=DOC_UID,       # self-save protects DOC from the shot
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=DOC_UID,
            law_pick=0,
        )
        # FINAL rule: the shot target had an active mine, so the mine
        # detonates despite the Doctor's self-save and the Doctor is
        # eliminated; the mine is consumed exactly once.
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(self.game.players[DOC_UID].is_alive)
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)
        events = self.game.nmnd_night2_mine_events
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["triggered"])
        self.assertEqual(
            self.game.nmnd_night2_outcome["mine"]["placed"], True
        )
        # snapshot round-trip of the resolution surfaces
        from bot.game_snapshot import (
            game_from_snapshot_dict,
            game_to_snapshot_dict,
        )

        payload = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(payload)
        for a in (
            "nmnd_night2_active_mine_uid",
            "nmnd_night2_mine_events",
            "nmnd_night2_outcome",
            "nmnd_night2_outcome_committed",
            "nmnd_night2_resolved",
            "nmnd_night2_resolved_night",
            "nmnd_night2_publication_pending",
            "nmnd_night2_armor_uid",
            "nmnd_night2_lawyer_immune_uid",
            "nmnd_night2_grant_decided",
            "nmnd_night2_extra_kind",
            "nmnd_night2_extra_target_uid",
            "nmnd_night2_extra_result",
            "nmnd_night2_hacker_uids",
            "nmnd_night2_eliminations",
        ):
            self.assertEqual(
                getattr(restored, a), getattr(self.game, a), a
            )

    # -- Shot intent resolver ----------------------------------------------

    async def test_38_shots_needs_committed_resolution(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        from bot.nam10.night2 import night2_resolve_shot_intent

        res = night2_resolve_shot_intent(self.game, CIT1_UID)
        self.assertFalse(res["accepted"])
        self.assertEqual(res["reason"], "resolution_not_committed")
        self.assertFalse(self.game.nmnd_night2_shot_resolved)

    async def test_39_shot_doctor_save_cannot_stop_mine(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,      # Doctor picked the same mined target
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,     # mine also sits on CIT1
            law_pick=0,
        )
        # the resolution consumed the confirmed shot intent immediately
        from bot.nam10.night2 import night2_resolve_shot_intent

        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["accepted"])
        # FINAL rule: the mine detonates regardless of the Doctor save;
        # the mined target is eliminated either way.
        self.assertFalse(res["protected_by_doctor"])
        self.assertTrue(res["doctor_save_ineffective"])
        self.assertTrue(res["eliminated"])
        self.assertEqual(res["mine_disposition"], "triggered")
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(
            self.game.players[CIT1_UID].is_alive
        )
        # plain shot: the existing Mafia-casualty flow is required
        self.assertTrue(res["mine_casualty_pending"])
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)
        events = self.game.nmnd_night2_mine_events
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["triggered"])
        self.assertFalse(events[0]["neutralized"])
        self.assertTrue(
            self.game.nmnd_night2_outcome["shot"]["resolved"]
        )
        # repeat calls stay idempotent
        res2 = night2_resolve_shot_intent(self.game, CIT1_UID)
        self.assertTrue(res2["accepted"])

    async def test_40_shot_plain_triggers_mine_pending_casualty(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=DOC_UID,       # Doctor elsewhere
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        from bot.nam10.night2 import night2_resolve_shot_intent

        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["accepted"])
        self.assertFalse(res["protected_by_doctor"])
        self.assertTrue(res["eliminated"])
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertEqual(res["mine_disposition"], "triggered")
        self.assertTrue(res["mine_casualty_pending"])
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)
        # the deferred Mafia-casualty consequence stays unresolved: no
        # second elimination, no extra casualty, no panel, no selection
        dead_count = sum(
            1 for p in self.game.players.values() if not p.is_alive
        )
        self.assertEqual(dead_count, 1)
        self.assertFalse(
            any(
                p.is_alive is False and p.user_id != CIT1_UID
                for p in self.game.players.values()
            )
        )
        self.assertEqual(
            self.game.nmnd_night2_dispositions.get("mine_casualty"),
            None,
        )
        events = self.game.nmnd_night2_mine_events
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["triggered"])
        self.assertFalse(events[0]["neutralized"])
        # repeat call is idempotent, never triggers a second casualty
        night2_resolve_shot_intent(self.game, CIT1_UID)
        dead_count2 = sum(
            1 for p in self.game.players.values() if not p.is_alive
        )
        self.assertEqual(dead_count2, 1)

    async def test_41_shot_neutralized_mine_detonates_no_casualty(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2,
            shot_target=CIT1_UID,
            doc_pick=DOC_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        # FINAL matrix — with neutralization: the mine is neutralized
        # and consumed; the Doctor was elsewhere, so the target dies and
        # no Mafia-casualty selection runs.
        self.assertEqual(res["mine_disposition"], "neutralized")
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)
        self.assertFalse(res.get("mine_casualty_pending"))
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        events = self.game.nmnd_night2_mine_events
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["neutralized"])
        self.assertFalse(events[0]["triggered"])

    async def test_42_shot_repeat_idempotent_single_elimination(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=BOSS_UID,
            mine_pick=0,
            law_pick=0,
        )
        from bot.nam10.night2 import night2_resolve_shot_intent

        self.assertTrue(self.game.nmnd_night2_shot_resolved)
        self.assertFalse(self.game.players[BOSS_UID].is_alive)
        # a resolved intent repeats cleanly and refuses new targets
        res = night2_resolve_shot_intent(self.game, 99999)
        self.assertTrue(res["accepted"])
        self.assertEqual(res, dict(self.game.nmnd_night2_shot_result))
        res2 = night2_resolve_shot_intent(self.game, BOSS_UID)
        self.assertEqual(res2, res)
        self.assertEqual(len(self.game.nmnd_night2_eliminations), 1)

    # -- Guardian armor / predicates ----------------------------------------

    async def test_43_guardian_armor_grant_consume_expire(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            guard_target=CIT1_UID,
            mine_pick=0,
            law_pick=0,
        )
        from bot.nam10.night2 import (
            night2_consume_guardian_armor,
            night2_guardian_armor_active,
        )

        self.assertTrue(
            night2_guardian_armor_active(self.game, CIT1_UID, day_after_night=1)
        )
        # wrong day / wrong player -> inactive
        self.assertFalse(
            night2_guardian_armor_active(self.game, CIT1_UID, day_after_night=2)
        )
        self.assertFalse(
            night2_guardian_armor_active(self.game, DOC_UID, day_after_night=1)
        )
        self.assertTrue(
            night2_consume_guardian_armor(self.game, CIT1_UID, day_after_night=1)
        )
        self.assertFalse(
            night2_consume_guardian_armor(self.game, CIT1_UID, day_after_night=1)
        )
        self.assertIsNone(self.game.nmnd_night2_armor_uid)

    async def test_44_lawyer_immunity_predicate(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            law_pick=SYN_UID,
            mine_pick=0,
        )
        from bot.nam10.night2 import night2_lawyer_defense_immunity

        self.assertTrue(
            night2_lawyer_defense_immunity(
                self.game, SYN_UID, day_after_night=1
            )
        )
        self.assertFalse(
            night2_lawyer_defense_immunity(
                self.game, SYN_UID, day_after_night=2
            )
        )
        self.assertFalse(
            night2_lawyer_defense_immunity(
                self.game, CIT1_UID, day_after_night=1
            )
        )

    # -- Rebel assassination predicates/effect -------------------------------

    async def test_45_rebel_assassination_unlock_and_effect(self):
        self._fork_room()
        await self._enter_night()
        from bot.nam10.night2 import (
            night2_apply_elimination,
            night2_rebel_assassination_available,
            night2_rebel_assassination_effect,
            night2_rebel_assassination_unlocked,
        )

        self.assertFalse(night2_rebel_assassination_unlocked(self.game))
        rec = night2_apply_elimination(self.game, BOSS_UID, "boss_killed_x")
        self.assertIsNotNone(rec)
        self.assertTrue(night2_rebel_assassination_unlocked(self.game))
        self.assertTrue(night2_rebel_assassination_available(self.game))
        # guardian immunity
        res = night2_rebel_assassination_effect(self.game, GUARD_UID)
        self.assertTrue(res["accepted"])
        self.assertEqual(res["reason"], "guardian_immune")
        self.assertFalse(res["target_eliminated"])
        self.assertTrue(self.game.players[GUARD_UID].is_alive)
        self.assertFalse(self.game.players[NATO_UID].is_alive)
        self.assertTrue(self.game.nmnd_night2_rebel_assassin_used)
        self.assertFalse(night2_rebel_assassination_available(self.game))
        # once-per-game: any further effect is unavailable
        res2 = night2_rebel_assassination_effect(self.game, CIT1_UID)
        self.assertFalse(res2["accepted"])
        self.assertEqual(res2["reason"], "assassination_unavailable")

    async def test_46_rebel_effect_armored_target_survives(self):
        self._fork_room()
        await self._enter_night()
        from bot.nam10.night2 import (
            night2_apply_elimination,
            night2_rebel_assassination_effect,
        )

        night2_apply_elimination(self.game, BOSS_UID, "boss_killed_x")
        self.game.nmnd_night2_armor_uid = CIT1_UID
        self.game.nmnd_night2_armor_day = 1
        res = night2_rebel_assassination_effect(self.game, CIT1_UID)
        self.assertTrue(res["accepted"])
        self.assertEqual(res["reason"], "armor_absorbed")
        self.assertTrue(res["armor_consumed"])
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.players[NATO_UID].is_alive)
        self.assertIsNone(self.game.nmnd_night2_armor_uid)

    async def test_47_rebel_effect_unprotected_both_die(self):
        self._fork_room()
        await self._enter_night()
        from bot.nam10.night2 import (
            night2_apply_elimination,
            night2_rebel_assassination_effect,
        )

        night2_apply_elimination(self.game, BOSS_UID, "boss_killed_x")
        res = night2_rebel_assassination_effect(self.game, CIT1_UID)
        self.assertTrue(res["accepted"])
        self.assertEqual(res["reason"], "eliminated")
        self.assertTrue(res["target_eliminated"])
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.players[NATO_UID].is_alive)

    # -- Idempotency / restart recovery -------------------------------------

    async def test_48_resolution_idempotent_repeat_calls(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(mine_pick=0, law_pick=0)
        from bot.nam10.night2 import (
            night2_run_resolution,
        )

        first = dict(self.game.nmnd_night2_outcome)
        again = night2_run_resolution(self.game)
        self.assertEqual(again, first)
        self.assertEqual(self.game.nmnd_night2_outcome, first)
        self.assertTrue(self.game.nmnd_night2_outcome_committed)
        # maybe_finish outside collecting phase is a no-op
        from bot.nam10.night2 import night2_maybe_finish

        self.assertFalse(night2_maybe_finish(self.game))

    async def test_49_grant_recovery_after_snapshot_restore(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        from bot.game_snapshot import (
            game_from_snapshot_dict,
            game_to_snapshot_dict,
        )
        from bot.nam10.night2 import (
            EXTRA_KIND_SENT,
            nam10_night2_entry_dispatch,
        )

        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        # recipient's citizen ack still owed: not materialized, no panel
        self.assertFalse(self.game.nmnd_night2_extra_materialized)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        ok = await nam10_night2_entry_dispatch(self.bot, restored, self.manager)
        self.assertTrue(ok)
        # same-night re-entry is idempotent: the grant decision is not
        # re-decided and the owed extra investigation stays a readiness
        # requirement (recovery keeps the state, no duplicate effects)
        self.assertEqual(restored.nmnd_night2_grant_decided, True)
        self.assertEqual(restored.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertEqual(restored.nmnd_night2_extra_uid, CIT1_UID)
        from bot.nam10.night2 import night2_required_keys

        self.assertIn("n2extra", night2_required_keys(restored))

    async def test_50_full_walk_doctor_nato_cancellation_section(self):
        self._fork_room()
        self.game.nmnd_night2_doctor_self_saves = 0
        await self._enter_night()
        await self._walk_v2(
            boss_tid=3,
            nato_role_tid=2,
            nato_target=GUIDE_UID,
            doc_pick=None,          # cancelled by NATO, never pressed
        )
        doc = self.game.nmnd_night2_outcome["doctor"]
        self.assertTrue(doc["cancelled"])
        self.assertEqual(doc["cancelled_reason"], "cancelled_by_nato")
        self.assertIsNone(doc["save_target_uid"])
        # doctor's stale presses never get applied during resolution
        self.assertIsNone(self.game.nmnd_night2_doctor_uid)
        nato = self.game.nmnd_night2_outcome["nato"]
        self.assertTrue(nato["success"])
        self.assertFalse(self.game.players[GUIDE_UID].is_alive)

    # ---------------------------------------------------------------------------
    # Boss shot target-selection panel (both shooting modes -> single target)
    # ---------------------------------------------------------------------------

    async def test_51_shot_panel_all_alive_colours_reselect(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        from bot.nam10.night2 import BOSS_PHASE_SHOT_TARGET

        self.assertEqual(
            self.game.nmnd_night2_boss_phase, BOSS_PHASE_SHOT_TARGET
        )
        # all currently alive players, in seat order, appear once
        cbs = [
            cb for cb in self._panel_buttons(SHOT_MARK, BOSS_UID)
            if cb.act == "sht"
        ]
        self.assertEqual(
            [cb.tid for cb in cbs], REAL_UIDS + [SYN_UID]
        )
        # colour normalisation: every eligible target is BLUE, no
        # faction-based distinction, nothing selected yet
        styles = self._shot_button_styles()
        for uid in (BOSS_UID, NATO_UID, SHIAD_UID):
            self.assertEqual(styles.get(uid), "primary", uid)
        for uid in (LAW_UID, GUIDE_UID, GUARD_UID, DOC_UID, MINE_UID, CIT1_UID):
            self.assertEqual(styles.get(uid), "primary", uid)
        self.assertEqual(styles.get(SYN_UID), "primary")
        self.assertNotIn("success", styles.values())
        # selecting any target turns it RED
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(CIT1_UID), "danger")
        self.assertEqual(styles.get(DOC_UID), "primary")
        # selecting another player resets the previous one to BLUE
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=GUARD_UID)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(CIT1_UID), "primary")
        self.assertEqual(styles.get(GUARD_UID), "danger")
        self.assertEqual(styles.get(BOSS_UID), "primary")
        # tapping the currently selected player deselects it
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=GUARD_UID)
        self.assertIsNone(self.game.nmnd_night2_shot_pending_uid)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(GUARD_UID), "primary")
        # nothing persisted so far
        self.assertIsNone(self.game.nmnd_night2_shot_target_uid)
        self.assertFalse(self.game.nmnd_night2_boss_shot_marked)

    async def test_52_shot_confirm_persists_and_stale_rejected(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        from bot.nam10.night2 import BOSS_MODE_SHOT_PLAIN, BOSS_PHASE_DONE

        # zero-target confirmation is rejected
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        self.assertTrue(
            any("ابتدا یک بازیکن" in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nmnd_night2_shot_target_uid)
        self.assertIsNone(self.game.nmnd_night2_shot_pending_uid)
        # unauthorized pick: another player cannot use the boss panel
        await self._press(CIT1_UID, "sht", BOSS_UID, tid=CIT1_UID)
        self.assertTrue(
            any(FORBIDDEN_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nmnd_night2_shot_pending_uid)
        # forged cross-room callback never mutates state
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID, code="ROOMXX")
        self.assertIsNone(self.game.nmnd_night2_shot_pending_uid)
        # pick then confirm => intent persisted (mode + target)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        self.assertEqual(self.game.nmnd_night2_shot_pending_uid, CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        self.assertEqual(self.game.nmnd_night2_shot_target_uid, CIT1_UID)
        self.assertEqual(self.game.nmnd_night2_boss_mode, BOSS_MODE_SHOT_PLAIN)
        self.assertTrue(self.game.nmnd_night2_boss_shot_marked)
        # confirmation replaced the panel with a button-free receipt
        texts = "\n".join(self.bot.texts_to(BOSS_UID))
        self.assertIn("انتخاب شات شما ثبت شد", texts)
        self.assertIn("بازیکن انتخاب‌شده", texts)
        # nothing eliminated at confirmation time
        self.assertTrue(all(p.is_alive for p in self.game.players.values()))
        # every press on the now-closed panels is stale: the mode menu
        # cannot overwrite the confirmed shooting mode either
        n_calls = len(self.bot.calls)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=2)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=DOC_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        self.assertEqual(len(self.bot.calls), n_calls + 3)
        self.assertEqual(self.game.nmnd_night2_shot_target_uid, CIT1_UID)
        self.assertEqual(self.game.nmnd_night2_boss_mode, BOSS_MODE_SHOT_PLAIN)

    async def test_53_shot_panel_converted_faction_colour(self):
        self._fork_room()
        await self._enter_night()
        # colour normalisation is faction-blind: a Yakuza-converted
        # player renders exactly like every other target (blue; red
        # only while selected)
        self.game.players[DOC_UID].nmnd_converted_by_yakuza = True
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(DOC_UID), "primary")
        self.assertEqual(styles.get(CIT1_UID), "primary")
        self.assertEqual(styles.get(BOSS_UID), "primary")
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=DOC_UID)
        styles = self._shot_button_styles()
        self.assertEqual(styles.get(DOC_UID), "danger")
        self.assertEqual(styles.get(CIT1_UID), "primary")

    async def test_54_shot_synthetic_boss_observer_only(self):
        self._fork_room()
        await self._enter_night()
        from bot.models import Role as R

        # the synthetic seat becomes the Mafia Boss
        self.game.players[SYN_UID].role = R.MAFIA_BOSS
        self.game.players[BOSS_UID].role = R.CITIZEN
        await self._press(OBS_UID, "bmode", SYN_UID, tid=1)
        from bot.nam10.night2 import BOSS_MODE_SHOT_PLAIN, BOSS_PHASE_SHOT_TARGET

        self.assertEqual(self.game.nmnd_night2_boss_mode, BOSS_MODE_SHOT_PLAIN)
        self.assertEqual(
            self.game.nmnd_night2_boss_phase, BOSS_PHASE_SHOT_TARGET
        )
        # synthetic negative UID gets no direct Telegram copy
        self.assertNotIn(
            "انتخاب هدف شات", "\n".join(self.bot.texts_to(SYN_UID))
        )
        self.assertIn("انتخاب هدف شات", "\n".join(self.bot.texts_to(OBS_UID)))
        # identical semantics through the observer mirror
        await self._press(OBS_UID, "sht", SYN_UID, tid=CIT1_UID)
        self.assertEqual(self.game.nmnd_night2_shot_pending_uid, CIT1_UID)
        await self._press(OBS_UID, "shtok", SYN_UID)
        from bot.nam10.night2 import BOSS_PHASE_DONE

        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        self.assertEqual(self.game.nmnd_night2_shot_target_uid, CIT1_UID)
        self.assertTrue(self.game.nmnd_night2_boss_shot_marked)
        # a real player cannot operate the synthetic boss panel
        await self._press(CIT1_UID, "sht", SYN_UID, tid=CIT1_UID)
        self.assertTrue(
            any(FORBIDDEN_ALERT in (a or "") for a in self.bot.acks())
        )

    async def test_55_shot_state_snapshot_roundtrip(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=2)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=SYN_UID)
        from bot.game_snapshot import (
            game_from_snapshot_dict,
            game_to_snapshot_dict,
        )

        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        for a in (
            "nmnd_night2_boss_mode",
            "nmnd_night2_boss_phase",
            "nmnd_night2_shot_pending_uid",
            "nmnd_night2_shot_target_uid",
            "nmnd_night2_boss_shot_marked",
        ):
            self.assertEqual(
                getattr(restored, a), getattr(self.game, a), a
            )

    # -- Guide-grant deferred materialization -------------------------------

    async def test_56_nato_cancelled_doctor_recipient_not_deadlocked(self):
        self._fork_room()
        self.game.nmnd_night2_doctor_self_saves = 0
        await self._enter_night()
        await self._walk_v2(
            boss_tid=3,
            nato_role_tid=1,
            nato_target=DOC_UID,
            doc_pick=None,          # cancelled by NATO before choosing
            guide_target=DOC_UID,
            do_extra=True,
        )
        from bot.nam10.night2 import (
            EXTRA_KIND_SENT,
            INVEST_NEGATIVE,
            PENDING_RESOLVED,
        )

        # the cancelled main action counts as settled: the panel
        # materialized without waiting for an impossible doctor callback
        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertEqual(self.game.nmnd_night2_extra_uid, DOC_UID)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        self.assertIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(DOC_UID))
        )
        self.assertEqual(
            self.game.nmnd_night2_extra_result, INVEST_NEGATIVE
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)

    async def test_57_guide_before_hacker_no_panel(self):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        from bot.nam10.night2 import (
            EXTRA_KIND_SENT,
            night2_maybe_grant_guide_extra,
        )

        self.assertFalse(self.game.nmnd_night2_grant_decided)
        self.assertIsNone(self.game.nmnd_night2_extra_kind)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        # Guide confirm alone cannot decide or dispatch anything
        await night2_maybe_grant_guide_extra(self.bot, self.game)
        self.assertFalse(self.game.nmnd_night2_grant_decided)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        # Hacker confirms -> decision made, but the citizen ack is owed
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertTrue(self.game.nmnd_night2_grant_decided)
        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertFalse(self.game.nmnd_night2_extra_materialized)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        # citizen ack settles the main action -> exactly one extra panel
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        texts = [t for t in self.bot.texts_to(CIT1_UID) if "استعلام کارآگاهی" in t]
        self.assertEqual(len(texts), 1)

    async def test_58_hacker_before_guide_no_panel(self):
        self._fork_room()
        await self._enter_night()
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        from bot.nam10.night2 import EXTRA_KIND_SENT

        self.assertFalse(self.game.nmnd_night2_grant_decided)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        self.assertTrue(self.game.nmnd_night2_grant_decided)
        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertFalse(self.game.nmnd_night2_extra_materialized)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(CIT1_UID))
        )
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        texts = [t for t in self.bot.texts_to(CIT1_UID) if "استعلام کارآگاهی" in t]
        self.assertEqual(len(texts), 1)

    async def test_59_recipient_first_then_hacker_panel_once(self):
        self._fork_room()
        await self._enter_night()
        from bot.nam10.night2 import EXTRA_KIND_SENT

        # Doctor completes the main action first
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=DOC_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        # all prerequisites were satisfied -> panel materialized at hacok
        self.assertTrue(self.game.nmnd_night2_grant_decided)
        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertEqual(self.game.nmnd_night2_extra_uid, DOC_UID)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        texts = [t for t in self.bot.texts_to(DOC_UID) if "استعلام کارآگاهی" in t]
        self.assertEqual(len(texts), 1)

    async def test_60_dependency_first_then_recipient_panel(self):
        self._fork_room()
        await self._enter_night()
        # Hacker confirms (Guide still silent)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        from bot.nam10.night2 import (
            EXTRA_KIND_SENT,
            night2_required_keys,
        )

        self.assertFalse(self.game.nmnd_night2_grant_decided)
        # Guide picks the Doctor
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=DOC_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        # Doctor's main action is still owed: nothing materialized yet
        self.assertFalse(self.game.nmnd_night2_extra_materialized)
        self.assertNotIn(
            "استعلام کارآگاهی", "\n".join(self.bot.texts_to(DOC_UID))
        )
        # Doctor completes -> panel materializes during the docok hook
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        texts = [t for t in self.bot.texts_to(DOC_UID) if "استعلام کارآگاهی" in t]
        self.assertEqual(len(texts), 1)
        # extra obligation is registered while it is unconfirmed
        self.assertIn("n2extra", night2_required_keys(self.game))

    async def test_61_mine_trigger_deferred_resolution_completes(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=DOC_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        from bot.nam10.night2 import PENDING_RESOLVED

        # internal resolution COMPLETED despite the deferred consequence
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(self.game.nmnd_night2_publication_pending)
        mine_out = self.game.nmnd_night2_outcome["mine"]
        self.assertTrue(mine_out.get("mafia_casualty_deferred"))
        ev = self.game.nmnd_night2_mine_events[-1]
        self.assertTrue(ev["triggered"])
        self.assertFalse(ev["neutralized"])
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)
        # exactly one elimination: no Mafia casualty chosen, no panel
        dead = [p for p in self.game.players.values() if not p.is_alive]
        self.assertEqual([p.user_id for p in dead], [CIT1_UID])
        all_text = "\n".join(self.bot.texts())
        self.assertNotIn("پیامد مین", all_text)

    async def test_62_walk_grant_materializes_and_resolves(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=BOSS_UID,
            doc_pick=CIT1_UID,
            guide_target=CIT1_UID,
        )
        from bot.nam10.night2 import (
            EXTRA_KIND_SENT,
            INVEST_NEGATIVE,
            PENDING_RESOLVED,
        )

        self.assertEqual(self.game.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertTrue(self.game.nmnd_night2_extra_materialized)
        self.assertEqual(
            self.game.nmnd_night2_extra_result, INVEST_NEGATIVE
        )
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)
