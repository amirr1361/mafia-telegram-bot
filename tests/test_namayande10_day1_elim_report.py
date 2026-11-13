"""Namayande-10 fork: Day-1 eliminated-player report invitation.

Live case (Room 74): the Day-1 representative-target outcome arrested a
SYNTHETIC player (کاوه) and the user reported the private eliminated-player
notification with the «📋 گزارش بازی» button as missing.  The pipeline is:

    eliminate_player_from_game
      -> queue_player_elimination_notify
      -> flush_elimination_notifications (after the Day-1 outcome press)
        -> notify_eliminated_player
          -> (synthetic: no direct DM) mirror of 💀 msg to registered Observer
          -> maybe_send_nam10_elim_report_invite
            -> capture the immutable elimination report cutoff at elimination time
            -> invite text + button (button served by the shared bzrep
               router in bot/bazpors_elim_report.py which delegates to the
               fork callback for Namayande rooms)

These tests exercise the REAL Day-1 outcome callback (d1o1/d1o2/d1o0)
through the registered aiogram dispatcher and then press the REAL
bzrep callback through the same dispatcher.

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
REAL_UIDS = list(range(901, 910))  # 901 Boss; 902/903 mafia; rest town
SYN_UID = -930001  # seat 10, synthetic

KILL_MARK = "شما از بازی خارج شدید"
INVITE_MARK = "برای مشاهده گزارش بازی"
REPORT_TITLE_MARK = "بازیکنان و نقش‌ها"
REPORT_BTN_MARK = "گزارش بازی"
STALE_ALERT = "این مرحله دیگر فعال نیست."
DENIED_ALERT = "اجازهٔ مشاهدهٔ این گزارش را ندارید."


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
        return [t for _, t in self.sends()]

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
        counts = {}
        for chat, t in self.sends():
            if mark in t:
                counts[chat] = counts.get(chat, 0) + 1
        return counts

    def last_bzrep_callback(self, chat_id: int) -> str | None:
        """callback_data of the LAST «گزارش بازی» button sent to chat_id."""
        found = None
        for text, kb in self.kb_segments():
            if kb is None or REPORT_BTN_MARK not in text:
                continue
            for row in kb.inline_keyboard:
                for btn in row:
                    if (
                        isinstance(btn, InlineKeyboardButton)
                        and (btn.callback_data or "").startswith("bzrep:")
                        and REPORT_BTN_MARK in btn.text
                    ):
                        found = btn.callback_data
        return found


class Nam10Day1ElimReportTest(unittest.IsolatedAsyncioTestCase):
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

    async def _press_raw(self, callback_data: str, actor_uid: int):
        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        cq = CallbackQuery(
            id=f"cqr-{len(self.bot.calls)}",
            from_user=actor,
            chat_instance="ci",
            data=callback_data,
            message=Message(
                message_id=778,
                date=datetime.now(timezone.utc),
                chat=Chat(id=actor_uid, type=ChatType.PRIVATE),
                from_user=actor,
            ),
        )
        update = Update(
            update_id=6_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    # ---- flow walkers (same shape as the betrayal suite) ---------------
    async def _walk_to_stage_a(self):
        await self._funnel()
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=904)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=902)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)

    async def _boss_choose(self, op: str, rep_uid: int, actor=901):
        await self._press(
            actor, "d1ba" if op == "add" else "d1bs", 901, tid=rep_uid
        )
        # Two-step flow: commit with the separate confirmation press.
        await self._press(actor, "d1bak", 901)

    def _wait_uids(self):
        from bot.nam10.day1_betrayal import _alive_mafia_boss

        boss = _alive_mafia_boss(self.game)
        boss_uid = boss.user_id if boss is not None else None
        return [
            uid
            for uid, p in self.game.players.items()
            if p.is_alive and uid != boss_uid
        ]

    async def _ack_all_waiting(self):
        for uid in self._wait_uids():
            actor = OBS_UID if uid == SYN_UID else uid
            await self._press(actor, "d1bw", uid)

    async def _walk_to_outcome(self, t1=907, t2=903):
        await self._walk_to_stage_a()
        await self._boss_choose("add", 904)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=t1)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=t2)
        await self._press(ASSIST_UID, "d1tok", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rv", ASSIST_UID)

    def _audit_events(self):
        path = self.game.audit_log_path
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    # =================================================================
    # Room 74 case — synthetic eliminated via Day-1 target vote
    # =================================================================
    async def test_01_synthetic_elim_observer_gets_mirror_and_invite(self):
        """Room 74 replication: target 2 (synthetic) eliminated via d1o2."""
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=SYN_UID)
        cuts_before = self.bot.send_counts(KILL_MARK)
        invites_before = self.bot.send_counts(INVITE_MARK)
        self.assertEqual(cuts_before, {})
        self.assertEqual(invites_before, {})

        # the REAL dispatcher press that eliminates target 2
        await self._press(ASSIST_UID, "d1o2", ASSIST_UID)

        self.assertFalse(self.game.players[SYN_UID].is_alive)
        self.assertTrue(self.game.players[907].is_alive)

        # 1) the eliminated-player message mirrored to the Observer
        cut_to_obs = self.bot.send_counts(KILL_MARK).get(OBS_UID, 0)
        self.assertGreaterEqual(
            cut_to_obs,
            1,
            "Observer must receive the 💀 eliminated-player mirror",
        )
        obs_kill = [t for c, t in self.bot.sends() if c == OBS_UID and KILL_MARK in t]
        self.assertTrue(obs_kill)
        # copy prefix identifies the eliminated seat for the observer
        self.assertTrue(any("امیر-نقش" in t for t in obs_kill))

        # 2) the report invitation with the button, also to the Observer
        invites = self.bot.send_counts(INVITE_MARK)
        self.assertIn(OBS_UID, invites, "Observer must receive the report invite")
        self.assertNotIn(
            SYN_UID,
            invites,
            "synthetic seats must never get a direct Telegram invite",
        )
        obs_invite = [
            t for c, t in self.bot.sends() if c == OBS_UID and INVITE_MARK in t
        ]
        self.assertTrue(obs_invite)

        # 3) the invite carries the immutable bzrep button
        cb = self.bot.last_bzrep_callback(OBS_UID)
        self.assertIsNotNone(cb)
        self.assertIn(f"bzrep:{self.game.room_code}:", cb)

        # 4) the cutoff was captured at elimination time
        entry = self.game.nmnd_elim_report_cutoffs.get(SYN_UID)
        self.assertIsInstance(entry, dict)
        self.assertFalse(self.game.players[SYN_UID].is_alive)
        self.assertTrue(entry.get("invite_sent"))
        html = entry.get("report_html")
        self.assertIsInstance(html, str)
        self.assertTrue(html.strip())

        # 5) the final-nap stage still opened — no handoff side effects
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_FINAL_NAP

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_FINAL_NAP)
        self.assertIsNone(self.game.nam10_day1_defense_phase)

        # 6) truthful audit trail: notify + invite outcomes recorded
        events = self._audit_events()
        notify = [e for e in events if e.get("event") == "elim.notify"]
        self.assertTrue(any(e.get("uid") == SYN_UID for e in notify))
        inv = [e for e in events if e.get("event") == "nam10.elim_report_invite"]
        self.assertTrue(inv)
        self.assertEqual(inv[-1].get("uid"), SYN_UID)
        self.assertTrue(inv[-1].get("synthetic"))
        self.assertTrue(inv[-1].get("observer_sent"))
        self.assertTrue(inv[-1].get("sent_any"))

    async def test_02_real_elim_direct_dm_and_observer_copies(self):
        """Target 1 (real player) eliminated via d1o1."""
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)

        self.assertFalse(self.game.players[907].is_alive)

        # direct DM to the eliminated real player
        self.assertIn(907, self.bot.send_counts(KILL_MARK))
        self.assertIn(907, self.bot.send_counts(INVITE_MARK))

        # and the Observer still receives its copies
        self.assertIn(OBS_UID, self.bot.send_counts(KILL_MARK))
        self.assertIn(OBS_UID, self.bot.send_counts(INVITE_MARK))

        entry = self.game.nmnd_elim_report_cutoffs.get(907)
        self.assertIsInstance(entry, dict)
        self.assertTrue(entry.get("invite_sent"))
        cb = self.bot.last_bzrep_callback(907)
        self.assertIsNotNone(cb)
        self.assertIn(f"bzrep:{self.game.room_code}:", cb)

        # truthful audit trail for the real eliminated player
        events = self._audit_events()
        notify = [e for e in events if e.get("event") == "elim.notify"]
        self.assertTrue(
            any(
                e.get("uid") == 907 and e.get("direct_sent") for e in notify
            ),
            "real eliminated player's DM delivery must be recorded",
        )
        inv = [e for e in events if e.get("event") == "nam10.elim_report_invite"]
        entry_inv = [e for e in inv if e.get("uid") == 907]
        self.assertTrue(entry_inv)
        self.assertTrue(entry_inv[-1].get("direct_sent"))
        self.assertTrue(entry_inv[-1].get("observer_sent"))

    # =================================================================
    # Opening the report via the REAL bzrep callback routing
    # =================================================================
    async def test_03_eliminated_button_opens_immutable_report(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)

        entry = self.game.nmnd_elim_report_cutoffs.get(907)
        html = entry["report_html"]
        cb = self.bot.last_bzrep_callback(907)
        self.assertIsNotNone(cb)

        n_before = len(self.bot.sends())
        await self._press_raw(cb, 907)
        delivered = self.bot.sends()[n_before:]
        texts = [t for c, t in delivered if c == 907]
        self.assertTrue(texts, "report must be delivered to the eliminated player")
        joined = "\n".join(texts)
        self.assertIn(REPORT_TITLE_MARK, joined)
        self.assertIn("سناریو: نماینده", joined)
        # the delivered report is the captured cutoff content
        self.assertTrue(any(t in html for t in texts if t))

    async def test_04_observer_opens_eliminated_report(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)

        cb = self.bot.last_bzrep_callback(OBS_UID)
        self.assertIsNotNone(cb)
        n_before = len(self.bot.sends())
        await self._press_raw(cb, OBS_UID)
        texts = [
            t for c, t in self.bot.sends()[n_before:] if c == OBS_UID
        ]
        self.assertTrue(texts, "observer must be able to open the report copy")
        joined = "\n".join(texts)
        self.assertIn(REPORT_TITLE_MARK, joined)

    async def test_05_unauthorized_alive_player_denied(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)

        cb = self.bot.last_bzrep_callback(907)
        # craft the same button pressed by an unauthorized alive player 904
        code, rest = cb.split(":", 1)
        self.assertEqual(code, "bzrep")
        _room, as_uid, gts = rest.split(":")
        self.assertEqual(int(as_uid), 907)
        from bot.bazpors_elim_report import BazporsElimReportCb

        forged = BazporsElimReportCb(
            code=self.game.room_code, as_uid=907, gts=int(gts)
        ).pack()
        n_before = len(self.bot.sends())
        await self._press_raw(forged, 904)
        new_texts = [
            t for c, t in self.bot.sends()[n_before:] if c == 904
        ]
        self.assertEqual(new_texts, [], "no report leak to an unauthorized player")
        self.assertTrue(
            any(a and DENIED_ALERT in a for a in self.bot.acks())
        )

    # =================================================================
    # Higher-level invariants
    # =================================================================
    async def test_06_no_elimination_outcome_sends_no_invite(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        invites_before = self.bot.send_counts(INVITE_MARK)
        kills_before = self.bot.send_counts(KILL_MARK)
        await self._press(ASSIST_UID, "d1o0", ASSIST_UID)

        self.assertEqual(self.game.nam10_day1_defense_outcome, "none")
        self.assertTrue(self.game.players[907].is_alive)
        self.assertEqual(self.bot.send_counts(INVITE_MARK), invites_before)
        self.assertEqual(self.bot.send_counts(KILL_MARK), kills_before)
        self.assertEqual(self.game.nmnd_elim_report_cutoffs, {})

    async def test_07_duplicate_actions_never_resent_invitation(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=903)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)

        invites_after_first = self.bot.send_counts(INVITE_MARK)
        self.assertGreater(sum(invites_after_first.values()), 0)

        # duplicate outcome press is stale and adds no invite
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)
        self.assertEqual(self.bot.send_counts(INVITE_MARK), invites_after_first)
        self.assertTrue(
            any(a and STALE_ALERT in a for a in self.bot.acks())
        )

        # direct re-invocation of the invitation helper is refused
        from bot.nam10.no_host_elim_report import send_nam10_elim_report_invitation

        ok = await send_nam10_elim_report_invitation(
            self.bot, self.game, self.manager, 907
        )
        self.assertFalse(ok)
        self.assertEqual(self.bot.send_counts(INVITE_MARK), invites_after_first)

    async def test_08_cutoff_survives_night_entry_immutable(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=SYN_UID)
        await self._press(ASSIST_UID, "d1o2", ASSIST_UID)

        entry = self.game.nmnd_elim_report_cutoffs.get(SYN_UID)
        frozen = entry["report_html"]

        # advance the game to Night 1 via the final nap
        await self._press(ASSIST_UID, "d1fn", ASSIST_UID)
        from bot.nam10.day1_betrayal import NAM10_DAY1_STAGE_NIGHT_ENTERED
        from bot.nam10.nmnd_narrator import NIGHT_START

        self.assertEqual(self.game.nam10_day1_stage, NAM10_DAY1_STAGE_NIGHT_ENTERED)
        self.assertIn(self.game.nmnd_narrator_step, (NIGHT_START, "night2_wait"))

        # the frozen report is untouched by later events
        self.assertEqual(self.game.nmnd_elim_report_cutoffs[SYN_UID]["report_html"], frozen)

        # and the button still opens exactly the captured report
        cb = self.bot.last_bzrep_callback(OBS_UID)
        self.assertIsNotNone(cb)
        await self._press_raw(cb, OBS_UID)

    async def test_09_synthetic_case_observer_button_opens_report(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=SYN_UID)
        await self._press(ASSIST_UID, "d1o2", ASSIST_UID)

        cb = self.bot.last_bzrep_callback(OBS_UID)
        self.assertIsNotNone(cb)
        # the button represents the eliminated synthetic player's uid
        self.assertIn(str(SYN_UID), cb)
        n_before = len(self.bot.sends())
        await self._press_raw(cb, OBS_UID)
        texts = [t for c, t in self.bot.sends()[n_before:] if c == OBS_UID]
        self.assertTrue(texts)
        joined = "\n".join(texts)
        self.assertIn(REPORT_TITLE_MARK, joined)
        self.assertIn("سناریو: نماینده", joined)

    async def test_10_report_identity_and_roster_fully_namayande(self):
        self._fork_room()
        await self._walk_to_outcome(t1=907, t2=SYN_UID)
        await self._press(ASSIST_UID, "d1o2", ASSIST_UID)

        entry = self.game.nmnd_elim_report_cutoffs.get(SYN_UID)
        html = entry["report_html"]
        self.assertIn("سناریو: نماینده", html)
        self.assertIn("بازیکنان و نقش‌ها", html)
        self.assertIn("رئیس مافیا", html)
        self.assertIn("امیر-نقش", html)
        # timeline gate must not render a bazpors-labeled report for the fork
        self.assertNotIn("سناریو: بازپرس", html)
        self.assertNotIn("برندهٔ بازی", html)


if __name__ == "__main__":
    unittest.main()
