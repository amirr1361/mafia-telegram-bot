"""Namayande-10 fork: eliminated-player report history (day/night timeline).

Live defect (Room 55): the eliminated player's 📋 گزارش بازی message showed
only the header + roster. ``_build_bazpors_timeline_html`` gated the shared
timeline to bazpors/mozakere/masoon scenarios, and the fork's audit records
carried ``bazpors: null`` with no night report html (fork narrator state
lives in nmnd_* fields), so no day/night history could ever be rendered.

Fix: fork-aware audit snapshots (nmnd_* state projected onto the shared
payload keys, fork night report html into ``night.resolved``) plus the
timeline gate accepting ``namayande`` when ``nmnd_host_mode == "no_host"``.

Isolated temporary storage only; never touches production rooms.
"""

import asyncio
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

OBS_UID = 90311
STRANGER_UID = 90417


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
        return MagicMock(
            message_id=len(self.calls), date=datetime.now(timezone.utc)
        )

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _record(*args, **kwargs):
            m = MagicMock(_cls=name, _rec_args=tuple(args), _rec_kwargs=dict(kwargs))
            self.calls.append(m)
            return MagicMock(message_id=len(self.calls) + 1)

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

    def acks(self):
        out = []
        for c in self.calls:
            if type(c).__name__ in ("AnswerCallbackQuery", "CallbackQueryAnswer"):
                out.append(getattr(c, "text", None))
        return out


