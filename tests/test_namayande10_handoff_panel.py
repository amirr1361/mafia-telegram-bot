"""Namayande-10 fork: handoff-panel delivery, authorization and lifecycle.

Live defect (Room 42, Namayande-10 no-host): at the end of Day 1 the handoff
offer ("🔄 انتقال گردانندگی (خودکار مستقل)") was delivered to the assistant
and mirrored to the registered observer. After one decision was recorded,
the room switched to ``nmnd_host_mode == "semi_auto"`` and no longer matched
``is_namayande10_no_host_room``, so a stale press on the leftover counterpart
panel fell into the shared Bazpors narrator handler and answered

    «فقط کمک‌کنندهٔ ربات یا ناظر (در حالت بدون گرداننده) می‌تواند
    این دکمه را بزند.»

even to the registered observer. The counterpart panel was also never
closed, and the semi-auto room was stuck when the transferred host was a
synthetic/unreachable seat.

Fix (fork only; Bazpors untouched):
- ``is_namayande10_semi_auto_room`` routes semi-auto Namayande-10 rooms to
  the fork narrator handler;
- fork semi-auto authorization covers the bot-assistant and the registered
  observer;
- a recorded handoff decision closes both panels and stale presses get a
  clean "already recorded" answer;
- the observer mirror stays on after the fork handoff.

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
from unittest.mock import MagicMock, patch

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

ASSIST_UID = 80011
OBS_UID = 80012

OFFER_TITLE = "🔄 <b>انتقال گردانندگی (خودکار مستقل)</b>"
MIRROR_PREFIX = "👁 <i>ناظر"
REJECT_TEXT = "فقط کمک‌کننده ربات یا ناظر"
STALE_TEXT = "انتقال گردانندگی قبلاً ثبت شده است."
OK_TEXT = "ثبت شد."


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

            chat_id = kwargs.get("chat_id", args[0] if args else None)
            m = SimpleNamespace(
                message_id=len(self.calls) + 10_000,
                chat=SimpleNamespace(id=chat_id),
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

    def deletes(self):
        out = []
        for c in self.calls:
            if type(c).__name__ == "DeleteMessage":
                out.append(
                    (getattr(c, "chat_id", None), getattr(c, "message_id", None))
                )
            elif getattr(c, "_cls", None) == "delete_message":
                args = getattr(c, "_rec_args", ())
                kw = getattr(c, "_rec_kwargs", {}) or {}
                out.append(
                    (
                        kw.get("chat_id", args[0] if args else None),
                        kw.get("message_id", args[1] if len(args) > 1 else None),
                    )
                )
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


class Nam10HandoffPanelTest(unittest.IsolatedAsyncioTestCase):
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
        import bot.handlers.host_panel as host_panel_mod
        import bot.handlers.lobby as lobby_mod
        import bot.handlers.no_host_player as nhp_mod
        import bot.main as main_mod
        import bot.nam10.dayflow as dayflow_mod
        import bot.nam10.nmnd_narrator_cb as nmnd_cb_mod
        import bot.nam10.no_host_elim_report as elim_mod
        import bot.nam10.player_mirror as mirror_mod
        import bot.post_game_flow as pgf_mod

        self._mgr_patches = [
            patch.object(_app_state, "manager", self.manager),
            patch.object(main_mod, "manager", self.manager),
            patch.object(lobby_mod, "manager", self.manager),
            patch.object(nhp_mod, "manager", self.manager),
            patch.object(host_panel_mod, "manager", self.manager),
            patch.object(pgf_mod, "manager", self.manager),
        ]
        for mod in (nmnd_cb_mod, dayflow_mod, elim_mod, mirror_mod):
            if hasattr(mod, "manager"):
                self._mgr_patches.append(
                    patch.object(mod, "manager", self.manager)
                )
        # Dispatch-path modules bind theGameManager singleton at import
        # time (e.g. bot.handlers.narrator_cb) - sweep any live module that
        # still points at the original instance.
        from bot.game import GameManager as _GMc

        for name, mod in list(sys.modules.items()):
            m = getattr(mod, "manager", None)
            if isinstance(m, _GMc) and m is not self.manager:
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
    async def _fork_room_post_day1_elim(self, *,
                                        observer=True,
                                        assistant_picked=True):
        """Fork no-host room, Day 1 elim already applied, Day-1 handoff gate."""
        from bot.game_audit_log import init_audit_log
        from bot.models import Phase, Player
        from bot.nam10.engine import is_mafia_team
        from bot.nam10.lobby import roles_for_count

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        if observer:
            game.observer_user_id = OBS_UID
            game.observer_prompt_status = "registered"
        roster = roles_for_count(10)
        self.assertEqual(len(roster), 10)
        for i, role in enumerate(roster, start=1):
            err = self.manager.add_player(
                game,
                Player(
                    user_id=900 + i,
                    full_name=f"بازیکن {i}",
                    username=None,
                    role=role,
                    is_alive=True,
                    seat=i,
                ),
            )
            assert err is None, err
        game.mafia_ids = {
            uid
            for uid, p in game.players.items()
            if p.role and is_mafia_team(p.role)
        }
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_night_count = 0
        game.nmnd_narrator_step = "day_discuss"
        init_audit_log(game)

        if assistant_picked:
            from bot.nam10.dayflow import finalize_no_host_bot_assistant

            await finalize_no_host_bot_assistant(self.bot, game, ASSIST_UID)
        self.game = game
        return game

    async def _open_day1_handoff_offer(self, uid=903):
        """Production flow: mark the Day-1 elimination, open the gate."""
        game = self.game
        game.players[uid].is_alive = False
        game.nmnd_narrator_step = "confirm_day_elim"
        from bot.nam10.no_host_handoff import offer_handoff_day1_after_elim

        self.assertTrue(offer_handoff_day1_after_elim(game))
        self.assertEqual(game.nmnd_narrator_step, "nam10_handoff_offer")
        from bot.nam10.nmnd_narrator import push_host_step

        await push_host_step(self.bot, game, self.manager)
        return game

    async def _press(self, actor_uid, act, tid=0):
        from bot.nam10.nmnd_narrator import BazporsNarrCb

        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        data = BazporsNarrCb(
            code=self.game.room_code, act=act, tid=tid
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
            update_id=2_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    def _sends_to(self, chat):
        return [s for s in self.bot.sends() if s[0] == chat]

    def _last_audit_event(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        return lines[-1], lines

    # ------------------------------------------------------------------
    async def test_01_offer_panels_delivered_to_assistant_and_observer(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()

        asst = self._sends_to(ASSIST_UID)
        obs = self._sends_to(OBS_UID)
        self.assertTrue(
            any(OFFER_TITLE in (t or "") for t in [s[1] for s in asst]),
            "assistant must receive its own handoff offer panel",
        )
        self.assertTrue(
            any(
                MIRROR_PREFIX in (t or "") and OFFER_TITLE in (t or "")
                for t in [s[1] for s in obs]
            ),
            "registered observer must receive the mirrored handoff panel",
        )
        self.assertEqual(
            self.game.nmnd_assistant_panel_chat_id, ASSIST_UID
        )
        self.assertIsNotNone(self.game.nmnd_assistant_panel_message_id)
        self.assertEqual(
            self.game.nmnd_observer_narrator_mirror_chat_id, OBS_UID
        )
        self.assertIsNotNone(self.game.nmnd_observer_narrator_mirror_message_id)

    async def test_02_observer_press_continue_with_assistant(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        pre_sends = list(self.bot.sends())

        await self._press(OBS_UID, "handoff_skip")
        self.assertIn(OK_TEXT, self.bot.acks(), "observer press must succeed")

        game = self.game
        self.assertIsNone(game.nam10_handoff_gate)
        self.assertEqual(game.nmnd_host_mode, "no_host")
        self.assertTrue(game.nam10_assistant_narrator_active)
        self.assertTrue(game.nam10_observer_only_narrator_mirror)
        # No transfer happened; the flow resumed into Night 1.
        self.assertEqual(game.nmnd_narrator_night_count, 1)
        self.assertNotEqual(game.nmnd_narrator_step, "nam10_handoff_offer")
        played = [s for s in self.bot.sends() if s[0] in game.players]
        self.assertTrue(played, "Night 1 participation panels must be sent")

        # Panel lifecycle: both stale copies are gone (no new offer panels).
        offer_sends_after = [
            s for s in self.bot.sends()[len(pre_sends):] if OFFER_TITLE in (s[1] or "")
        ]
        self.assertEqual(offer_sends_after, [])
        _, lines = self._last_audit_event()
        declined = [e for e in lines if e.get("event") == "no_host.handoff_declined"]
        self.assertTrue(
            declined,
            f"audit log must contain the declined event; events={[e.get('event') for e in lines]}",
        )
        self.assertEqual(declined[0].get("gate"), "day1_after_elim")

    async def test_03_panel_refs_cleared_and_counterpart_closed(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        old_asst = self.game.nmnd_assistant_panel_message_id
        old_obs = self.game.nmnd_observer_narrator_mirror_message_id
        self.assertIsNotNone(old_asst)
        self.assertIsNotNone(old_obs)

        await self._press(OBS_UID, "handoff_skip")

        game = self.game
        self.assertIsNone(game.nmnd_assistant_panel_message_id)
        self.assertIsNone(game.nmnd_assistant_panel_chat_id)
        # The skip path resumes Night 1: the night flow may re-mirror a fresh
        # panel, so the mirror ref must never keep pointing at the stale one.
        mirror_ref = (
            game.nmnd_observer_narrator_mirror_chat_id,
            game.nmnd_observer_narrator_mirror_message_id,
        )
        self.assertNotEqual(mirror_ref, (OBS_UID, old_obs))
        deleted_assistant = any(
            chat == ASSIST_UID and mid == old_asst
            for chat, mid in self.bot.deletes()
        )
        self.assertTrue(
            deleted_assistant,
            "the assistant's counterpart panel must be closed after the decision; "
            f"deletes={self.bot.deletes()}",
        )

    async def test_04_assistant_transfer_to_eliminated_player(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        pre_sends = self.bot.sends()
        offer_sends_before = sum(
            1 for s in pre_sends if OFFER_TITLE in (s[1] or "")
        )
        self.assertEqual(offer_sends_before, 2)

        await self._press(ASSIST_UID, "handoff_pick", tid=903)
        self.assertIn(OK_TEXT, self.bot.acks())

        game = self.game
        self.assertEqual(game.nmnd_host_mode, "semi_auto")
        self.assertEqual(game.host_id, 903)
        self.assertIsNone(game.nam10_handoff_gate)
        self.assertFalse(game.nam10_assistant_narrator_active)
        # Fork divergence (documented): the observer mirror stays ON so a
        # synthetic/unreachable transferred host keeps the game operable.
        self.assertTrue(game.nam10_observer_only_narrator_mirror)

        # Semi-auto panel push to the transferred host + observer mirror copy.
        self.assertTrue(
            any("منتقل شد" in (t or "") for t in [s[1] for s in self._sends_to(903)]),
            "transferred host must receive the handover notice",
        )
        obs_after = [
            s
            for s in self.bot.sends()[len(pre_sends):]
            if s[0] == OBS_UID and MIRROR_PREFIX in (s[1] or "")
        ]
        self.assertTrue(
            obs_after,
            "observer must keep receiving the semi-auto narrator mirror",
        )
        # No duplicated handoff offers after the transfer.
        offer_sends_total = sum(
            1 for s in self.bot.sends() if OFFER_TITLE in (s[1] or "")
        )
        self.assertEqual(offer_sends_total, 2)

        event, _ = self._last_audit_event()
        self.assertEqual(event.get("event"), "no_host.handoff_accepted")
        self.assertEqual(event.get("gate"), "day1_after_elim")
        self.assertEqual(event.get("from_mode"), "no_host")
        self.assertEqual(event.get("to_mode"), "semi_auto")
        self.assertEqual(event.get("new_host_uid"), 903)

    async def test_05_stale_press_after_transfer_friendly_not_shared_rejection(self):
        """THE live Room-42 regression: the observer presses the leftover
        «ادامه با کمک‌کننده ربات» button after the transfer was recorded.
        Must hit the FORK handler (semi-auto routing) and get the clean
        "already recorded" answer - never the shared Bazpors rejection."""
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        await self._press(ASSIST_UID, "handoff_pick", tid=903)
        self.assertEqual(self.game.nmnd_host_mode, "semi_auto")

        await self._press(OBS_UID, "handoff_skip")
        acks = self.bot.acks()
        self.assertIn(STALE_TEXT, acks)
        self.assertFalse(
            any(REJECT_TEXT in (a or "") for a in acks),
            f"stale press must never yield the shared Bazpors rejection; acks={acks}",
        )
        # Stale press must not mutate anything.
        self.assertEqual(self.game.nmnd_host_mode, "semi_auto")
        self.assertEqual(self.game.host_id, 903)

    async def test_06_stale_press_after_skip_also_friendly(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        await self._press(OBS_UID, "handoff_skip")
        self.assertEqual(self.game.nmnd_host_mode, "no_host")

        await self._press(ASSIST_UID, "handoff_skip")
        self.assertIn(STALE_TEXT, self.bot.acks())
        # No conflicting late transfer decision from the stale panel.
        self.assertEqual(self.game.nmnd_host_mode, "no_host")

    async def test_07_unauthorized_player_press_rejected(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        live_uid = 905
        self.assertTrue(self.game.players[live_uid].is_alive)

        await self._press(live_uid, "handoff_skip")
        acks = self.bot.acks()
        self.assertTrue(
            any(REJECT_TEXT in (a or "") for a in acks),
            "a live player must be rejected with the fork authorization message",
        )
        self.assertNotIn(OK_TEXT, acks)
        self.assertEqual(self.game.nmnd_narrator_step, "nam10_handoff_offer")
        self.assertIsNotNone(self.game.nam10_handoff_gate)

    async def test_08_semi_auto_operator_authorization(self):
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        await self._press(ASSIST_UID, "handoff_pick", tid=903)

        from bot.nam10.nmnd_narrator import narrator_callback_user_may_act

        self.assertTrue(narrator_callback_user_may_act(self.game, 903))
        self.assertTrue(narrator_callback_user_may_act(self.game, ASSIST_UID))
        self.assertTrue(narrator_callback_user_may_act(self.game, OBS_UID))
        self.assertFalse(narrator_callback_user_may_act(self.game, 906))

    async def test_09_cross_scenario_isolation(self):
        from bot.room_mode import (
            is_namayande10_no_host_room,
            is_namayande10_semi_auto_room,
        )

        # Fresh fork transfers only the fork room.
        await self._fork_room_post_day1_elim()
        await self._open_day1_handoff_offer()
        self.assertTrue(is_namayande10_no_host_room(self.game))
        self.assertFalse(is_namayande10_semi_auto_room(self.game))
        await self._press(ASSIST_UID, "handoff_pick", tid=903)
        self.assertTrue(is_namayande10_semi_auto_room(self.game))
        self.assertFalse(is_namayande10_no_host_room(self.game))

        # A Bazpors semi-auto room is never routed to the fork.
        baz = self.manager.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert baz is not None
        self.assertFalse(is_namayande10_semi_auto_room(baz))

        # A classic 11+ Namayande room without fence state is never routed.
        classic = self.manager.create_game(
            host_id=1, scenario_name="namayande", max_players=11
        )
        assert classic is not None
        self.assertFalse(is_namayande10_semi_auto_room(classic))
        self.assertFalse(is_namayande10_no_host_room(classic))


if __name__ == "__main__":
    unittest.main()
