"""Namayande-10 fork: Day-1 betrayal vote, targets, reveal, outcome, night.

Covers the continuation of the Day-1 workflow after the afternoon-nap ack
(``bot/nam10/day1_betrayal.py``), driven by REAL aiogram dispatcher presses:

Stage A - betrayal collection:
  waiting panels for every alive non-Boss player (synthetic seats via the
  Observer mirror), the private Mafia Boss panel with exactly four add/
  subtract buttons, immutable Boss choice, idempotent recognition and the
  automatic completion gate.

Stage B - representative-target selection (shared assistant/Observer
  state, red/green toggles, exactly two targets, representatives eligible).

Stage C - external voting stage + public reveal of the stored Boss choice
  (dead players excluded, duplicates blocked, no early disclosure).

Stage D - Day-1 defensive outcome (eliminate target 1 / target 2 / none)
  reusing the fork elimination machinery WITHOUT any handoff workflow.

Stage E - final afternoon nap -> existing independent Namayande Night 1.

Isolated temporary storage only; never touches production rooms.
"""

import asyncio
import json
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
REAL_UIDS = list(range(901, 910))  # BOSS 901; 902/903 mafia; rest town
SYN_UID = -930001  # seat 10, synthetic
SYNC_MARK_WAIT = "رأی خیانت گروه مافیا"
BOSS_MARK = "مرحله ثبت رأی خیانت"
INTRO_MARK = "فرآیند انتخاب تارگت‌های نمایندگان"
PICK_MARK = "انتخاب تارگت‌های نمایندگان"
EXT_MARK = "رأی‌گیری روز اول — مرحله دوم"
REVEAL_MARK = "نتیجه رأی خیانت"
OUTCOME_MARK = "مرحله تعیین نتیجه دفاعیه روز اول"
NAP_MARK = "خواب نیمروزی پیش از آغاز شب"

STALE_ALERT = "این مرحله دیگر فعال نیست."
FORBIDDEN_ALERT = "شما مجاز به این عمل نیستید."
ALREADY_ALERT = "این انتخاب قبلاً ثبت شده است."
NEED_TWO_TGT = "لطفاً دقیقاً دو تارگت انتخاب کنید."
MAX_TWO_TGT = "حداکثر دو تارگت"


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
            if type(c).__name__ == "SendMessage":
                out.append((getattr(c, "chat_id", None), getattr(c, "text", "")))
            elif getattr(c, "_cls", None) == "send_message":
                args = getattr(c, "_rec_args", ())
                kw = getattr(c, "_rec_kwargs", {}) or {}
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

    def send_counts(self, mark: str):
        """(chat_id -> number of send_message copies containing mark)."""
        counts = {}
        for chat, t in self.sends():
            if mark in t:
                counts[chat] = counts.get(chat, 0) + 1
        return counts