class _Isolated(unittest.IsolatedAsyncioTestCase):
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
        import bot.post_game_flow as pgf_mod

        self._mgr_patches = [
            patch.object(_app_state, "manager", self.manager),
            patch.object(main_mod, "manager", self.manager),
            patch.object(lobby_mod, "manager", self.manager),
            patch.object(nhp_mod, "manager", self.manager),
            patch.object(host_panel_mod, "manager", self.manager),
            patch.object(pgf_mod, "manager", self.manager),
        ]
        for p in self._mgr_patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._mgr_patches):
            p.stop()
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    def _fork_room(self, *, observer=OBS_UID, max_players=10):
        from bot.game_audit_log import init_audit_log
        from bot.models import Phase, Player
        from bot.nam10.engine import is_mafia_team
        from bot.nam10.lobby import roles_for_count

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=max_players,
            nam10_no_host=True,
        )
        assert game is not None
        if observer:
            game.observer_user_id = observer
            game.observer_prompt_status = "pending"
        roster = roles_for_count(max_players)
        self.assertEqual(len(roster), max_players)
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
        return game

    _NIGHT1_REPORT = (
        "-----------\n"
        "🌙 ═══ <b>گزارش کامل شب گذشته</b> ═══\n"
        "🎯 هدف هانتر: هاکان (شهروند ساده)\n"
        "🔴 شات مافیا: خسروی (هانتر شهروند)\n"
        "🟢 نتیجهٔ کاراگاه: فریدونی (رویین تن) — منفی\n"
        "💉 پزشک از فراهانی (پزشک) محافظت کرد\n"
    )

    def _log_night1_real(self, game):
        """Night 1 resolution through the REAL shared logging path."""
        from bot.game_audit_log import log_night_resolved

        game.nmnd_night_report_html = self._NIGHT1_REPORT
        game.nmnd_narrator_night_count = 1
        game.nmnd_narrator_host_day = 2
        log_night_resolved(game)

    # ------------------------------------------------------------------
    async def test_header_and_full_fork_roster(self):
        from bot.nam10.no_host_elim_report import build_nam10_elim_cutoff_report_html

        game = self._fork_room()
        game.players[905].is_alive = False

        html = build_nam10_elim_cutoff_report_html(game, self.manager)
        self.assertIn("سناریو: نماینده", html)
        # The INTERROGATOR role label is legitimately «بازپرس»; only the
        # scenario header must not claim Bazpors.
        self.assertNotIn("سناریو: بازپرس", html)
        self.assertIn("بازیکنان و نقش‌ها", html)
        self.assertIn("رئیس مافیا", html)
        self.assertIn("وکیل", html)
        self.assertNotIn("برندهٔ بازی", html)
        self.assertNotIn("پایان بازی", html)
        # No audit events yet → no timeline section (same as old shape).
        self.assertNotIn("اتفاقات در طول بازی", html)

    async def test_day_elim_timeline_via_real_audit_logging(self):
        from bot.game_audit_log import log_player_eliminated
        from bot.nam10.no_host_elim_report import build_nam10_elim_cutoff_report_html

        game = self._fork_room()
        game.players[905].is_alive = False
        log_player_eliminated(game, 905, source="day_vote")

        html = build_nam10_elim_cutoff_report_html(game, self.manager)
        self.assertIn("🧭 <b>اتفاقات در طول بازی</b>", html)
        self.assertIn("☀️ <b>روز ۱</b>", html)
        self.assertIn("به اتفاق آرا از بازی خارج شد", html)
        # No further rounds exist yet.
        self.assertNotIn("روز ۲", html)

    async def test_night_section_from_real_night_resolved_logging(self):
        from bot.nam10.no_host_elim_report import build_nam10_elim_cutoff_report_html

        game = self._fork_room()
        self._log_night1_real(game)

        html = build_nam10_elim_cutoff_report_html(game, self.manager)
        self.assertIn("🧭 <b>اتفاقات در طول بازی</b>", html)
        self.assertIn("🌙 <b>شب ۱</b>", html)
        self.assertIn("شات مافیا", html)
        self.assertIn("هدف هانتر", html)
        self.assertIn("نتیجهٔ کاراگاه", html)
        self.assertIn("پزشک", html)
        # A night with no eliminations yet: no day-elimination lines at all.
        self.assertNotIn("به اتفاق آرا از بازی خارج شد", html)

    async def test_cutoff_immutable_after_later_events(self):
        from bot.nam10.no_host_elim_report import (
            build_nam10_elim_cutoff_report_html,
            capture_nam10_elim_report_cutoff,
            resolve_nam10_elim_report_html,
        )

        game = self._fork_room()
        game.players[905].is_alive = False
        game.nmnd_narrator_step = "confirm_day_elim"
        from bot.game_audit_log import log_player_eliminated

        log_player_eliminated(game, 905, source="eliminate_player")
        entry = capture_nam10_elim_report_cutoff(game, self.manager, 905)
        assert entry is not None
        frozen = entry["report_html"]
        self.assertIn("روز ۱", frozen)

        # Later rounds happen: night 2 + a renamed player.
        game.nmnd_night_report_html = (
            "🌙 ═══ <b>گزارش کامل شب گذشته</b> ═══\n🔴 شات مافیا: بازیکن 2"
        )
        game.nmnd_narrator_night_count = 2
        game.nmnd_narrator_host_day = 3
        from bot.game_audit_log import log_night_resolved

        log_night_resolved(game)
        game.players[901].full_name = "CHANGED_LATER"

        again = resolve_nam10_elim_report_html(
            game, 905, gts=entry["game_created_ts"]
        )
        self.assertEqual(again, frozen)
        self.assertNotIn("شب ۲", frozen)
        self.assertNotIn("CHANGED_LATER", frozen)
        live = build_nam10_elim_cutoff_report_html(game, self.manager)
        self.assertIn("CHANGED_LATER", live)
        self.assertIn("روز ۲", live)
        self.assertNotEqual(live, frozen)

    async def test_two_players_cutoffs_later_round_includes_history(self):
        from bot.game_audit_log import log_player_eliminated
        from bot.nam10.no_host_elim_report import capture_nam10_elim_report_cutoff

        game = self._fork_room()
        # Round 1: day-1 elimination (before any night resolved).
        game.players[905].is_alive = False
        game.nmnd_narrator_step = "confirm_day_elim"
        log_player_eliminated(game, 905, source="eliminate_player")
        e1 = capture_nam10_elim_report_cutoff(game, self.manager, 905)
        assert e1 is not None
        self.assertIn("روز ۱", e1["report_html"])
        self.assertNotIn("شات مافیا", e1["report_html"])

        # Round 2: night 1 resolves with events, then a day-2 elimination.
        self._log_night1_real(game)
        game.nmnd_narrator_step = "day_discuss"
        game.nmnd_narrator_host_day = 2
        game.players[904].is_alive = False
        log_player_eliminated(game, 904, source="eliminate_player")
        e2 = capture_nam10_elim_report_cutoff(game, self.manager, 904)
        assert e2 is not None
        # The later victim's cutoff includes all prior history...
        self.assertIn("روز ۱", e2["report_html"])
        self.assertIn("روز ۲", e2["report_html"])
        self.assertIn("🌙 <b>شب ۱</b>", e2["report_html"])
        self.assertIn("شات مافیا", e2["report_html"])
        # ...but nothing beyond the cutoff: night 2 renders only as the
        # empty placeholder (Bazpors parity), with no event lines at all.
        self.assertIn("🌙 <b>شب ۲</b> - بدون اتفاق", e2["report_html"])
        self.assertNotIn("روز ۲\n", e2["report_html"].split("بدون اتفاق", 1)[0].split("☀️ <b>روز ۲</b>", 1)[0])
        # And the earlier victim's frozen report never gained later content.
        self.assertNotIn("روز ۲", e1["report_html"])
        self.assertNotIn("شات مافیا", e1["report_html"])

    async def test_classic_namayande_timeline_stays_excluded(self):
        from bot.game_audit_log import init_audit_log, log_event
        from bot.nam10.no_host_elim_report import build_nam10_elim_cutoff_report_html

        game = self.manager.create_game(
            host_id=1, scenario_name="namayande", max_players=11
        )
        assert game is not None
        game.roles_dealt = True
        from bot.models import Player

        err = self.manager.add_player(
            game, Player(user_id=700, full_name="کلمنت", username=None, seat=1)
        )
        assert err is None
        init_audit_log(game)
        log_event(game, "player.eliminated", uid=700, source="day_vote")
        game.players[700].is_alive = False

        html = build_nam10_elim_cutoff_report_html(game, self.manager)
        # Classic host-mode Namayande keeps the old (timeline-less) shape.
        self.assertNotIn("اتفاقات در طول بازی", html)
        self.assertIn("بازیکنان و نقش‌ها", html)

    async def test_bazpors_timeline_parity_unchanged(self):
        from bot.bazpors_elim_report import build_bazpors_elim_cutoff_report_html
        from bot.game_audit_log import init_audit_log, log_player_eliminated
        from bot.models import Phase, Player, Role

        game = self.manager.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        seats = [(10, "Boss", Role.GODFATHER), (20, "Civ", Role.CITIZEN)]
        for i, (uid, name, role) in enumerate(seats, start=1):
            err = self.manager.add_player(
                game,
                Player(user_id=uid, full_name=name, username=None, role=role, seat=i),
            )
            assert err is None, err
        game.mafia_ids.add(10)
        game.roles_dealt = True
        game.phase = Phase.DAY_DISCUSSION
        game.bazpors_narrator_host_day = 1
        game.bazpors_narrator_night_count = 0
        game.bazpors_narrator_step = "day_discuss"
        init_audit_log(game)
        game.players[20].is_alive = False
        log_player_eliminated(game, 20, source="day_vote")

        html = build_bazpors_elim_cutoff_report_html(game, self.manager)
        self.assertIn("🧭 <b>اتفاقات در طول بازی</b>", html)
        self.assertIn("☀️ <b>روز ۱</b>", html)
        self.assertIn("Civ به اتفاق آرا از بازی خارج شد.", html)
        self.assertNotIn("نماینده", html)

    # ------------------------------------------------------------------
    # E2E — the real fork pipeline: day 1 (no defense) → night 1 role
    # actions → night resolution kills a player → the eliminated player's
    # cutoff report carries the full history; the observer gets the invite.
    # ------------------------------------------------------------------
    async def test_e2e_night1_elimination_report_full_history(self):
        from tests.nam10_flow_harness import Nam10FlowHarness

        harness = Nam10FlowHarness.build(self.manager)
        game = harness.game
        # The harness assigns roles outside the production deal pipeline, so
        # initialize the audit log the same way production's deal does.
        from bot.game_audit_log import init_audit_log

        init_audit_log(game)
        # The harness seeds observer_prompt_status="skipped"; reset it so the
        # real registration gate is exercised.
        game.observer_prompt_status = "pending"
        err = self.manager.register_game_observer(
            game, OBS_UID, full_name="ناظر", username=None
        )
        self.assertIsNone(err)

        from tests.nam10_game_loop import full_simulation_patches

        async with full_simulation_patches(harness):
            await harness.run_intro_night()
            await harness.day1_no_defense()
            await harness.complete_night1_via_role_buttons()

        dead = [uid for uid, p in game.players.items() if not p.is_alive]
        self.assertTrue(dead, "night 1 resolution must eliminate a player")

        # The resolution logged the fork's own night report with the shot.
        self.assertIsNotNone(game.nmnd_night_report_html)
        self.assertIn("شات مافیا", game.nmnd_night_report_html)
        self.assertEqual(game.nmnd_narrator_night_count, 1)

        from bot.nam10.no_host_elim_report import (
            build_nam10_elim_cutoff_report_html,
            maybe_send_nam10_elim_report_invite,
        )

        # The only difference from production is that the elimination-notice
        # hook is replaced by the loop's mocks, so the invite is re-issued
        # here for every real victim (idempotent cutoff capture applies).
        for uid in dead:
            await maybe_send_nam10_elim_report_invite(harness.bot, game, uid)
        victim = dead[0]
        entry = game.nmnd_elim_report_cutoffs.get(victim)
        self.assertIsInstance(entry, dict, "cutoff must be captured for the victim")
        html = entry["report_html"]
        self.assertIn("سناریو: نماینده", html)
        self.assertIn("بازیکنان و نقش‌ها", html)
        self.assertIn("🧭 <b>اتفاقات در طول بازی</b>", html)
        self.assertIn("🌙 <b>شب ۱</b>", html)
        self.assertIn("شات مافیا", html)
        self.assertNotIn("روز ۲", html)

        # A live rebuild must match the frozen cutoff (no drift yet).
        live = build_nam10_elim_cutoff_report_html(game, self.manager)
        self.assertEqual(live, html)

        # Observer invite copy was delivered with the invite text.
        invites = [
            (chat, text)
            for chat, text in self._dm_texts(harness)
            if "گزارش بازی" in (text or "")
        ]
        self.assertTrue(invites, "elim report invite must be delivered")
        self.assertTrue(
            any(chat == OBS_UID for chat, _ in invites),
            "observer must receive the invite copy",
        )

    def _dm_texts(self, harness):
        texts = []
        for call in harness.bot.send_message.call_args_list:
            args, kwargs = call.args, call.kwargs
            chat = kwargs.get("chat_id", args[0] if args else None)
            text = kwargs.get("text", args[1] if len(args) > 1 else "")
            texts.append((chat, text or ""))
        return texts

    # ------------------------------------------------------------------
    # Real dispatcher access rules (shared bzrep callback → fork delegate).
    # ------------------------------------------------------------------
    async def _access_game(self):
        from bot.game_audit_log import log_player_eliminated
        from bot.nam10.no_host_elim_report import BazporsElimReportCb

        from bot.nam10.no_host_elim_report import (
            BazporsElimReportCb,
            capture_nam10_elim_report_cutoff,
        )

        game = self._fork_room()
        game.players[905].is_alive = False
        log_player_eliminated(game, 905, source="day_vote")
        entry = capture_nam10_elim_report_cutoff(game, self.manager, 905)
        self.assertIsInstance(entry, dict)
        assert entry is not None
        gts = entry["game_created_ts"]
        data = BazporsElimReportCb(code=game.room_code, as_uid=905, gts=gts).pack()
        return game, data

    async def _feed_cb(self, data, actor_uid):
        user = User(id=actor_uid, is_bot=False, first_name="U")
        msg = Message(
            message_id=700,
            date=datetime.now(timezone.utc),
            chat=Chat(id=actor_uid, type=ChatType.PRIVATE),
            from_user=user,
        )
        cq = CallbackQuery(
            id=f"cq{actor_uid}-{len(self.bot.calls)}",
            from_user=user,
            chat_instance="ci",
            data=data,
            message=msg,
        )
        update = Update(update_id=5_000_000 + len(self.bot.calls), callback_query=cq)
        await self.dp.feed_update(self.bot, update)

    async def test_dead_player_reads_own_report_real_dispatcher(self):
        game, data = await self._access_game()
        await self._feed_cb(data, 905)
        sends = self.bot.sends()
        self.assertTrue(
            any(chat == 905 and "بازیکنان و نقش‌ها" in (text or "") for chat, text in sends),
            sends,
        )
        self.assertTrue(
            any("🧭 <b>اتفاقات در طول بازی</b>" in (text or "") for _, text in sends),
            "the report must include the timeline through the real path",
        )

    async def test_observer_reads_eliminated_report_real_dispatcher(self):
        game, data = await self._access_game()
        await self._feed_cb(data, OBS_UID)
        sends = self.bot.sends()
        self.assertTrue(
            any(
                chat == OBS_UID and "بازیکنان و نقش‌ها" in (text or "")
                for chat, text in sends
            ),
            sends,
        )

    async def test_stranger_rejected_real_dispatcher(self):
        game, data = await self._access_game()
        await self._feed_cb(data, STRANGER_UID)
        self.assertIn("اجازهٔ مشاهدهٔ این گزارش را ندارید.", self.bot.acks())
        self.assertFalse(
            any(
                chat == STRANGER_UID and "بازیکنان و نقش‌ها" in (text or "")
                for chat, text in self.bot.sends()
            )
        )

    async def test_alive_player_rejected_real_dispatcher(self):
        game, data = await self._access_game()
        from bot.nam10.no_host_elim_report import BazporsElimReportCb

        entry_ts = game.nmnd_elim_report_cutoffs[905]["game_created_ts"]
        data2 = BazporsElimReportCb(
            code=game.room_code, as_uid=906, gts=entry_ts
        ).pack()
        await self._feed_cb(data2, 906)
        self.assertIn("این گزارش فقط برای بازیکن حذف‌شده است.", self.bot.acks())
        self.assertFalse(
            any(chat == 906 and "بازیکنان و نقش‌ها" in (text or "") for chat, text in self.bot.sends())
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
