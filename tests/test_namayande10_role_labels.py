"""Namayande-10 fork: independent role display registry (renaming).

Display-only task — the internal ``Role`` enum values, mechanics, faction
membership and composition are unchanged.  The fork now resolves every
player-facing role label through ``bot/nam10/role_labels.py``:

    MAFIA_BOSS  رئیس مافیا / Mafia Boss      SHIAD     هکر / Hacker
    NATO        یاغی / Rebel                 HUNTER    وکیل / Lawyer
    INTERROGATOR راهنما / Guide              DETECTIVE محافظ / Guardian
    RUINTAN     مین‌گذار / Mine Layer        DOCTOR    پزشک / Doctor
    CITIZEN     شهروند ساده / Citizen

Bazpors and classic Namayande (11+) keep their original labels.
"""

import os
import sys
import unittest
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
from bot.models import Game, Phase, Player, Role
from bot.observer_delivery import PlayerMirrorCb

ASSIST_UID = 80012
OBS_UID = 80013
REAL_UIDS = list(range(901, 910))
SYN_UID = -930001


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
        from bot.handlers import register_all_handlers

        register_all_handlers(dp)
    except RuntimeError:
        _force_reset_all_routers()
        from bot.handlers import register_all_handlers

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
            date=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _record(*args, **kwargs):
            from types import SimpleNamespace
            import datetime

            m = SimpleNamespace(
                message_id=len(self.calls) + 10_000,
                chat=SimpleNamespace(
                    id=kwargs.get("chat_id", args[0] if args else None)
                ),
                date=datetime.datetime.now(datetime.timezone.utc),
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


class Nam10RoleLabelsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._dbp = root / "t.sqlite3"
        self._audit = root / "audit"
        self._audit.mkdir()
        self._patches = [
            patch("bot.config.get_database_path", return_value=self._dbp),
            patch("bot.config.get_game_audit_log_dir", return_value=self._audit),
            patch.dict(
                os.environ,
                {
                    "DATABASE_PATH": str(self._dbp),
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
    def _fork_room(self):
        from bot.game_audit_log import init_audit_log
        from bot.nam10.nmnd_narrator import DAY_DISCUSS
        from bot.nam10.lobby import assign_roles_namayande10

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        seat = 0
        for uid in REAL_UIDS + [SYN_UID]:
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
        assign_roles_namayande10(game)
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_step = DAY_DISCUSS
        game.observer_user_id = OBS_UID
        game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game
        return game

    def _deal_role_of(self, uid):
        return self.game.players[uid].role

    # =================================================================
    # 1–3: registry mapping / names / composition
    # =================================================================
    async def test_01_registry_maps_exact_new_persian_names(self):
        from bot.nam10.role_labels import (
            NAM10_ROLE_LABELS_FA,
            nam10_role_label_fa,
        )

        expected = {
            Role.MAFIA_BOSS: "رئیس مافیا",
            Role.NATO: "یاغی",
            Role.SHIAD: "هکر",
            Role.DOCTOR: "پزشک",
            Role.INTERROGATOR: "راهنما",
            Role.HUNTER: "وکیل",
            Role.DETECTIVE: "محافظ",
            Role.RUINTAN: "مین‌گذار",
            Role.CITIZEN: "شهروند ساده",
            Role.NATO_AGENT: "ناتو",
            Role.SOLDIER: "سرباز",
        }
        self.assertEqual(NAM10_ROLE_LABELS_FA, expected)
        for role, label in expected.items():
            self.assertEqual(nam10_role_label_fa(role), label)

    async def test_02_english_names_registered(self):
        from bot.nam10.role_labels import (
            NAM10_ROLE_LABELS_EN,
            nam10_role_label_en,
        )

        self.assertEqual(
            NAM10_ROLE_LABELS_EN,
            {
                Role.MAFIA_BOSS: "Mafia Boss",
                Role.NATO: "Rebel",
                Role.SHIAD: "Hacker",
                Role.DOCTOR: "Doctor",
                Role.INTERROGATOR: "Guide",
                Role.HUNTER: "Lawyer",
                Role.DETECTIVE: "Guardian",
                Role.RUINTAN: "Mine Layer",
                Role.CITIZEN: "Citizen",
                Role.NATO_AGENT: "NATO Agent",
                Role.SOLDIER: "Soldier",
            },
        )
        self.assertEqual(nam10_role_label_en(Role.DETECTIVE), "Guardian")

    async def test_03_composition_unchanged_citizen_x2(self):
        from collections import Counter

        from bot.nam10.lobby import roles_for_count
        from bot.nam10.role_labels import NAM10_FORK_ROLE_COMPOSITION

        expected = Counter(
            {
                Role.MAFIA_BOSS: 1,
                Role.NATO: 1,
                Role.SHIAD: 1,
                Role.DOCTOR: 1,
                Role.INTERROGATOR: 1,
                Role.HUNTER: 1,
                Role.DETECTIVE: 1,
                Role.RUINTAN: 1,
                Role.CITIZEN: 2,
            }
        )
        self.assertEqual(Counter(roles_for_count(10)), expected)
        self.assertEqual(Counter(NAM10_FORK_ROLE_COMPOSITION), expected)

    # =================================================================
    # 4–8: rendered fork surfaces use the new labels; others keep old ones
    # =================================================================
    async def test_04_role_card_text_builder_uses_new_labels(self):
        """The deal/roster card text builder renders fork labels."""
        self._fork_room()
        from bot.nam10.nmnd_narrator import _night_role_step_name
        from bot.nam10.role_labels import nam10_role_label_fa

        dealt = {p.role for p in self.game.players.values() if p.role}
        self.assertEqual(
            len(dealt), 9  # 9 distinct roles (citizen repeats)
        )
        for role in dealt:
            label = nam10_role_label_fa(role)
            self.assertNotIn("ناتو", label)
            self.assertNotIn("شیاد", label)
            self.assertNotIn("بازپرس", label)
            self.assertNotIn("هانتر", label)
            self.assertNotIn("کاراگاه", label)
            self.assertNotIn("رویین", label)
        # spot check the reveal-card builder path via the step-name fallback
        self.assertEqual(_night_role_step_name(Role.RUINTAN), "مین‌گذار")

    async def test_05_synthetic_suffix_and_observer_prefix(self):
        self._fork_room()
        from bot.game import synthetic_player_base_name
        from bot.nam10.lobby import sync_synthetic_player_display_names_nam10

        # make the synthetic holder obvious
        self.game.players[SYN_UID].role = Role.SHIAD
        sync_synthetic_player_display_names_nam10(self.game)
        base = synthetic_player_base_name(
            self.game.players[SYN_UID].full_name
        )
        self.game.players[SYN_UID].full_name = f"{base}-هکر"
        self.assertIn("-هکر", self.game.players[SYN_UID].full_name)

        # observer per-seat copy prefix resolves the fork label
        from bot.observer_delivery import observer_player_copy_prefix

        self.game.players[908].role = Role.HUNTER
        pref = observer_player_copy_prefix(self.game, 908)
        self.assertIn("وکیل", pref)

    async def test_06_night_step_and_waiting_labels(self):
        self._fork_room()
        from bot.nam10.nmnd_narrator import _night_role_step_name
        from bot.nam10.no_host_night_ready import (
            pending_no_host_night_actor_labels,
        )

        self.assertEqual(_night_role_step_name(Role.HUNTER), "وکیل")
        self.assertEqual(_night_role_step_name(Role.INTERROGATOR), "راهنما")
        self.assertEqual(_night_role_step_name(Role.DETECTIVE), "محافظ")
        joined = "\n".join(pending_no_host_night_actor_labels(self.game))
        self.assertNotIn("هانتر", joined)
        self.assertNotIn("کارآگاه", joined)
        self.assertNotIn("رویین", joined)
        self.assertNotIn("بازپرس", joined)
        self.assertNotIn("شیاد", joined)
        self.assertNotIn("ناتو", joined)

    async def test_07_timeline_night_lines_fork_labels(self):
        from bot.main import _timeline_night_lines_from_bazpors

        bz = {
            "hunter_link_uid": 5,
            "hunter_linked_this_night": True,
            "mafia_shot_registered": True,
            "mafia_target": 6,
            "shiad_target_uid": 7,
            "detective_check": 8,
            "det_no_inquiry": False,
            "interrog_night_finished": True,
            "interrog_first_uid": 9,
            "interrog_second_uid": 10,
        }

        def tag(u):
            return f"#{u}"

        old_lines = "\n".join(
            _timeline_night_lines_from_bazpors(bz, tag)
        )
        self.assertIn("هانتر", old_lines)
        self.assertIn("شیاد", old_lines)
        self.assertIn("کارآگاه", old_lines)
        self.assertIn("بازپرس", old_lines)

        fork_lines = "\n".join(
            _timeline_night_lines_from_bazpors(bz, tag, nam10=True)
        )
        self.assertIn("وکیل", fork_lines)
        self.assertIn("هکر", fork_lines)
        self.assertIn("محافظ", fork_lines)
        self.assertIn("راهنما", fork_lines)
        self.assertNotIn("هانتر", fork_lines)
        self.assertNotIn("شیاد:", fork_lines)

    # =================================================================
    # 11: eliminated-player report + final report via the REAL dispatcher
    # =================================================================
    async def _press(self, actor_uid, act, as_uid, tid=0):
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
                date=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
                chat=Chat(id=actor_uid, type=ChatType.PRIVATE),
                from_user=actor,
            ),
        )
        update = Update(
            update_id=4_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    async def _walk_to_outcome(self):
        await self._do_funnel()
        for uid in self._wait_uids():
            actor = OBS_UID if uid == SYN_UID else uid
            await self._press(actor, "d1bw", uid)
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=905)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=907)
        await self._press(ASSIST_UID, "d1tok", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rv", ASSIST_UID)

    async def _do_funnel(self):
        from bot.nam10.no_host_day_vote import send_no_host_day_vote_prompt

        await send_no_host_day_vote_prompt(self.bot, self.game)
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=904)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=902)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)
        # boss add rep1 (904) + traitor reveal stage needs one boss action
        boss = None
        for uid, p in self.game.players.items():
            if p.role == Role.MAFIA_BOSS and p.is_alive:
                boss = uid
        if boss is not None:
            await self._press(
                OBS_UID if boss == SYN_UID else boss,
                "d1ba",
                boss,
                tid=904,
            )
            await self._press(
                OBS_UID if boss == SYN_UID else boss, "d1bak", boss
            )

    def _wait_uids(self):
        from bot.nam10.day1_betrayal import _alive_mafia_boss

        boss = _alive_mafia_boss(self.game)
        boss_uid = boss.user_id if boss is not None else None
        return [
            uid
            for uid, p in self.game.players.items()
            if p.is_alive and uid != boss_uid
        ]

    async def test_08_elim_report_and_final_report_new_labels(self):
        self._fork_room()
        await self._walk_to_outcome()
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)

        # eliminated-player report keeps Namayande identity and fork labels
        entry = self.game.nmnd_elim_report_cutoffs.get(905)
        self.assertIsInstance(entry, dict)
        html = entry.get("report_html") or ""
        self.assertIn("سناریو: نماینده", html)
        new_words = ["یاغی", "هکر", "راهنما", "وکیل", "محافظ", "مین‌گذار"]
        old_words = ["ناتو", "شیاد", "بازپرس", "هانتر", "کاراگاه", "کارآگاه",
                     "رویین"]
        for w in new_words:
            self.assertIn(w, html)
        for w in old_words:
            self.assertNotIn(w, html)

        # final game-end broadcast keeps the fork roster labels too
        from bot.main import build_bazpors_game_end_broadcast_html

        self.game.nmnd_narrator_night_count = 0
        end_html = build_bazpors_game_end_broadcast_html(self.game, "mafia")
        self.assertIn("رئیس مافیا", end_html)
        for w in ["یاغی", "هکر", "محافظ", "مین‌گذار", "وکیل", "راهنما"]:
            self.assertIn(w, end_html)

    # =================================================================
    # 12/14/17: internal identities + snapshot stability
    # =================================================================
    async def test_09_internal_role_values_and_snapshot_roundtrip(self):
        self._fork_room()
        # enum values untouched — stable serialized identities
        self.assertEqual(Role.NATO.value, "NATO")
        self.assertEqual(Role.SHIAD.value, "SHIAD")
        self.assertEqual(Role.INTERROGATOR.value, "INTERROGATOR")
        self.assertEqual(Role.HUNTER.value, "HUNTER")
        self.assertEqual(Role.DETECTIVE.value, "DETECTIVE")
        self.assertEqual(Role.RUINTAN.value, "RUINTAN")

        from bot.game_snapshot import (
            game_from_snapshot_dict,
            game_to_snapshot_dict,
        )

        payload = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(payload)
        for uid, p in self.game.players.items():
            self.assertEqual(restored.players[uid].role, p.role)
        # no fork label leaked into persisted identity fields
        blob = str(payload)
        for w in ["یاغی", "هکر", "راهنما", "وکیل", "محافظ", "مین‌گذار"]:
            self.assertNotIn(w, blob)

    # =================================================================
    # 13: is_mafia_team unchanged (mechanic identity)
    # =================================================================
    async def test_10_faction_membership_functions_unchanged(self):
        from bot.game import is_mafia_team

        self.assertTrue(is_mafia_team(Role.NATO))
        self.assertTrue(is_mafia_team(Role.SHIAD))
        self.assertTrue(is_mafia_team(Role.MAFIA_BOSS))
        self.assertFalse(is_mafia_team(Role.HUNTER))
        self.assertFalse(is_mafia_team(Role.RUINTAN))
        self.assertFalse(is_mafia_team(Role.CITIZEN))

    # =================================================================
    # 15/16: scenario isolation
    # =================================================================
    async def test_11_bazpors_and_classic_namayande_keep_old_labels(self):
        from bot.game import scenario_role_label_fa

        old_map = {
            Role.NATO: "ناتو",
            Role.SHIAD: "شیاد",
            Role.INTERROGATOR: "بازپرس",
            Role.HUNTER: "هانتر (شهروند)",
            Role.DETECTIVE: "کاراگاه",
            Role.RUINTAN: "رویین تن",
        }
        for scenario, mode in (("bazpors", "host"), ("namayande", "host")):
            g = Game(
                room_code=f"x{scenario[:2]}",
                host_id=1,
                scenario_name=scenario,
                max_players=13,
            )
            if scenario == "namayande":
                g.nmnd_host_mode = None
                g.max_players = 12
            for role, old in old_map.items():
                self.assertEqual(
                    scenario_role_label_fa(g, role), old, (scenario, role)
                )

        # an un-activated fork room (host mode) keeps old labels as well
        g = Game(
            room_code="zz", host_id=1, scenario_name="namayande", max_players=10
        )
        g.nmnd_host_mode = "host"
        self.assertEqual(scenario_role_label_fa(g, Role.NATO), "ناتو")


if __name__ == "__main__":
    unittest.main()