class Nam10Day1BetrayalTest(unittest.IsolatedAsyncioTestCase):
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
        from bot.nam10.nmnd_narrator import DAY_DISCUSS, Role

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
                full_name="امیر-نقش",
                username=None,
                role=None,
                is_alive=True,
                seat=10,
            ),
        )
        assert err is None, err
        # Standard size roster: Boss 901, mafia 902/903, rest town.
        team_map = {
            REAL_UIDS[0]: Role.MAFIA_BOSS,
            REAL_UIDS[1]: Role.MAFIA,
            REAL_UIDS[2]: Role.MAFIA,
        }
        for uid, pl in game.players.items():
            pl.role = team_map.get(uid, Role.CITIZEN)
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_step = DAY_DISCUSS
        if with_observer:
            game.observer_user_id = OBS_UID
            game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game
        return game

    async def _funnel(self):
        from bot.nam10.no_host_day_vote import send_no_host_day_vote_prompt

        await send_no_host_day_vote_prompt(self.bot, self.game)

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

    # ---- flow walkers --------------------------------------------------
    async def _walk_to_stage_a(self):
        """Day-1 funnel -> reps [904, 902] -> nap ack -> Stage A active."""
        await self._funnel()
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=904)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=902)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)

    async def _boss_choose(self, op: str, rep_uid: int, actor=BOSS_UID):
        await self._press(
            actor, "d1ba" if op == "add" else "d1bs", BOSS_UID, tid=rep_uid
        )
        # Two-step flow: the pick is only a pending selection; the
        # choice is committed by the separate '✅ تأیید انتخاب' press.
        await self._press(actor, "d1bak", BOSS_UID)

    def _wait_uids(self):
        """Alive players that still owe a waiting-panel acknowledgement."""
        from bot.nam10.day1_betrayal import _alive_mafia_boss

        boss = _alive_mafia_boss(self.game)
        boss_uid = boss.user_id if boss is not None else None
        return [
            uid
            for uid, p in self.game.players.items()
            if p.is_alive and uid != boss_uid
        ]

    async def _ack_one(self, uid: int, actor=None):
        await self._press(actor or uid, "d1bw", uid)

    async def _ack_all_waiting(self):
        for uid in self._wait_uids():
            actor = OBS_UID if uid == SYN_UID else uid
            await self._press(actor, "d1bw", uid)

    async def _walk_to_target_intro(self, *, boss_first=True):
        await self._walk_to_stage_a()
        if boss_first:
            await self._boss_choose("add", 904)
            await self._ack_all_waiting()
        else:
            await self._ack_all_waiting()
            await self._boss_choose("add", 904)

    async def _walk_to_target_pick(self):
        await self._walk_to_target_intro()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)

    async def _choose_targets(self, first: int, second: int, actor=ASSIST_UID):
        await self._press(actor, "d1tt", ASSIST_UID, tid=first)
        await self._press(actor, "d1tt", ASSIST_UID, tid=second)
        await self._press(actor, "d1tok", ASSIST_UID)

    async def _walk_to_ext_vote(self, t1=907, t2=903):
        await self._walk_to_target_pick()
        await self._choose_targets(t1, t2)

    async def _reveal(self, actor=ASSIST_UID):
        await self._press(actor, "d1rv", ASSIST_UID)

    async def _walk_to_outcome(self, t1=907, t2=903):
        await self._walk_to_ext_vote(t1, t2)
        await self._reveal()

    def _panel_buttons(self, *marks: str):
        """pmr buttons of the LAST panel whose text contains any mark."""
        picked = None
        for text, kb in self.bot.kb_segments():
            if any(m in text for m in marks) and kb is not None:
                picked = kb
        if picked is None:
            return []
        out = []
        for row in picked.inline_keyboard:
            for btn in row:
                if (
                    isinstance(btn, InlineKeyboardButton)
                    and (btn.callback_data or "").startswith("pmr:")
                ):
                    out.append(PlayerMirrorCb.unpack(btn.callback_data))
        return out

    def _button_objects(self, mark: str):
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

    def _audit_events(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    # =================================================================
    # Stage A — betrayal-vote collection
    # =================================================================
    async def test_01_nap_ack_opens_collection_panels(self):
        self._fork_room()
        await self._walk_to_stage_a()
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(
            self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT
        )
        self.assertTrue(
            any(SYNC_MARK_WAIT in t for t in self.bot.texts())
        )
        # Every alive non-Boss player has an OK panel bound to its uid.
        sel = set()
        for text, kb in self.bot.kb_segments():
            if SYNC_MARK_WAIT in text and kb is not None:
                for row in kb.inline_keyboard:
                    for btn in row:
                        if (
                            isinstance(btn, InlineKeyboardButton)
                            and (btn.callback_data or "").startswith("pmr:")
                        ):
                            cb = PlayerMirrorCb.unpack(btn.callback_data)
                            self.assertEqual(cb.act, "d1bw")
                            sel.add(cb.as_uid)
        self.assertEqual(sel, set(self._wait_uids()))
        self.assertNotIn(BOSS_UID, sel)
        ok_btns = [
            b
            for b in self._button_objects(SYNC_MARK_WAIT)
            if (b.callback_data or "").startswith("pmr:")
        ]
        self.assertTrue(ok_btns)
        self.assertEqual(ok_btns[0].text, "✅ اوکی")
        self.assertEqual(ok_btns[0].style, "primary")
        # Mafia Boss private panel: exactly FOUR option buttons
        # (one per own row) plus exactly ONE confirm button.
        boss_btns = [
            b
            for b in self._button_objects(BOSS_MARK)
            if (b.callback_data or "").startswith("pmr:")
        ]
        self.assertEqual(len(boss_btns), 5)
        confirm_btns = [
            b for b in boss_btns if b.text == "✅ تأیید انتخاب"
        ]
        self.assertEqual(len(confirm_btns), 1)
        self.assertEqual(confirm_btns[0].style, "success")
        self.assertTrue(
            all(
                b.style == "primary"
                for b in boss_btns
                if b.text != "✅ تأیید انتخاب"
            ),
            [b.text for b in boss_btns],
        )
        boss_acts = {cb.act for cb in self._panel_buttons(BOSS_MARK)}
        self.assertEqual(boss_acts, {"d1ba", "d1bs", "d1bak"})
        texts = [b.text for b in boss_btns]
        self.assertTrue(any("➕ افزودن یک رأی به" in t for t in texts))
        self.assertTrue(any("➖ کسر یک رأی از" in t for t in texts))
        self.assertTrue(any("نماینده ۱" in t for t in texts))
        self.assertTrue(any("نماینده ۲" in t for t in texts))
        confirms = [t for t in texts if t == "✅ تأیید انتخاب"]
        self.assertEqual(len(confirms), 1)
        # Each option occupies its OWN keyboard row (no side-by-side).
        boss_kb = next(
            kb
            for text, kb in self.bot.kb_segments()
            if BOSS_MARK in text and kb is not None
        )
        option_rows = [
            row
            for row in boss_kb.inline_keyboard
            if any(
                (btn.callback_data or "").startswith("pmr:")
                and PlayerMirrorCb.unpack(btn.callback_data).act
                in ("d1ba", "d1bs")
                for btn in row
                if isinstance(btn, InlineKeyboardButton)
            )
        ]
        self.assertEqual(len(option_rows), 4)
        self.assertTrue(
            all(len(row) == 1 for row in option_rows), option_rows
        )
        # The actual representative names are in the panel body.
        boss_texts = [t for t, _ in self.bot.kb_segments() if BOSS_MARK in t]
        self.assertTrue(boss_texts)
        body = "\n".join(boss_texts)
        self.assertIn("بازیکن 4", body)
        self.assertIn("بازیکن 2", body)
        self.assertIn("<b>نماینده ۱:</b>", body)
        self.assertIn("<b>نماینده ۲:</b>", body)

    async def test_02_eliminated_players_receive_nothing(self):
        self._fork_room()
        # 909 knew its fate earlier in the day.
        self.game.players[909].is_alive = False
        await self._walk_to_stage_a()
        wait_players = {
            cb.as_uid
            for text, kb in self.bot.kb_segments()
            if SYNC_MARK_WAIT in text and kb is not None
            for row in kb.inline_keyboard
            for btn in row
            if isinstance(btn, InlineKeyboardButton)
            and (btn.callback_data or "").startswith("pmr:")
            for cb in [PlayerMirrorCb.unpack(btn.callback_data)]
            if cb.act == "d1bw"
        }
        self.assertNotIn(909, wait_players)
        direct = {chat for chat, _ in self.bot.sends()}
        self.assertNotIn(909, direct)

    async def test_03_boss_choice_recorded_immutable_panel_closed(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._boss_choose("add", 904)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(self.game.nam10_day1_betrayal_op, "add")
        self.assertEqual(self.game.nam10_day1_betrayal_rep_uid, 904)
        self.assertEqual(self.game.nam10_day1_betrayal_boss_uid, BOSS_UID)
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT)
        best = None
        for text, kb in self.bot.kb_segments():
            if "رأی خیانت شما ثبت شد" in text:
                best = (text, kb)
        self.assertIsNotNone(best)
        body, kb = best
        self.assertIn("افزودن یک رأی به", body)
        self.assertIsNone(kb)
        # Immutable: further presses change nothing.
        await self._boss_choose("add", 902)
        await self._boss_choose("sub", 902)
        self.assertEqual(self.game.nam10_day1_betrayal_op, "add")
        self.assertEqual(self.game.nam10_day1_betrayal_rep_uid, 904)
        self.assertTrue(any(a and ALREADY_ALERT in a for a in self.bot.acks()))

    async def test_04_boss_choice_alone_does_not_advance(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._boss_choose("add", 904)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT)
        self.assertNotIn(INTRO_MARK, "\n".join(self.bot.texts()))
        # Privacy: nothing public about the Boss choice before the reveal.
        self.assertNotIn(REVEAL_MARK, "\n".join(self.bot.texts()))

    async def test_05_wait_ack_finalizes_panel_idempotent(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._ack_one(905)
        self.assertIn(905, self.game.nam10_day1_betrayal_waiting_confirmed_uids)
        done = [
            (t, kb)
            for t, kb in self.bot.kb_segments()
            if t.startswith("🌙 <b>رأی خیانت گروه مافیا</b>") and "✅ ثبت شد." in t
        ]
        self.assertTrue(done)
        self.assertIsNone(done[-1][1])
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT)
        await self._ack_one(905)
        self.assertTrue(any(a and ALREADY_ALERT in a for a in self.bot.acks()))
        self.assertEqual(
            self.game.nam10_day1_betrayal_waiting_confirmed_uids.count(905), 1
        )

    async def test_06_all_waiting_without_boss_choice_no_advance(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._ack_all_waiting()
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT)
        self.assertEqual(
            len(self.game.nam10_day1_betrayal_waiting_confirmed_uids),
            len(self._wait_uids()),
        )
        self.assertNotIn(INTRO_MARK, "\n".join(self.bot.texts()))

    async def test_07_boss_first_then_acks_auto_advance(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._boss_choose("add", 904)
        await self._ack_all_waiting()
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_TARGET_INTRO

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_TARGET_INTRO)
        self.assertTrue(any(INTRO_MARK in t for t in self.bot.texts()))
        # one shared intro panel with the 👥 button
        pairs = self._panel_buttons(INTRO_MARK)
        self.assertEqual({cb.act for cb in pairs}, {"d1to"})
        self.assertEqual({cb.as_uid for cb in pairs}, {ASSIST_UID})

    async def test_08_acks_first_then_boss_also_advances(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._ack_all_waiting()
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT)
        await self._boss_choose("sub", 902)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_TARGET_INTRO

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_TARGET_INTRO)
        self.assertEqual(self.game.nam10_day1_betrayal_op, "sub")
        self.assertEqual(self.game.nam10_day1_betrayal_rep_uid, 902)

    async def test_09_observer_acks_synthetic_and_rejections(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._ack_one(SYN_UID, actor=OBS_UID)
        self.assertIn(SYN_UID, self.game.nam10_day1_betrayal_waiting_confirmed_uids)
        # real player cannot ack for someone else
        before = list(self.game.nam10_day1_betrayal_waiting_confirmed_uids)
        await self._press(906, "d1bw", 905)
        self.assertTrue(any(a and FORBIDDEN_ALERT in a for a in self.bot.acks()))
        self.assertEqual(
            self.game.nam10_day1_betrayal_waiting_confirmed_uids, before
        )
        # Observer cannot choose for the REAL Mafia Boss
        await self._press(OBS_UID, "d1ba", BOSS_UID, tid=904)
        self.assertTrue(any(a and FORBIDDEN_ALERT in a for a in self.bot.acks()))
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        # a player cannot act as the Boss either
        await self._press(906, "d1ba", BOSS_UID, tid=904)
        self.assertIsNone(self.game.nam10_day1_betrayal_op)

    async def test_10_synthetic_boss_act_via_observer_mirror(self):
        self._fork_room()
        from bot.nam10.nmnd_narrator import Role

        self.game.players[SYN_UID].role = Role.MAFIA_BOSS
        self.game.players[BOSS_UID].role = Role.CITIZEN
        await self._walk_to_stage_a()
        # No direct delivery to a synthetic chat; only the Observer mirror.
        direct = {chat for chat, _ in self.bot.sends()}
        self.assertNotIn(SYN_UID, direct)
        from bot.nam10.day1_betrayal import _alive_mafia_boss

        self.assertEqual(_alive_mafia_boss(self.game).user_id, SYN_UID)
        # Real player cannot act as the synthetic Boss.
        await self._press(905, "d1ba", SYN_UID, tid=904)
        self.assertTrue(any(a and FORBIDDEN_ALERT in a for a in self.bot.acks()))
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        # Registered Observer may fulfil the synthetic Boss's action
        # (pending pick, then the two-step confirm).
        await self._press(OBS_UID, "d1ba", SYN_UID, tid=904)
        self.assertIsNone(self.game.nam10_day1_betrayal_op)
        self.assertEqual(
            self.game.nam10_day1_betrayal_pending_rep_uid, 904
        )
        await self._press(OBS_UID, "d1bak", SYN_UID)
        self.assertEqual(self.game.nam10_day1_betrayal_op, "add")
        self.assertEqual(self.game.nam10_day1_betrayal_rep_uid, 904)
        self.assertEqual(self.game.nam10_day1_betrayal_boss_uid, SYN_UID)

    async def test_11_mid_stage_elimination_recomputes_obligation(self):
        self._fork_room()
        await self._walk_to_stage_a()
        for uid in (902, 903, 904, 905):
            await self._ack_one(uid)
        # 907 leaves scope mid-stage (e.g. an external moderator decision is
        # out of the question here; this emulates any authoritative removal).
        self.game.players[907].is_alive = False
        await self._boss_choose("add", 904)
        remaining = [
            u
            for u in self._wait_uids()
            if u not in self.game.nam10_day1_betrayal_waiting_confirmed_uids
        ]
        for uid in remaining:
            actor = OBS_UID if uid == SYN_UID else uid
            await self._press(actor, "d1bw", uid)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_TARGET_INTRO

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_TARGET_INTRO)
        self.assertNotIn(907, self.game.nam10_day1_betrayal_waiting_confirmed_uids)

    # =================================================================
    # Stage B — representative-target selection
    # =================================================================
    async def test_12_target_pick_panel_all_alive_red_including_reps(self):
        self._fork_room()
        await self._walk_to_target_intro()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_TARGET_PICK

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_TARGET_PICK)
        cbs = self._panel_buttons(PICK_MARK)
        toggles = [cb for cb in cbs if cb.act == "d1tt"]
        self.assertEqual(
            {cb.tid for cb in toggles},
            {u for u, p in self.game.players.items() if p.is_alive},
        )
        btns = self._button_objects(PICK_MARK)
        player_btns = [b for b in btns if (b.callback_data or "").startswith("pmr:") and ". " in b.text]
        self.assertTrue(all(b.style == "primary" for b in player_btns))
        self.assertTrue(all(b.text.startswith("☐") for b in player_btns))
        ok = [b for b in btns if (b.callback_data or "").startswith("pmr:") and b.text == "✅ OK"]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0].style, "success")

    async def test_13_target_toggle_and_third_blocked(self):
        self._fork_room()
        await self._walk_to_target_pick()
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=905)
        self.assertEqual(self.game.nam10_day1_target_pending, [905])
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=906)
        self.assertEqual(self.game.nam10_day1_target_pending, [905, 906])
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=907)
        self.assertTrue(any(a and MAX_TWO_TGT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nam10_day1_target_pending, [905, 906])
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=905)
        self.assertEqual(self.game.nam10_day1_target_pending, [906])
        green = [
            b
            for b in self._button_objects(PICK_MARK)
            if (b.callback_data or "").startswith("pmr:") and ". " in b.text
            and b.style == "danger"
        ]
        self.assertEqual(len(green), 1)

    async def test_14_target_ok_needs_exactly_two(self):
        self._fork_room()
        await self._walk_to_target_pick()
        await self._press(ASSIST_UID, "d1tok", ASSIST_UID)
        self.assertTrue(any(a and NEED_TWO_TGT in a for a in self.bot.acks()))
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_TARGET_PICK

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_TARGET_PICK)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=908)
        await self._press(ASSIST_UID, "d1tok", ASSIST_UID)
        self.assertTrue(any(a and NEED_TWO_TGT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nam10_day1_target_uids, [])

    async def test_15_target_confirm_stores_order_and_advances(self):
        self._fork_room()
        await self._walk_to_target_pick()
        await self._choose_targets(907, 903)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_EXT_VOTE

        self.assertEqual(self.game.nam10_day1_target_uids, [907, 903])
        self.assertEqual(self.game.nam10_day1_target_pending, [])
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_EXT_VOTE)
        self.assertTrue(any(EXT_MARK in t for t in self.bot.texts()))
        cbs = self._panel_buttons(EXT_MARK)
        self.assertEqual({cb.act for cb in cbs}, {"d1rv"})
        self.assertEqual(
            [b.text for b in self._button_objects(EXT_MARK)],
            ["🔎 مشاهده رأی خیانت"],
        )

    async def test_16_observer_shares_target_selection_state(self):
        self._fork_room()
        await self._walk_to_target_pick()
        await self._press(OBS_UID, "d1tt", ASSIST_UID, tid=906)
        self.assertEqual(self.game.nam10_day1_target_pending, [906])
        await self._press(OBS_UID, "d1tt", ASSIST_UID, tid=905)
        self.assertEqual(self.game.nam10_day1_target_pending, [906, 905])
        await self._press(OBS_UID, "d1tok", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_EXT_VOTE

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_EXT_VOTE)
        self.assertEqual(self.game.nam10_day1_target_uids, [906, 905])

    # =================================================================
    # Stage C — external voting stage + reveal
    # =================================================================
    async def test_17_reveal_blocked_before_stage(self):
        self._fork_room()
        await self._walk_to_stage_a()
        # Stage A: reveal pressed far too early.
        await self._press(ASSIST_UID, "d1rv", ASSIST_UID)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()))
        self.assertFalse(self.game.nam10_day1_betrayal_revealed)
        self.assertEqual(self.bot.send_counts(REVEAL_MARK), {})
        # Target pick stage: still not allowed.
        await self._boss_choose("add", 904)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rv", ASSIST_UID)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()[-3:]))
        self.assertEqual(self.bot.send_counts(REVEAL_MARK), {})

    async def test_18_reveal_broadcast_matches_stored_choice(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._boss_choose("add", 904)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._choose_targets(907, 903)
        await self._reveal()
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_OUTCOME

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_OUTCOME)
        self.assertTrue(self.game.nam10_day1_betrayal_revealed)
        sends = self.bot.send_counts(REVEAL_MARK)
        alive_real = {u for u, p in self.game.players.items() if p.is_alive}
        for uid in alive_real:
            if uid == SYN_UID:
                self.assertNotIn(uid, sends)
            else:
                self.assertEqual(sends.get(uid, 0), 1, uid)
        self.assertNotIn(SYN_UID, sends)
        reveal_texts = [t for chat, t in self.bot.sends() if REVEAL_MARK in t]
        self.assertTrue(reveal_texts)
        self.assertTrue(
            all("➕ یک رأی به بازیکن 4 اضافه شد." in t for t in reveal_texts)
        )
        reveal_texts_minus = [
            t for t in reveal_texts if "کسر" in t
        ]
        self.assertEqual(reveal_texts_minus, [])
        # the reveal message carries no keyboard
        self.assertTrue(
            any(
                "نتیجه رأی خیانت" in t and kb is None
                for t, kb in self.bot.kb_segments()
            )
        )

    async def test_19_reveal_only_once_and_no_eligible_duplicate(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        counts = self.bot.send_counts(REVEAL_MARK)
        await self._reveal()
        await self._reveal()
        self.assertEqual(self.bot.send_counts(REVEAL_MARK), counts)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()[-2:]))

    async def test_20_subtract_choice_reveal_label(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._boss_choose("sub", 902)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._choose_targets(905, 908)
        await self._reveal()
        reveal_texts = [t for chat, t in self.bot.sends() if REVEAL_MARK in t]
        self.assertTrue(reveal_texts)
        self.assertTrue(
            all("➖ یک رأی از بازیکن 2 کسر شد." in t for t in reveal_texts)
        )
        self.assertTrue(
            all("اضافه" not in t for t in reveal_texts)
        )

    # =================================================================
    # Stage D — Day-1 defensive outcome
    # =================================================================
    async def test_21_outcome_panel_three_primary_buttons(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        btns = self._button_objects(OUTCOME_MARK)
        pmr = [b for b in btns if (b.callback_data or "").startswith("pmr:")]
        self.assertEqual(len(pmr), 3)
        self.assertTrue(all(b.style == "primary" for b in pmr))
        acts = {cb.act for cb in self._panel_buttons(OUTCOME_MARK)}
        self.assertEqual(acts, {"d1o1", "d1o2", "d1o0"})
        texts = [b.text for b in pmr]
        self.assertTrue(any("🚪 خروج بازیکن 7" in t for t in texts))
        self.assertTrue(any("🚪 خروج بازیکن 3" in t for t in texts))
        self.assertIn("🌙 خروجی نداشتیم", texts)

    async def test_22_eliminate_target1(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        nights_before = self.game.nmnd_narrator_night_count
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_FINAL_NAP

        self.assertFalse(self.game.players[907].is_alive)
        self.assertTrue(self.game.players[903].is_alive)
        self.assertEqual(self.game.nam10_day1_defense_outcome, "elim_1")
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_FINAL_NAP)
        self.assertEqual(
            self.game.nmnd_narrator_night_count, nights_before
        )
        # elimination broadcast reached alive players
        elim_sends = self.bot.send_counts("پایان روز اول")
        self.assertTrue(elim_sends)
        # the eliminated player no longer gets game broadcasts, but did
        # receive its own private notification from the elimination flow
        self.assertTrue(
            any(chat == 907 for chat, _ in self.bot.sends())
        )
        # no handoff / no defense flow side effects
        self.assertIsNone(self.game.nam10_day1_defense_phase)
        self.assertFalse(self.game.nam10_day1_defense_active)
        events = self._audit_events()
        names = {e.get("event") for e in events}
        self.assertIn("no_host.day1_defense_outcome_selected", names)

    async def test_23_eliminate_target2(self):
        self._fork_room()
        await self._walk_to_outcome(t1=905, t2=909)
        await self._press(ASSIST_UID, "d1o2", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_FINAL_NAP

        self.assertFalse(self.game.players[909].is_alive)
        self.assertTrue(self.game.players[905].is_alive)
        self.assertEqual(self.game.nam10_day1_defense_outcome, "elim_2")
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_FINAL_NAP)

    async def test_24_no_elimination_outcome(self):
        self._fork_room()
        await self._walk_to_outcome(t1=905, t2=909)
        await self._press(ASSIST_UID, "d1o0", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_FINAL_NAP

        self.assertTrue(self.game.players[905].is_alive)
        self.assertTrue(self.game.players[909].is_alive)
        self.assertEqual(self.game.nam10_day1_defense_outcome, "none")
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_FINAL_NAP)
        self.assertTrue(self.game.nam10_day1_final_nap_acked is False)

    async def test_25_faction_win_ends_game_without_nap(self):
        self._fork_room()
        from bot.nam10.nmnd_narrator import Role

        # five mafia-sided (Boss + 4) vs five town; eliminating one town
        # player makes mafia >= town -> immediate faction win.
        for uid in (902, 906, 907, 908, 909):
            self.game.players[uid].role = Role.MAFIA
        for uid in (903, 904, 905, SYN_UID):
            self.game.players[uid].role = Role.CITIZEN
        await self._walk_to_outcome(t1=903, t2=904)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)
        # Faction-win finalization closes the room (removed from the
        # manager); the final nap stage must never open.
        from bot.nam10.day1_betrayal import (
            NAM10_DAY1_STAGE_FINAL_NAP,
            NAM10_DAY1_STAGE_OUTCOME,
        )

        self.assertIsNone(self.manager.get_game(self.game.room_code))
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_OUTCOME)
        self.assertNotIn(NAP_MARK, "\n".join(self.bot.texts()))
        self.assertFalse(self.game.players[903].is_alive)

    # =================================================================
    # Stage E — final afternoon nap -> Night 1
    # =================================================================
    async def test_26_final_nap_ack_enters_night_exactly_once(self):
        self._fork_room()
        await self._walk_to_outcome(t1=905, t2=909)
        await self._press(ASSIST_UID, "d1o0", ASSIST_UID)
        from bot.nam10.day1_betrayal import (
            NAM10_DAY1_STAGE_FINAL_NAP,
            NAM10_DAY1_STAGE_NIGHT_ENTERED,
        )

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_FINAL_NAP)
        self.assertTrue(any(NAP_MARK in t for t in self.bot.texts()))
        nap_btns = self._panel_buttons(NAP_MARK)
        self.assertEqual({cb.act for cb in nap_btns}, {"d1fn"})
        from bot.nam10.nmnd_narrator import NIGHT_START

        nights_before = self.game.nmnd_narrator_night_count
        await self._press(ASSIST_UID, "d1fn", ASSIST_UID)
        self.assertTrue(self.game.nam10_day1_final_nap_acked)
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_NIGHT_ENTERED)
        self.assertEqual(
            self.game.nmnd_narrator_night_count, nights_before + 1
        )
        self.assertIn(self.game.nmnd_narrator_step, (NIGHT_START, "night2_wait"))
        self.assertFalse(self.game.nam10_day1_defense_active)
        self.assertIsNone(self.game.nam10_day1_defense_phase)
        # repeated press cannot re-enter the night
        await self._press(ASSIST_UID, "d1fn", ASSIST_UID)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()))
        self.assertEqual(
            self.game.nmnd_narrator_night_count, nights_before + 1
        )

    async def test_27_final_nap_after_elimination_path(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)
        from bot.nam10.nmnd_narrator import NIGHT_START

        nights_before = self.game.nmnd_narrator_night_count
        await self._press(OBS_UID, "d1fn", ASSIST_UID)
        self.assertTrue(self.game.nam10_day1_final_nap_acked)
        self.assertEqual(
            self.game.nmnd_narrator_night_count, nights_before + 1
        )
        self.assertIn(self.game.nmnd_narrator_step, (NIGHT_START, "night2_wait"))
        self.assertFalse(self.game.players[907].is_alive)

    # =================================================================
    # Persistence, isolation, history
    # =================================================================
    async def test_28_snapshot_roundtrip_at_each_stage(self):
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict

        self._fork_room()
        await self._walk_to_stage_a()
        await self._ack_one(905)
        snapshot = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(snapshot)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(restored.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT)
        self.assertEqual(
            restored.nam10_day1_betrayal_waiting_confirmed_uids, [905]
        )
        self.assertIsNone(restored.nam10_day1_betrayal_op)

        await self._boss_choose("sub", 902)
        snapshot = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(snapshot)
        self.assertEqual(restored.nam10_day1_betrayal_op, "sub")
        self.assertEqual(restored.nam10_day1_betrayal_rep_uid, 902)
        self.assertEqual(restored.nam10_day1_betrayal_boss_uid, BOSS_UID)

        await self._ack_all_waiting()
        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_TARGET_INTRO

        self.assertEqual(restored.nam10_day1_stage, NAM10_DAY1_STAGE_TARGET_INTRO)

        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        self.assertEqual(restored.nam10_day1_target_uids, [])
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._choose_targets(906, 904)
        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_EXT_VOTE

        self.assertEqual(restored.nam10_day1_stage, NAM10_DAY1_STAGE_EXT_VOTE)
        self.assertEqual(restored.nam10_day1_target_uids, [906, 904])

        await self._reveal()
        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        self.assertTrue(restored.nam10_day1_betrayal_revealed)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_OUTCOME

        self.assertEqual(restored.nam10_day1_stage, NAM10_DAY1_STAGE_OUTCOME)

        await self._press(ASSIST_UID, "d1o0", ASSIST_UID)
        restored = game_from_snapshot_dict(game_to_snapshot_dict(self.game))
        self.assertEqual(restored.nam10_day1_defense_outcome, "none")
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_FINAL_NAP

        self.assertEqual(restored.nam10_day1_stage, NAM10_DAY1_STAGE_FINAL_NAP)

    async def test_29_replay_protection_and_unknown_seat(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._ack_one(905)
        # duplicate replay of the same ack is idempotent
        await self._ack_one(905)
        self.assertEqual(
            self.game.nam10_day1_betrayal_waiting_confirmed_uids.count(905), 1
        )
        # unknown seat uid is rejected
        before = list(self.game.nam10_day1_betrayal_waiting_confirmed_uids)
        await self._press(424242, "d1bw", 424242)
        self.assertEqual(
            self.game.nam10_day1_betrayal_waiting_confirmed_uids, before
        )
        # once the stage advanced, old waiting presses become stale
        await self._boss_choose("add", 904)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        n_calls = len(self.bot.calls)
        await self._ack_one(906)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()))
        self.assertEqual(len(self.bot.calls), n_calls + 1)

    async def test_30_audit_events_and_privacy_boundaries(self):
        self._fork_room()
        await self._walk_to_stage_a()
        await self._boss_choose("add", 904)
        await self._ack_one(905)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._choose_targets(906, 904)
        await self._reveal()
        await self._press(ASSIST_UID, "d1o2", ASSIST_UID)
        await self._press(ASSIST_UID, "d1fn", ASSIST_UID)
        events = self._audit_events()
        names = {e.get("event") for e in events}
        for event in (
            "no_host.day1_afternoon_nap_acked",
            "no_host.day1_betrayal_collection_started",
            "no_host.day1_boss_betrayal_selected",
            "no_host.day1_betrayal_waiting_acked",
            "no_host.day1_betrayal_collection_completed",
            "no_host.day1_targets_confirmed",
            "no_host.day1_betrayal_revealed",
            "no_host.day1_defense_outcome_selected",
            "no_host.day1_final_nap_started",
            "no_host.day1_final_nap_acked",
            "no_host.day1_night1_entry_started",
        ):
            self.assertIn(event, names, event)
        # the stored Boss choice survives in the audit stream only
        boss_ev = [
            e
            for e in events
            if e.get("event") == "no_host.day1_boss_betrayal_selected"
        ]
        self.assertEqual(boss_ev[0].get("op"), "add")
        self.assertEqual(boss_ev[0].get("rep_uid"), 904)
        # eliminated player (target 2 = 904) report DB accessible read-only
        self.assertFalse(self.game.players[904].is_alive)


if __name__ == "__main__":
    unittest.main()
