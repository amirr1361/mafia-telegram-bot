"""Bazpors no-host: generalized night-readiness reconciliation.

Mirror of the Namayande-10 fork suite (``tests/test_namayande10_night_reconcile.py``)
covering the shared defect family on the Bazpors side:

- `_after_interrog_commit` early-returned on the skip-ack branch without
  running the readiness finish gate (stalled parallel collection);
- the doctor's pick is cancelled by the rules on a Yakuza night, but the
  panel stayed actionable and no auto-disposition existed;
- converted players kept obsolete citizen/Ruintan ack panels;
- pending-list panel staleness.

Bazpors uses the shared ``no_host_*`` namespace and the independent Bazpors
night modules; the fork's ``nam10_*`` state is never touched.

Isolated temporary storage only; never touches production rooms.
"""

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

DOCTOR_NOTE_MARK = "پزشک امشب انتخاب ندارد"
CONVERT_NOTE_MARK = "نقش شما به‌تازگی تغییر کرد"
DOCTOR_BLOCK_ANSWER = "امشب پزشک به‌دلیل عملیات مافیا (یاکوزایی) انتخاب ندارد."
FINISH_EVENT = "no_host.parallel_night_collect_finished"
AUTO_RESOLVE_EVENT = "no_host.night_ready_auto_resolve"
REFRESH_EVENT = "no_host.night_ready_panel_refreshed"


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


