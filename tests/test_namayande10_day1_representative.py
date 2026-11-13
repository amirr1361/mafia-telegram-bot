"""Namayande-10 fork: Day-1 representative selection + afternoon-nap stages.

Covers the new Day-1 insertion that runs BEFORE the ordinary Day-1 defense
pick panel (only for ``is_namayande10_no_host_room`` rooms):

1. Day-1 routes to the representative-intro stage instead of the defense
   pick panel; legacy Day-1/Day-2+ paths and other scenarios are untouched.
2. Exactly ten player buttons in seat order, no role information, native
   red/green styling, synthetic role suffixes hidden (UI only).
3. Toggle semantics: max two green, order preserved, no auto-advance.
4. OK validation, representative-UID storage order, panel closure.
5. Assistant/Observer share ONE selection state; unauthorized and
   stale/duplicate presses are rejected.
6. Afternoon-nap acknowledgement is idempotent and hands control to the
   Day-1 betrayal-vote workflow (Stage A panels open automatically); the
   ordinary Day-1 defense flow still cannot bypass it.
7. Snapshot round-trip of the new stage/UID fields.

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
from aiogram.types import CallbackQuery, Chat, Message, Update, User

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

ASSIST_UID = 80012
OBS_UID = 80013
REAL_UIDS = list(range(901, 910))  # seats 1..9
SYN_UID = -930001  # seat 10, synthetic with a decorative role suffix
SYN_RAW_NAME = "امیر-نقش"

INTRO_MARK = "فرآیند انتخاب نمایندگان روز اول آغاز شد"
PICK_MARK = "انتخاب نمایندگان روز اول"
NAP_MARK = "خواب نیمروزی — فرآیند رأی خیانت"
NAP_ACK_MARK = "پایان خواب نیمروزی ثبت شد"
DEFENSE_PICK_MARK = "روز شروع شد"
NEED_TWO_ALERT = "لطفاً دقیقاً دو نماینده انتخاب کنید."
MAX_TWO_ALERT = "حداکثر دو نماینده"
STALE_ALERT = "این مرحله دیگر فعال نیست."
FORBIDDEN_ALERT = "شما مجاز به این عمل نیستید."
VOTE_TIME_ALERT = "الان زمان رأی‌گیری پایان روز نیست."


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
        """(text, reply_markup) for every send_message / edit_message_text."""
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


class Nam10Day1RepresentativeTest(unittest.IsolatedAsyncioTestCase):
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
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

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
                full_name=SYN_RAW_NAME,
                username=None,
                role=None,
                is_alive=True,
                seat=10,
            ),
        )
        assert err is None, err
        # Roles are dealt so the Mafia Boss exists for the continued
        # Day-1 betrayal workflow (from the afternoon-nap ack onward).
        from bot.nam10.nmnd_narrator import Role as _Role

        team_map = {
            REAL_UIDS[0]: _Role.MAFIA_BOSS,
            REAL_UIDS[1]: _Role.MAFIA,
            REAL_UIDS[2]: _Role.MAFIA,
        }
        for uid, pl in game.players.items():
            pl.role = team_map.get(uid, _Role.CITIZEN)
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
        """Real production Day-1 funnel (send_no_host_day_vote_prompt)."""
        from bot.nam10.no_host_day_vote import send_no_host_day_vote_prompt

        await send_no_host_day_vote_prompt(self.bot, self.game)

    async def _press(self, actor_uid, act, as_uid, tid=0):
        from bot.observer_delivery import PlayerMirrorCb

        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        data = PlayerMirrorCb(
            code=self.game.room_code, act=act, as_uid=as_uid, tid=tid
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
            update_id=3_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    async def _to_pick(self):
        """Run the funnel and open the pick panel as the assistant."""
        await self._funnel()
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)

    def _buttons(self, mark: str):
        """Buttons of the LAST rendered panel whose text contains ``mark``."""
        from aiogram.types import InlineKeyboardButton

        picked = None
        for text, kb in self.bot.kb_segments():
            if mark in text and kb is not None:
                picked = kb
        if picked is None:
            return []
        buttons = []
        for row in picked.inline_keyboard:
            for btn in row:
                if isinstance(btn, InlineKeyboardButton):
                    buttons.append(btn)
        return buttons

    def _pmr_acts(self, mark: str):
        from bot.observer_delivery import PlayerMirrorCb

        out = []
        for btn in self._buttons(mark):
            data = btn.callback_data or ""
            if data.startswith("pmr:"):
                out.append(PlayerMirrorCb.unpack(data))
        return out

    def _pick_buttons(self):
        return self._pmr_acts(PICK_MARK)

    def _audit_events(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    # ------------------------------------------------------------------
    async def test_01_day1_routes_to_representative_intro_not_defense(self):
        game = self._fork_room()
        await self._funnel()
        from bot.nam10.day1_representative import NAM10_DAY1_STAGE_REP_INTRO

        self.assertEqual(game.nam10_day1_stage, NAM10_DAY1_STAGE_REP_INTRO)
        self.assertTrue(game.nam10_day1_vote_prompt_sent)
        self.assertFalse(game.nam10_day1_defense_active)
        self.assertIn(INTRO_MARK, "\n".join(self.bot.texts()))
        self.assertNotIn(DEFENSE_PICK_MARK, "\n".join(self.bot.texts()))
        before = len(self.bot.calls)
        await self._funnel()  # idempotent: prompt already consumed
        self.assertEqual(len(self.bot.calls), before)
        self.assertEqual(
            game.nam10_day1_stage,
            NAM10_DAY1_STAGE_REP_INTRO,
        )

    async def test_02_intro_panel_delivered_to_assistant_and_observer(self):
        self._fork_room()
        await self._funnel()
        assistant_sends = [
            t for chat, t in self.bot.sends() if chat == ASSIST_UID
        ]
        observer_sends = [t for chat, t in self.bot.sends() if chat == OBS_UID]
        self.assertTrue(any(INTRO_MARK in t for t in assistant_sends))
        self.assertTrue(any(INTRO_MARK in t for t in observer_sends))
        acts = [cb.act for cb in self._pmr_acts(INTRO_MARK)]
        self.assertIn("d1ri", acts)
        buttons = {b.text: b for b in self._buttons(INTRO_MARK)}
        kb_button = next(b for b in buttons.values() if b.callback_data.startswith("pmr:"))
        self.assertEqual(kb_button.style, "primary")

    async def test_03_pick_panel_ten_players_seats_red_no_role_leak(self):
        self._fork_room()
        await self._to_pick()
        from bot.nam10.day1_representative import NAM10_DAY1_STAGE_REP_PICK

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_REP_PICK)
        buttons = self._pick_buttons()
        toggles = [cb for cb in buttons if cb.act == "d1rt"]
        self.assertEqual(len(toggles), 10)
        label_texts = {
            b.text
            for b in self._buttons(PICK_MARK)
            if b.callback_data.startswith("pmr:")
        }
        # exactly ten player rows + OK row; all blue initially
        for b in self._buttons(PICK_MARK):
            if b.callback_data.startswith("pmr:") and ". " in b.text:
                self.assertEqual(b.style, "primary")
                self.assertTrue(b.text.startswith("☐"))
            elif b.callback_data.startswith("pmr:"):
                self.assertEqual((b.text, b.style), ("✅ OK", "success"))
        # seat numbers rendered as Persian digits
        seat_texts = [t for t in label_texts if "۱." in t or "۵." in t or "۱۰." in t]
        self.assertTrue(seat_texts)
        # synthetic role suffix hidden, real names untouched
        self.assertFalse(any(SYN_RAW_NAME in t for t in label_texts))
        self.assertTrue(any("امیر" in t for t in label_texts))
        self.assertTrue(any("بازیکن 3" in t for t in label_texts))

    async def test_04_toggle_selection_and_back(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        self.assertEqual(self.game.nam10_day1_rep_pending, [901])
        green = [
            b
            for b in self._buttons(PICK_MARK)
            if b.callback_data.startswith("pmr:") and b.style == "danger"
        ]
        self.assertEqual(len(green), 1)
        toggled = [cb for cb in self._pmr_acts(PICK_MARK) if cb.act == "d1rt" and cb.tid == 901]
        self.assertEqual(len(toggled), 1)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        self.assertEqual(self.game.nam10_day1_rep_pending, [])
        greens = [
            b
            for b in self._buttons(PICK_MARK)
            if b.callback_data.startswith("pmr:") and b.style == "danger"
        ]
        self.assertEqual(len(greens), 0)

    async def test_05_two_selected_third_press_rejected(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=902)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=903)
        self.assertTrue(
            any(a and MAX_TWO_ALERT in a for a in self.bot.acks()),
            self.bot.acks(),
        )
        self.assertEqual(self.game.nam10_day1_rep_pending, [901, 902])
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=905)
        self.assertEqual(self.game.nam10_day1_rep_pending, [901, 902])
        green = [
            b
            for b in self._buttons(PICK_MARK)
            if b.callback_data.startswith("pmr:") and b.style == "danger"
        ]
        self.assertEqual(len(green), 2)

    async def test_06_ok_rejected_with_zero_and_one_selection(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        self.assertTrue(any(a and NEED_TWO_ALERT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nam10_day1_rep_uids, [])
        from bot.nam10.day1_representative import NAM10_DAY1_STAGE_REP_PICK

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_REP_PICK)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        self.assertTrue(any(a and NEED_TWO_ALERT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nam10_day1_rep_uids, [])
        self.assertEqual(self.game.nam10_day1_rep_pending, [901])

    async def test_07_ok_with_two_stores_uids_in_order_and_enters_nap(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=904)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=902)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        from bot.nam10.day1_representative import NAM10_DAY1_STAGE_AFTERNOON_NAP

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_AFTERNOON_NAP)
        self.assertEqual(self.game.nam10_day1_rep_uids, [904, 902])
        self.assertEqual(self.game.nam10_day1_rep_pending, [])
        self.assertTrue(any(NAP_MARK in t for t in self.bot.texts()))
        nap_buttons = [
            b
            for b in self._buttons(NAP_MARK)
            if b.callback_data.startswith("pmr:")
        ]
        self.assertEqual(len(nap_buttons), 1)
        self.assertEqual(nap_buttons[0].text, "✅ خواب نیمروزی انجام شد")
        self.assertEqual(self._pmr_acts(NAP_MARK)[0].act, "d1na")
        # no defense / Mafia side effects started
        self.assertFalse(self.game.nam10_day1_defense_active)
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

        self.assertEqual(self.game.nmnd_narrator_step, DAY_DISCUSS)

    async def test_08_selection_order_preserved_on_replace(self):
        self._fork_room()
        await self._to_pick()
        for tid in (904, 902):
            await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=tid)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=904)  # deselect
        self.assertEqual(self.game.nam10_day1_rep_pending, [902])
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=906)
        self.assertEqual(self.game.nam10_day1_rep_pending, [902, 906])
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        self.assertEqual(self.game.nam10_day1_rep_uids, [902, 906])

    async def test_09_observer_shares_selection_and_can_confirm(self):
        self._fork_room()
        await self._to_pick()
        from bot.nam10.day1_representative import (
            NAM10_DAY1_STAGE_AFTERNOON_NAP,
            nam10_day1_rep_pick_ui_key,
        )

        # Observer acts on the assistant panel through its mirror copy.
        await self._press(OBS_UID, "d1rt", ASSIST_UID, tid=903)
        self.assertEqual(self.game.nam10_day1_rep_pending, [903])
        self.assertIn(
            nam10_day1_rep_pick_ui_key(self.game, ASSIST_UID),
            self.game.mirror_prompt_messages,
        )
        await self._press(OBS_UID, "d1rt", ASSIST_UID, tid=909)
        self.assertEqual(self.game.nam10_day1_rep_pending, [903, 909])
        await self._press(OBS_UID, "d1ro", ASSIST_UID)
        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_AFTERNOON_NAP)
        self.assertEqual(self.game.nam10_day1_rep_uids, [903, 909])

    async def test_10_unauthorized_press_rejected(self):
        self._fork_room()
        await self._to_pick()
        before = list(self.game.nam10_day1_rep_pending)
        await self._press(901, "d1rt", ASSIST_UID, tid=901)
        self.assertTrue(any(a and FORBIDDEN_ALERT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nam10_day1_rep_pending, before)
        await self._press(902, "d1ro", ASSIST_UID)
        self.assertTrue(any(a and FORBIDDEN_ALERT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nam10_day1_rep_uids, [])
        # Observer must NOT be authorized before its panel-stage gates pass
        # either (here it acts outside the intro stage).
        await self._press(OBS_UID, "d1ri", ASSIST_UID)
        self.assertEqual(
            self.game.nam10_day1_stage, "day1_representative_pick"
        )

    async def test_11_stale_presses_after_confirm_rejected(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=907)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        uids = list(self.game.nam10_day1_rep_uids)
        n_calls = len(self.bot.calls)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()))
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=905)
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)
        self.assertEqual(self.game.nam10_day1_rep_uids, uids)
        self.assertEqual(len(self.bot.calls), n_calls + 3)  # three stale acks
        self.assertEqual(self.game.nam10_day1_rep_pending, [])

    async def test_12_nap_ack_opens_betrayal_collection(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=908)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(OBS_UID, "d1na", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT
        from bot.nam10.day1_representative import nam10_day1_nap_ui_key

        # The old waiting boundary was replaced: Stage A starts at once.
        self.assertEqual(
            self.game.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT
        )
        self.assertTrue(self.game.nam10_day1_nap_acked)
        self.assertTrue(any(NAP_ACK_MARK in t for t in self.bot.texts()))
        nap_key = nam10_day1_nap_ui_key(self.game, ASSIST_UID)
        entry = self.game.mirror_prompt_messages[nap_key]
        self.assertIn("player", entry)
        if self.game.observer_user_id is not None:
            self.assertIn("observer", entry)
        reps = set(self.game.nam10_day1_rep_uids)
        # Waiting panels for every alive non-Boss player, Boss excluded.
        wait_players = set()
        for text, kb in self.bot.kb_segments():
            if "رأی خیانت گروه مافیا" not in text or kb is None:
                continue
            from aiogram.types import InlineKeyboardButton as _Btn

            for row in kb.inline_keyboard:
                for btn in row:
                    if (
                        isinstance(btn, _Btn)
                        and (btn.callback_data or "").startswith("pmr:")
                    ):
                        from bot.observer_delivery import (
                            PlayerMirrorCb as _PMC,
                        )

                        cb = _PMC.unpack(btn.callback_data)
                        if cb.act == "d1bw":
                            wait_players.add(cb.as_uid)
        expected_wait = {
            u
            for u, p in self.game.players.items()
            if p.is_alive and u != REAL_UIDS[0]
        }
        self.assertEqual(wait_players, expected_wait)
        self.assertNotIn(REAL_UIDS[0], wait_players)
        # Mafia Boss private panel: per-seat add/subtract options.
        boss_acts = set()
        for text, kb in self.bot.kb_segments():
            if "مرحله ثبت رأی خیانت" not in text or kb is None:
                continue
            from aiogram.types import InlineKeyboardButton as _Btn

            for row in kb.inline_keyboard:
                for btn in row:
                    if (
                        isinstance(btn, _Btn)
                        and (btn.callback_data or "").startswith("pmr:")
                    ):
                        from bot.observer_delivery import (
                            PlayerMirrorCb as _PMC,
                        )

                        cb = _PMC.unpack(btn.callback_data)
                        if cb.act in ("d1ba", "d1bs"):
                            boss_acts.add((cb.act, cb.tid))
        # Night-v2 correction: the Boss may never influence their own
        # representative seat — its two buttons are omitted entirely.
        self.assertEqual(
            boss_acts,
            {
                (act, uid)
                for uid in (min(reps), max(reps))
                for act in ("d1ba", "d1bs")
                if uid != REAL_UIDS[0]
            },
        )
        # duplicate nap press is stale
        n_calls = len(self.bot.calls)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)
        self.assertTrue(any(a and STALE_ALERT in a for a in self.bot.acks()))
        self.assertEqual(len(self.bot.calls), n_calls + 1)

    async def test_13_waiting_state_blocks_legacy_day1_defense(self):
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=908)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)
        self.assertFalse(self.game.nam10_day1_defense_active)
        from bot.nam10.no_host_day_vote import nam10_end_day_vote_cb_allowed

        self.assertFalse(nam10_end_day_vote_cb_allowed(self.game))
        step_before = self.game.nmnd_narrator_step
        nights_before = self.game.nmnd_narrator_night_count
        await self._press(ASSIST_UID, "d1_vote", ASSIST_UID)
        self.assertTrue(any(a and VOTE_TIME_ALERT in a for a in self.bot.acks()))
        await self._press(ASSIST_UID, "d1_skip", ASSIST_UID)
        self.assertTrue(any(a and VOTE_TIME_ALERT in a for a in self.bot.acks()))
        self.assertEqual(self.game.nmnd_narrator_step, step_before)
        self.assertEqual(self.game.nmnd_narrator_night_count, nights_before)
        self.assertTrue(all(p.is_alive for p in self.game.players.values()))
        self.assertFalse(self.game.nam10_day1_defense_active)

    async def test_14_snapshot_roundtrip_retains_stage_and_uids(self):
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict

        # Mid-flow: pick panel open with an in-progress selection order.
        self._fork_room()
        await self._to_pick()
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=905)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=902)
        snapshot = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(snapshot)
        self.assertEqual(
            restored.nam10_day1_stage, "day1_representative_pick"
        )
        self.assertEqual(restored.nam10_day1_rep_pending, [905, 902])

        # Final flow state: confirmed representatives + active Stage A.
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)
        snapshot = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(snapshot)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_BETRAYAL_COLLECT

        self.assertEqual(
            restored.nam10_day1_stage, NAM10_DAY1_STAGE_BETRAYAL_COLLECT
        )
        self.assertEqual(restored.nam10_day1_rep_uids, [905, 902])
        self.assertTrue(restored.nam10_day1_nap_acked)
        self.assertIsNone(restored.nam10_day1_betrayal_op)
        self.assertEqual(
            restored.nam10_day1_betrayal_waiting_confirmed_uids, []
        )
        self.assertFalse(restored.nam10_day1_betrayal_revealed)

    async def test_15_existing_rooms_not_migrated_backward(self):
        # (a) A room whose Day-1 defense panel was already presented keeps
        # its state; the funnel returns early without rep panels.
        game = self._fork_room()
        game.nam10_day1_vote_prompt_sent = True
        game.nam10_day1_vote_resolved = True
        game.nam10_day1_defense_active = True
        game.nam10_day1_defense_phase = "pick"
        await self._funnel()
        self.assertIsNone(game.nam10_day1_stage)
        self.assertFalse(any(INTRO_MARK in t for t in self.bot.texts()))

        # (b) A room already past Day 1 (day 2+) keeps the legacy flow.
        from bot.nam10.no_host_day_vote import (
            reset_no_host_day_vote_prompt_state,
        )
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

        game2 = self._fork_room()
        reset_no_host_day_vote_prompt_state(game2)
        game2.nmnd_narrator_host_day = 2
        game2.nmnd_narrator_step = DAY_DISCUSS
        await self._funnel()
        self.assertIsNone(game2.nam10_day1_stage)
        self.assertTrue(game2.nam10_day1_defense_active)
        self.assertEqual(game2.nam10_day1_defense_phase, "pick")
        self.assertTrue(any(DEFENSE_PICK_MARK in t for t in self.bot.texts()))
        self.assertNotIn(INTRO_MARK, "\n".join(self.bot.texts()))

    async def test_16_bazpors_and_classic_day1_unchanged(self):
        # Bazpors no-host Day-1: legacy defense flow, no rep stage fields.
        from bot.models import Phase, Player

        game = self.manager.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for i in range(1, 13):
            err = self.manager.add_player(
                game,
                Player(
                    user_id=700 + i,
                    full_name=f"بازپرس {i}",
                    username=None,
                    role=None,
                    is_alive=True,
                    seat=i,
                ),
            )
            assert err is None, err
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.no_host_assistant_narrator_active = True
        game.no_host_intro_night_started = True
        game.bazpors_narrator_host_day = 1
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        self.game = game
        from bot.no_host_day_vote import send_no_host_day_vote_prompt

        await send_no_host_day_vote_prompt(self.bot, game)
        self.assertTrue(game.no_host_day1_defense_active)
        self.assertTrue(game.no_host_day1_vote_resolved)
        self.assertIsNone(game.nam10_day1_stage)
        self.assertNotIn(INTRO_MARK, "\n".join(self.bot.texts()))
        self.assertTrue(any(DEFENSE_PICK_MARK in t for t in self.bot.texts()))

        # A 'd1ro' press aimed at the Bazpors room must not touch it.
        from bot.observer_delivery import PlayerMirrorCb

        actor = User(id=901, is_bot=False, first_name="U901")
        data = PlayerMirrorCb(
            code=game.room_code, act="d1ro", as_uid=ASSIST_UID
        ).pack()
        cq = CallbackQuery(
            id="cq-bz",
            from_user=actor,
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=778,
                date=datetime.now(timezone.utc),
                chat=Chat(id=901, type=ChatType.PRIVATE),
                from_user=actor,
            ),
        )
        update = Update(
            update_id=3_100_000, callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)
        self.assertTrue(game.no_host_day1_defense_active)
        self.assertIsNone(game.nam10_day1_stage)

        # Classic Namayande (11+ / classic host mode) must not be treated as
        # a fork room and never reaches the Day-1 rep workflow.
        from bot.room_mode import is_namayande10_no_host_room

        game2 = self.manager.create_game(
            host_id=1, scenario_name="namayande", max_players=11
        )
        assert game2 is not None
        game2.roles_dealt = True
        game2.phase = Phase.MANUAL
        game2.bot_assistant_user_id = ASSIST_UID
        self.game = game2
        self.assertFalse(is_namayande10_no_host_room(game2))
        await self._funnel()
        self.assertIsNone(game2.nam10_day1_stage)
        self.assertFalse(game2.nam10_day1_defense_active)
        self.assertFalse(
            any(INTRO_MARK in t for t in self.bot.texts()[-3:])
        )

    async def test_17_synthetic_suffix_hidden_only_in_this_ui(self):
        self._fork_room()
        await self._to_pick()
        label_texts = [
            b.text
            for b in self._buttons(PICK_MARK)
            if b.callback_data.startswith("pmr:")
        ]
        self.assertFalse(any(SYN_RAW_NAME in t for t in label_texts))
        self.assertTrue(any(t.startswith("☐ ۱۰.") for t in label_texts))
        # stored player name is untouched
        stored = self.game.players[SYN_UID].full_name
        self.assertEqual(stored, SYN_RAW_NAME)

    async def test_18_audit_events_and_room_code_isolation(self):
        self._fork_room()
        await self._funnel()
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=901)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=908)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)
        events = self._audit_events()
        names = {e.get("event") for e in events}
        self.assertIn("no_host.day1_representative_intro_started", names)
        self.assertIn("no_host.day1_representative_pick_opened", names)
        self.assertIn("no_host.day1_representative_toggled", names)
        confirmed = [
            e
            for e in events
            if e.get("event") == "no_host.day1_representative_confirmed"
        ]
        self.assertEqual(confirmed[0].get("rep_uids"), [901, 908])
        self.assertIn("no_host.day1_afternoon_nap_acked", names)
        self.assertIn("no_host.day1_betrayal_collection_started", names)
        # callback_data of every rep button carries the current room code
        codes = {
            cb.code
            for cb in self._pick_buttons()
        }
        codes.add(self._pmr_acts(NAP_MARK)[0].code)
        self.assertEqual(codes, {self.game.room_code})


if __name__ == "__main__":
    unittest.main()
