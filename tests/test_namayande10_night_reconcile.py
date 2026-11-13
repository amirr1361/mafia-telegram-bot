"""Namayande-10 fork: generalized night-readiness reconciliation.

Live defect (Room 9, Namayande-10 no-host, Night 2): a successful Yakuza
operation (NATO sacrificed, Ruintan converted to Mafia) left the parallel
night collection stalled. Evidence (snapshot + audit):

- The Interrogator's Night-2 panel was the once-per-game "skip ack" panel;
  its commit path (`_after_interrog_commit`) returned EARLY on the
  skip-ack branch and never ran the readiness finish gate -> the night
  never resolved.
- The doctor's panel survived although the rules void the doctor's pick on
  a Yakuza night (`void_night_pick`), so the doctor could still record a
  dead pick into a blocked night.
- The converted Ruintan kept its obsolete citizen/Ruintan ack panel, and
  the pending list panel went stale.

Fix (fork-side `bot/nam10/no_host_night_reconcile.py`, routed through
`maybe_finish_no_host_parallel_night`): generalized readiness
reconciliation — rule-blocked obligations auto-dispose with a machine
readable reason, converted players' obsolete ack panels close, missing
mandatory panels are restored, the pending panel refreshes, and the night
resolves only when the true readiness contract is satisfied.

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

ASSIST_UID = 80011

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
        """All sent/edited message texts (any method)."""
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


class Nam10NightReconcileTest(unittest.IsolatedAsyncioTestCase):
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
        # Dispatch-path modules bind the GameManager singleton at import
        # time - sweep any live module still pointing at the original.
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
    def _fork_collect_room(self):
        """Fork no-host room inside the Night-2 parallel-collect window."""
        from bot.game_audit_log import init_audit_log
        from bot.models import Phase, Player
        from bot.nam10.engine import is_mafia_team
        from bot.nam10.lobby import roles_for_count
        from bot.nam10.nmnd_narrator import NIGHT_START

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        roster = roles_for_count(10)
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
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nmnd_narrator_step = NIGHT_START
        game.nmnd_narrator_night_count = 2
        game.nam10_night_parallel_collect_active = True
        game.nam10_night_entry_dispatched_night = 2
        init_audit_log(game)
        self.game = game
        return game

    def _holder_uid(self, game, role):
        from bot.nam10.role_registry import find_alive_role_holder

        pl = find_alive_role_holder(game, role)
        assert pl is not None, f"no alive holder for {role}"
        return pl.user_id

    def _confirm_all_except_interrog(self, game):
        """Every non-interrogator night obligation completed (state only)."""
        from bot.nam10.no_host_mafia_night1 import MAFIA_ACTION_SHOT
        from bot.nam10.no_host_night_ready import _alive_citizen_uids

        game.nam10_citizen_night_confirmed_uids = list(_alive_citizen_uids(game))
        game.nam10_ruintan_night_confirmed = True
        game.nam10_night1_hunter_done = True
        game.nam10_mafia_night1_done = True
        game.nam10_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.nam10_mafia_shot_done = True
        game.nam10_shiad_pick_confirmed = True
        game.nam10_detective_pick_confirmed = True
        game.nam10_sniper_pick_confirmed = True
        game.nam10_doctor_pick_confirmed = True

    def _audit_events(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    async def _press(self, actor_uid, act, as_uid, tid=0):
        """Real dispatcher press through PlayerMirrorCb routing."""
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

    # ------------------------------------------------------------------
    async def test_01_skip_ack_commit_finished_room9_regression(self):
        """Room 9: the skip-ack interrogator commit must close the night."""
        from bot.nam10.nmnd_narrator import Role

        game = self._fork_collect_room()
        self._confirm_all_except_interrog(game)
        int_uid = self._holder_uid(game, Role.INTERROGATOR)
        game.nam10_interrog_ui_phase = "skip_ack"
        game.nmnd_interrog_once_done = True
        game.nam10_interrog_dm_signature = "2:interrog:night_entry"

        from bot.nam10.no_host_night_ready import (
            all_no_host_parallel_night_ready,
            maybe_finish_no_host_parallel_night,
            pending_no_host_night_actor_labels,
        )

        # Before the commit the night stays open (the interrogator is pending).
        self.assertFalse(all_no_host_parallel_night_ready(game))
        self.assertEqual(pending_no_host_night_actor_labels(game), ["راهنما"])
        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished)
        self.assertTrue(game.nam10_night_parallel_collect_active)

        # The REAL production press path for the skip-ack button. This is
        # the exact Room 9 press that previously short-circuited.
        await self._press(int_uid, "niisk", int_uid)

        self.assertIn("ثبت شد.", self.bot.acks())
        self.assertFalse(
            game.nam10_night_parallel_collect_active,
            "skip-ack commit must trigger the readiness finish gate",
        )
        events = [e.get("event") for e in self._audit_events()]
        self.assertIn(FINISH_EVENT, events)

    async def test_02_doctor_yaku_block_note_and_stale_pick_rejected(self):
        """Yakuza committed this night: doctor disposed + stale press rejects."""
        from bot.nam10.nmnd_narrator import Role
        from bot.nam10.roles_night_state import yaku_night_state

        game = self._fork_collect_room()
        self._confirm_all_except_interrog(game)
        game.nam10_doctor_pick_confirmed = False
        doc_uid = self._holder_uid(game, Role.DOCTOR)

        # Deliver the live doctor panel through the production night-entry
        # dispatcher so the mirror-prompt pair exists (real delivery).
        from bot.nam10.no_host_doctor_night import start_no_host_doctor_night_flow

        await start_no_host_doctor_night_flow(
            self.bot, game, self.manager, at_night_entry=True
        )
        had_panel = [
            s for s in self.bot.sends() if s[0] == doc_uid
        ]
        self.assertTrue(had_panel, "doctor panel must be delivered first")

        # Commit the Yakuza outcome the way the mafia flow leaves the state.
        civ_uid = self._holder_uid(game, Role.CITIZEN)
        game.nmnd_yaku_night_success = True
        game.nmnd_yaku_night_civilian_uid = civ_uid
        self.assertTrue(yaku_night_state(game).civilian_picked_this_night)

        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished, "interrogator is still genuinely pending")
        self.assertTrue(game.nam10_night_parallel_collect_active)

        # Doctor auto-disposed with a machine-readable reason + note panel.
        self.assertIn(
            "doctor_op_block#2",
            game.nam10_night_ready_disposed,
        )
        self.assertEqual(
            game.nam10_night_ready_disposed["doctor_op_block#2"],
            "action_cancelled_by_rule",
        )
        self.assertTrue(
            any(DOCTOR_NOTE_MARK in t for t in self.bot.texts()),
            f"doctor note panel must be delivered; texts={self.bot.texts()}",
        )
        # Voided pick state: no dead pick leaks after the block.
        from bot.nam10.roles_doctor import doctor_night_state

        self.assertEqual(doctor_night_state(game).get_save_uids(), [])

        # A stale pick press on the invalidated panel is rejected.
        pre = len(self.bot.calls)
        await self._press(doc_uid, "dkt", doc_uid, tid=int(civ_uid))
        self.assertIn(
            DOCTOR_BLOCK_ANSWER,
            [a for a in self.bot.acks() if a],
            f"stale pick must be rejected; acks={self.bot.acks()}",
        )
        self.assertEqual(doctor_night_state(game).get_save_uids(), [])

    async def test_03_citizen_conversion_closes_ack_and_auto_ready(self):
        """Converted citizen: obsolete ack panel closed, readiness auto-passes."""
        from bot.nam10.nmnd_narrator import Role

        game = self._fork_collect_room()
        # Night-entry deliveries may reset the per-night ack state, so the
        # citizen panel is delivered BEFORE the obligations are marked done.
        from bot.nam10.no_host_citizen_night import dispatch_no_host_citizen_night_panel

        await dispatch_no_host_citizen_night_panel(self.bot, game, self.manager)
        self._confirm_all_except_interrog(game)
        game.nam10_doctor_pick_confirmed = False
        int_uid = self._holder_uid(game, Role.INTERROGATOR)
        game.nam10_interrog_ui_phase = "skip_ack"
        game.nmnd_interrog_once_done = True
        game.nam10_interrog_dm_signature = "2:interrog:night_entry"

        civ_uid = self._holder_uid(game, Role.CITIZEN)
        # This citizen never pressed OK: drop them from the confirmed pool
        # so their ack is genuinely pending before the conversion.
        game.nam10_citizen_night_confirmed_uids = [
            u
            for u in (game.nam10_citizen_night_confirmed_uids or [])
            if u != civ_uid
        ]

        # The Yakuza conversion removes the citizen from the role pool.
        game.players[civ_uid].role = Role.MAFIA_BASIC
        game.mafia_ids = set(game.mafia_ids) | {civ_uid}
        game.nmnd_yaku_night_success = True
        game.nmnd_yaku_night_civilian_uid = civ_uid

        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished, "the doctor + interrogator are still pending")
        # No fabricated readiness: the citizen ack was never marked confirmed.
        self.assertNotIn(
            civ_uid,
            list(game.nam10_citizen_night_confirmed_uids or []),
        )
        disposed = game.nam10_night_ready_disposed
        self.assertIn("yaku_civ_ack#2", disposed)
        self.assertEqual(disposed["yaku_civ_ack#2"], "role_converted")
        self.assertTrue(
            any(CONVERT_NOTE_MARK in t for t in self.bot.texts()),
            f"converted ack panel must be replaced; texts={self.bot.texts()}",
        )
        auto = [e for e in self._audit_events() if e.get("event") == AUTO_RESOLVE_EVENT]
        self.assertTrue(
            any(e.get("reason") == "role_converted" for e in auto),
            f"audit must record the role_converted disposition; auto={auto}",
        )

        # The doctor is auto-ready on this rule-blocked night and the
        # interrogator confirms through the real skip-ack press: night closes.
        await self._press(int_uid, "niisk", int_uid)
        self.assertIn("ثبت شد.", self.bot.acks())
        self.assertFalse(
            game.nam10_night_parallel_collect_active,
            "after conversion dispositions + skip-ack commit the night closes",
        )

    async def test_04_missing_shiad_panel_restored_no_fabricated_ready(self):
        """A never-delivered mandatory panel is restored; no auto-confirm."""
        from bot.nam10.nmnd_narrator import Role

        game = self._fork_collect_room()
        self._confirm_all_except_interrog(game)
        game.nam10_doctor_pick_confirmed = False
        game.nam10_doctor_dm_signature = "2:doc:night_entry"
        # The yaku committed this night (doctor auto-disposed accordingly).
        civ_uid = self._holder_uid(game, Role.CITIZEN)
        game.nmnd_yaku_night_success = True
        game.nmnd_yaku_night_civilian_uid = civ_uid
        game.nam10_interrog_ui_phase = "skip_ack"
        game.nmnd_interrog_once_done = True
        game.nam10_interrog_dm_signature = "2:interrog:night_entry"
        game.nam10_shiad_pick_confirmed = False
        game.nam10_shiad_dm_signature = None

        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished, "Shiad must actually confirm, not be waived")
        self.assertTrue(game.nam10_night_parallel_collect_active)
        self.assertIsNotNone(
            game.nam10_shiad_dm_signature,
            "restore must deliver the missing mandatory panel",
        )
        self.assertTrue(
            game.nam10_shiad_flow_active,
            "restored flow must be armed and actionable",
        )
        auto = [e for e in self._audit_events() if e.get("event") == AUTO_RESOLVE_EVENT]
        self.assertTrue(
            any(
                e.get("reason") == "missing_panel_restored"
                and e.get("role") == "SHIAD"
                for e in auto
            ),
            f"audit must record the restore; auto={auto}",
        )
        # Idempotency: a repeated gate call must not re-send the panel.
        before = len(self.bot.calls)
        await maybe_finish_no_host_parallel_night(self.bot, game, self.manager)
        self.assertEqual(
            len(self.bot.calls), before, "no duplicate deliveries on repeat"
        )

    async def test_05_pending_panel_refreshed_once(self):
        """The pending list panel refreshes when the set changes, not twice."""
        from bot.nam10.nmnd_narrator import Role

        game = self._fork_collect_room()
        self._confirm_all_except_interrog(game)
        game.nam10_doctor_pick_confirmed = False
        game.nam10_doctor_dm_signature = "2:doc:night_entry"
        int_uid = self._holder_uid(game, Role.INTERROGATOR)
        game.nam10_interrog_ui_phase = "skip_ack"
        game.nmnd_interrog_once_done = True
        game.nam10_interrog_dm_signature = "2:interrog:night_entry"

        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        await maybe_finish_no_host_parallel_night(self.bot, game, self.manager)
        await maybe_finish_no_host_parallel_night(self.bot, game, self.manager)
        refreshes = [
            e
            for e in self._audit_events()
            if e.get("event") == REFRESH_EVENT
        ]
        self.assertEqual(
            len(refreshes),
            1,
            f"pending panel must refresh exactly once; refreshes={refreshes}",
        )

    async def test_06_genuine_pending_blocks_resolution(self):
        """A real unconfirmed obligation keeps the night open."""
        from bot.nam10.nmnd_narrator import Role

        game = self._fork_collect_room()
        self._confirm_all_except_interrog(game)
        game.nam10_doctor_pick_confirmed = False
        game.nam10_doctor_dm_signature = "2:doc:night_entry"
        game.nam10_interrog_pick_confirmed = True
        game.nam10_interrog_dm_signature = "2:interrog:night_entry"
        # No yaku this night: the doctor's pick is genuinely required.
        game.nmnd_yaku_night_success = None

        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(finished)
        self.assertTrue(game.nam10_night_parallel_collect_active)
        # The doctor's obligation was NOT fabricated: no disposed entry.
        self.assertNotIn("doctor_op_block#2", game.nam10_night_ready_disposed)

    async def test_07_nato_block_keeps_explicit_ok_flow(self):
        """NATO-blocked nights keep their explicit OK-ack (rules unchanged)."""
        from bot.nam10.nmnd_narrator import Role

        game = self._fork_collect_room()
        self._confirm_all_except_interrog(game)
        game.nam10_doctor_pick_confirmed = False
        game.nam10_doctor_dm_signature = "2:doc:night_entry"
        game.nam10_doctor_nato_blocked_panel = True
        game.nmnd_nato_action_registered = True
        game.nmnd_yaku_night_civilian_uid = None
        game.nam10_interrog_ui_phase = "skip_ack"
        game.nmnd_interrog_once_done = True
        game.nam10_interrog_dm_signature = "2:interrog:night_entry"

        from bot.nam10.no_host_night_ready import maybe_finish_no_host_parallel_night

        finished = await maybe_finish_no_host_parallel_night(
            self.bot, game, self.manager
        )
        self.assertFalse(
            finished, "NATO night doctor must still ack with the OK button"
        )
        self.assertNotIn("doctor_op_block#2", game.nam10_night_ready_disposed)
        self.assertFalse(
            any(DOCTOR_NOTE_MARK in t for t in self.bot.texts()),
            "the yaku informational note must not replace the NATO OK flow",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