class BazporsNightReconcileTest(unittest.IsolatedAsyncioTestCase):
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

    def tearDown(self):
        for p in reversed(self._mgr_patches):
            p.stop()
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    def _no_host_collect_room(self):
        """Bazpors no-host room inside the Night-2 parallel-collect window."""
        from bot.game_audit_log import init_audit_log
        from bot.models import Game, Phase, Player, Role

        gm = self.manager
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        players = [
            (10, "رییس-رییس مافیا", Role.MAFIA_BOSS),
            (11, "مافیایی-مافیا", Role.MAFIA_BASIC),
            (12, "دکتر-پزشک", Role.DOCTOR),
            (13, "شیاد-شیاد", Role.SHIAD),
            (14, "کاراگاه-کاراگاه", Role.DETECTIVE),
            (15, "رویین-رویینتن", Role.RUINTAN),
            (16, "شهروند-شهروند", Role.CITIZEN),
            (17, "بازپرس-بازپرس", Role.INTERROGATOR),
        ]
        for uid, name, role in players:
            err = gm.add_player(
                game, Player(uid, name, None, role, seat=uid % 100, is_alive=True)
            )
            assert err is None, err
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = 99
        game.no_host_assistant_narrator_active = True
        game.no_host_night_parallel_collect_active = True
        from bot.bazpors_narrator import NIGHT_START

        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 2
        game.no_host_night_entry_dispatched_night = 2
        init_audit_log(game)
        self.game = game
        return game

    def _confirm_all_except_interrog(self, game):
        from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT
        from bot.no_host_night_ready import _alive_citizen_uids

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

    def _audit_events(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

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
            update_id=4_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    # ------------------------------------------------------------------
    async def test_01_skip_ack_commit_finishes_parallel_night(self):
        game = self._no_host_collect_room()
        self._confirm_all_except_interrog(game)
        int_uid = 17
        game.no_host_interrog_ui_phase = "skip_ack"
        game.bazpors_interrog_once_done = True
        game.no_host_interrog_dm_signature = "2:interrog:night_entry"

        from bot.no_host_night_ready import (
            all_no_host_parallel_night_ready,
            maybe_finish_no_host_parallel_night,
            pending_no_host_night_actor_labels,
        )

        self.assertFalse(all_no_host_parallel_night_ready(game))
        self.assertEqual(pending_no_host_night_actor_labels(game), ["بازپرس"])
        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished)
        self.assertTrue(game.no_host_night_parallel_collect_active)

        await self._press(int_uid, "niisk", int_uid)
        self.assertIn("ثبت شد.", self.bot.acks())
        self.assertFalse(
            game.no_host_night_parallel_collect_active,
            "skip-ack commit must trigger the readiness finish gate",
        )
        self.assertIn(FINISH_EVENT, [e.get("event") for e in self._audit_events()])

    async def test_02_doctor_yaku_block_note_and_stale_pick_rejected(self):
        from bot.roles.doctor import blocked_this_night, doctor_night_state

        game = self._no_host_collect_room()
        self._confirm_all_except_interrog(game)
        game.no_host_doctor_pick_confirmed = False
        doc_uid = 12

        from bot.no_host_doctor_night import start_no_host_doctor_night_flow

        await start_no_host_doctor_night_flow(
            self.bot, game, self.manager, at_night_entry=True
        )
        self.assertTrue([s for s in self.bot.sends() if s[0] == doc_uid])

        civ_uid = 16
        game.bazpors_yaku_night_success = True
        game.bazpors_yaku_night_civilian_uid = civ_uid
        self.assertTrue(blocked_this_night(game))

        from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished, "the interrogator is still genuinely pending")
        self.assertIn("doctor_op_block#2", game.no_host_night_ready_disposed)
        self.assertEqual(
            game.no_host_night_ready_disposed["doctor_op_block#2"],
            "action_cancelled_by_rule",
        )
        self.assertTrue(
            any(DOCTOR_NOTE_MARK in t for t in self.bot.texts()),
            f"doctor note must be delivered; texts={self.bot.texts()}",
        )
        self.assertEqual(doctor_night_state(game).get_save_uids(), [])

        await self._press(doc_uid, "dkt", doc_uid, tid=10)
        self.assertIn(
            DOCTOR_BLOCK_ANSWER,
            [a for a in self.bot.acks() if a],
            f"stale pick must be rejected; acks={self.bot.acks()}",
        )
        self.assertEqual(doctor_night_state(game).get_save_uids(), [])

    async def test_03_citizen_conversion_closes_ack_and_auto_ready(self):
        from bot.models import Role

        game = self._no_host_collect_room()
        # Night-entry deliveries may reset the per-night ack state, so the
        # citizen panel is delivered BEFORE the obligations are marked done.
        from bot.no_host_citizen_night import dispatch_no_host_citizen_night_panel

        await dispatch_no_host_citizen_night_panel(self.bot, game, self.manager)
        self._confirm_all_except_interrog(game)
        game.no_host_doctor_pick_confirmed = False
        int_uid = 17
        game.no_host_interrog_ui_phase = "skip_ack"
        game.bazpors_interrog_once_done = True
        game.no_host_interrog_dm_signature = "2:interrog:night_entry"

        civ_uid = 16
        game.no_host_citizen_night_confirmed_uids = [
            u for u in (game.no_host_citizen_night_confirmed_uids or []) if u != civ_uid
        ]

        # Yakuza conversion removes the citizen from the role pool.
        game.players[civ_uid].role = Role.MAFIA_BASIC
        game.bazpors_yaku_night_success = True
        game.bazpors_yaku_night_civilian_uid = civ_uid

        from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished, "the doctor + interrogator are still pending")
        self.assertNotIn(
            civ_uid, list(game.no_host_citizen_night_confirmed_uids or [])
        )
        self.assertIn("yaku_civ_ack#2", game.no_host_night_ready_disposed)
        self.assertEqual(
            game.no_host_night_ready_disposed["yaku_civ_ack#2"], "role_converted"
        )
        self.assertTrue(
            any(CONVERT_NOTE_MARK in t for t in self.bot.texts()),
            f"converted ack panel must be replaced; texts={self.bot.texts()}",
        )
        auto = [e for e in self._audit_events() if e.get("event") == AUTO_RESOLVE_EVENT]
        self.assertTrue(
            any(e.get("reason") == "role_converted" for e in auto),
            f"audit must record the role_converted disposition; auto={auto}",
        )

        await self._press(int_uid, "niisk", int_uid)
        self.assertIn("ثبت شد.", self.bot.acks())
        self.assertFalse(
            game.no_host_night_parallel_collect_active,
            "after dispositions + skip-ack commit the night closes",
        )

    async def test_04_fork_room_is_not_touched(self):
        """The Bazpors gate can never close or repair a fork room."""
        from bot.game_audit_log import init_audit_log

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        init_audit_log(game)
        from bot.no_host_night_reconcile import reconcile_no_host_night_readiness

        finished = await reconcile_no_host_night_readiness(
            self.bot, game, self.manager, reason="isolation"
        )
        self.assertFalse(
            finished,
            "the Bazpors collector must not see a Namayande-10 fork room",
        )
        self.assertEqual(game.no_host_night_ready_disposed, {})
        self.assertIsNone(game.no_host_night_ready_signature)
        self.assertFalse(game.no_host_night_parallel_collect_active)

    async def test_05_missing_panel_restored_and_refresh_idempotent(self):
        game = self._no_host_collect_room()
        self._confirm_all_except_interrog(game)
        game.no_host_doctor_pick_confirmed = False
        game.no_host_doctor_dm_signature = "2:doc:night_entry"
        # Yaku committed this night so the doctor is rule-blocked; the shiad
        # panel was never delivered although a shiad is alive and pending.
        game.bazpors_yaku_night_success = True
        game.bazpors_yaku_night_civilian_uid = 16
        game.no_host_shiad_pick_confirmed = False
        game.no_host_shiad_dm_signature = None
        game.no_host_interrog_ui_phase = "skip_ack"
        game.bazpors_interrog_once_done = True
        game.no_host_interrog_dm_signature = "2:interrog:night_entry"

        from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished, "Shiad must actually confirm, not be waived")
        self.assertTrue(game.no_host_night_parallel_collect_active)
        self.assertIsNotNone(
            game.no_host_shiad_dm_signature,
            "restore must deliver the missing mandatory panel",
        )
        self.assertTrue(game.no_host_shiad_flow_active)
        auto = [e for e in self._audit_events() if e.get("event") == AUTO_RESOLVE_EVENT]
        self.assertTrue(
            any(
                e.get("reason") == "missing_panel_restored" and e.get("role") == "SHIAD"
                for e in auto
            ),
            f"audit must record the restore; auto={auto}",
        )

        before = len(self.bot.calls)
        await maybe_finish_no_host_parallel_night(self.bot, game, self.manager)
        refreshes = [
            e for e in self._audit_events() if e.get("event") == REFRESH_EVENT
        ]
        self.assertEqual(
            len(refreshes), 1, f"pending panel must refresh exactly once: {refreshes}"
        )
        self.assertEqual(
            len(self.bot.calls), before, "no duplicate deliveries on repeat"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
