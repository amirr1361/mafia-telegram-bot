"""Namayande-10 fork: /observer_<code> registration regression.

Live defect: ``/observer_1073`` in a Namayande-10 no-host room answered
"اتاق فعالی با این کد ناظر پیدا نشد" because the observer-code lookup and
observer registration gates only accepted ``bazpors_host_mode == "no_host"``.

Tests use the REAL aiogram dispatcher for the Telegram command
(``/observer_XXXX`` flows through the actual lobby router) and the real
fork mirror chain for observer panel delivery and a synthetic-player
action. Isolated temporary storage only; production data untouched.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, Update, User

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

_T = tempfile.mkdtemp(prefix="nam10_obs_")
os.environ.setdefault("DATABASE_PATH", os.path.join(_T, "r.sqlite3"))
os.environ.setdefault("GAME_AUDIT_LOG_DIR", os.path.join(_T, "g"))
os.environ.setdefault("GAME_AUDIT_LOG_ENABLED", "0")

import bot.app_state as _app_state
from bot.game import GameManager as _GM

_app_state.manager = _GM()

from bot import db as _db

_db.init_db()

from bot.handlers import register_all_handlers

HOST_UID = 7712347
OBS_UID = 7734657
STRANGER_UID = 7744255


class _RecordingBot:
    id = 42

    def __init__(self) -> None:
        self.calls = []

    async def __call__(self, method, *args, **kwargs):
        self.calls.append(method)
        return MagicMock(message_id=len(self.calls) + 1, date=datetime.now(timezone.utc))

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            m = MagicMock(__class_name__=name, args=args, **kwargs)
            m._rec_args = tuple(args)
            m._rec_kwargs = dict(kwargs)
            self.calls.append(m)
            return asyncio.sleep(0, result=MagicMock(message_id=1))

        return _record

    def edits(self):
        return [c for c in self.calls if type(c).__name__ == "EditMessageText"]

    def sends(self):
        return [c for c in self.calls if type(c).__name__ == "SendMessage"]

    def attr_sends(self):
        return [
            c
            for c in self.calls
            if getattr(c, "__class_name__", None) == "send_message"
        ]

    def last_edit_text(self):
        edits = self.edits()
        return edits[-1].text if edits else ""


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


class Namayande10ObserverRegistrationTest(unittest.TestCase):
    def setUp(self):
        self.bot = _RecordingBot()
        self.dp = _make_dispatcher()
        from bot.game import GameManager

        self.manager = GameManager()
        from unittest.mock import patch

        import bot.app_state as app_state
        import bot.handlers.host_panel as host_panel_mod
        import bot.handlers.lobby as lobby_mod
        import bot.handlers.no_host_player as nhp_mod
        import bot.main as main_mod

        self._patches = [
            patch.object(app_state, "manager", self.manager),
            patch.object(main_mod, "manager", self.manager),
            patch.object(lobby_mod, "manager", self.manager),
            patch.object(nhp_mod, "manager", self.manager),
            patch.object(host_panel_mod, "manager", self.manager),
        ]
        for p in self._patches:
            p.start()
        from bot.app_state import manager

        self.manager = manager
        self.host_user = User(
            id=HOST_UID, is_bot=False, first_name="Host", last_name="Obs"
        )
        self.host_chat = Chat(id=HOST_UID, type=ChatType.PRIVATE)
        self.host_message = Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=self.host_chat,
            from_user=self.host_user,
        )
        self.user_by_uid = {}

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def feed_callback(self, data_str, user=None, message=None):
        fuser = user or self.host_user
        cmessage = message or self.host_message
        cq = CallbackQuery(
            id=f"cq-{len(self.bot.calls)}",
            from_user=fuser,
            chat_instance="ci",
            data=data_str,
            message=cmessage,
        )
        update = Update(update_id=3_000_000 + len(self.bot.calls), callback_query=cq)
        asyncio.run(self.dp.feed_update(self.bot, update))

    def feed_command(self, text, user):
        chat = Chat(id=user.id, type=ChatType.PRIVATE)
        msg = Message(
            message_id=10_000 + len(self.bot.calls),
            date=datetime.now(timezone.utc),
            chat=chat,
            from_user=user,
            text=text,
        )
        update = Update(update_id=4_000_000 + len(self.bot.calls), message=msg)
        asyncio.run(self.dp.feed_update(self.bot, update))

    def user(self, uid, first="Obj"):
        u = self.user_by_uid.get(uid)
        if u is None:
            u = User(id=uid, is_bot=False, first_name=first)
            self.user_by_uid[uid] = u
        return u

    def answers(self):
        out = []
        for c in self.bot.calls:
            if type(c).__name__ in ("AnswerCallbackQuery", "CallbackQueryAnswer"):
                out.append(getattr(c, "text", None))
        return out

    def texts_to(self, target):
        out = []
        for c in self.bot.sends():
            out.append((getattr(c, "chat_id", None), getattr(c, "text", None)))
        for c in self.bot.attr_sends():
            args = getattr(c, "_rec_args", ()) or ()
            kw = getattr(c, "_rec_kwargs", {}) or {}
            chat = kw.get("chat_id")
            text = kw.get("text")
            if chat is None and args:
                chat = args[0]
            if text is None and len(args) > 1:
                text = args[1]
            out.append((chat, text))
        return [t for (chat, t) in out if chat == target]

    def room_for_host(self):
        found = self.manager.get_room_for_host(HOST_UID)
        game = found if hasattr(found, "room_code") else self.manager.get_game(found)
        return game

    def build_fork_room_to_deal(self):
        """Real-flow fork room: create -> dev fill -> shuffle -> confirm -> deal."""
        from bot.handlers.lobby import CreatePickPlayers
        from bot.main import HostPanel, SemiAutoDevLobby

        self.feed_callback(CreatePickPlayers(slug="namayande", count=10).pack())
        game = self.room_for_host()
        code = game.room_code
        self.feed_callback(SemiAutoDevLobby(code=code, act="fill").pack())
        game = self.room_for_host()
        self.assertEqual(len(game.players), 10)
        self.feed_callback(HostPanel(code=code, act="fs").pack())
        self.feed_callback(HostPanel(code=code, act="sy").pack())
        self.feed_callback(HostPanel(code=code, act="dr").pack())
        game = self.room_for_host()
        self.assertTrue(game.roles_dealt, "random deal must distribute fork roles")
        return game, code

    # ------------------------------------------------------------------
    # 1) wrong code through the real command handler.
    # ------------------------------------------------------------------
    def test_wrong_code_rejected_via_real_command_handler(self):
        self.feed_command("/observer_9999", self.user(OBS_UID, "Obs"))
        texts = self.texts_to(OBS_UID)
        self.assertTrue(
            any("اتاق فعالی با این کد ناظر پیدا نشد" in t for t in texts if t),
            texts,
        )
        # No room may be registered for the stranger.
        self.assertIsNone(self.manager.get_room_for_observer(OBS_UID))

    # ------------------------------------------------------------------
    # 2) valid code (incl. Persian digits) via the real handler, post-deal,
    #    mirroring room 14: lookup + registration + roster + host notify.
    # ------------------------------------------------------------------
    def test_valid_code_registers_observer_after_real_deal(self):
        game, code = self.build_fork_room_to_deal()
        raw_code = game.observer_code
        self.assertTrue(raw_code, "post-deal no-host fork room must carry observer code")
        obs_user = self.user(OBS_UID, "Obs")
        self.feed_command(f"/observer_{raw_code}", obs_user)
        game = self.room_for_host()

        self.assertEqual(game.observer_user_id, OBS_UID)
        self.assertEqual(game.observer_prompt_status, "registered")
        self.assertEqual(self.manager.get_room_for_observer(OBS_UID), game.room_code)
        self.assertFalse(game.bazpors_host_mode == "no_host")
        obs_texts = self.texts_to(OBS_UID)
        self.assertTrue(
            any("شما به‌عنوان <b>ناظر بازی</b>" in t for t in obs_texts if t),
            obs_texts,
        )
        # Roster copy reaches the observer too.
        roster_texts = [t for t in obs_texts if t and "ناظر" in t and "\n" in t]
        self.assertTrue(any(len(t) > 120 for t in roster_texts), roster_texts)
        host_texts = self.texts_to(HOST_UID)
        self.assertTrue(
            any("به‌عنوان ناظر بازی ثبت شد" in t for t in host_texts if t),
            host_texts,
        )

        # Re-registration replay: already-registered path stays reachable.
        self.feed_command(f"/observer_{raw_code}", obs_user)
        obs_texts = self.texts_to(OBS_UID)
        self.assertTrue(
            any("شما قبلاً ناظر اتاق" in t for t in obs_texts if t), obs_texts
        )
        self.assertEqual(game.observer_user_id, OBS_UID)

    # ------------------------------------------------------------------
    # 3) Persian-digit code form reaches the same registration.
    # ------------------------------------------------------------------
    def test_persian_digit_code_registers(self):
        game, _ = self.build_fork_room_to_deal()
        raw_code = game.observer_code
        fa = str.translate(
            raw_code,
            str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"),
        )
        self.feed_command(f"/observer_{fa}", self.user(OBS_UID, "Obs"))
        game = self.room_for_host()
        self.assertEqual(game.observer_user_id, OBS_UID)

    # ------------------------------------------------------------------
    # 4) rooms with a skipped observer prompt stay closed to registration,
    #    and Bazpors behavior is untouched.
    # ------------------------------------------------------------------
    def test_skipped_prompt_blocks_registration_and_bazpors_parity(self):
        from tests.nam10_flow_harness import Nam10FlowHarness

        harness = Nam10FlowHarness.build(self.manager)
        fam = harness.game
        fam.observer_prompt_status = "skipped"
        code = self.manager.ensure_observer_code(fam)
        self.feed_command(f"/observer_{code}", self.user(OBS_UID, "Obs"))
        texts = self.texts_to(OBS_UID)
        self.assertTrue(
            any("سازندهٔ بازی ثبت ناظر را لغو کرده است" in t for t in texts if t),
            texts,
        )
        self.assertIsNone(fam.observer_user_id)

        # Bazpors no-host room: the unchanged two-step creation + registration.
        from bot.handlers.lobby import CreatePickHostMode, CreatePickPlayers
        from bot.main import HostPanel, SemiAutoDevLobby

        stale = self.manager.get_room_for_host(HOST_UID)
        if stale is not None:
            sc = stale.room_code if hasattr(stale, "room_code") else stale
            self.manager.games.pop(sc, None)
            self.manager.host_to_room.pop(HOST_UID, None)
            for puid, pcode in list(self.manager.player_to_room.items()):
                if pcode == sc:
                    self.manager.player_to_room.pop(puid, None)

        self.feed_callback(CreatePickPlayers(slug="bazpors", count=10).pack())
        self.feed_callback(
            CreatePickHostMode(slug="bazpors", count=10, mode="no_host").pack()
        )
        bz = self.room_for_host()
        self.assertEqual(bz.scenario_name, "bazpors")
        self.assertEqual(bz.bazpors_host_mode, "no_host")
        self.feed_callback(SemiAutoDevLobby(code=bz.room_code, act="fill").pack())
        self.feed_callback(HostPanel(code=bz.room_code, act="fs").pack())
        self.feed_callback(HostPanel(code=bz.room_code, act="sy").pack())
        self.feed_callback(HostPanel(code=bz.room_code, act="dr").pack())
        self.assertTrue(bz.roles_dealt)
        bz_code = bz.observer_code
        self.assertTrue(bz_code)
        self.feed_command(f"/observer_{bz_code}", self.user(OBS_UID, "Obs"))
        self.assertEqual(bz.observer_user_id, OBS_UID)
        self.assertIsNone(bz.nmnd_host_mode)
        texts = self.texts_to(OBS_UID)
        self.assertTrue(
            any("شما به‌عنوان <b>ناظر بازی</b>" in t for t in texts if t), texts
        )

    # ------------------------------------------------------------------
    # 5) mirror panel delivery + observer acts for a SYNTHETIC player
    #    through the real pmr callback chain (nam10 citizen night act).
    # ------------------------------------------------------------------
    def test_observer_mirror_panel_and_synthetic_action(self):
        from tests.nam10_flow_harness import Nam10FlowHarness

        def run_coro(coro):
            return asyncio.run(coro)

        harness = Nam10FlowHarness.build(self.manager)
        game = harness.game
        # The harness seeds observer_prompt_status="skipped"; reset it to the
        # post-prompt state so the real registration gate is exercised.
        game.observer_prompt_status = "pending"
        err = self.manager.register_game_observer(
            game, OBS_UID, full_name="ناظر", username=None
        )
        self.assertIsNone(err, "fixed gate must permit the fork observer")
        self.assertEqual(game.observer_user_id, OBS_UID)

        run_coro(harness.run_intro_night())
        run_coro(harness.day1_no_defense())

        from tests.nam10_game_loop import ensure_night_entry

        run_coro(ensure_night_entry(harness))

        # A synthetic citizen's citizen-night pick panel must have an observer
        # mirror copy (the real register_mirror_prompt_pair path).
        from bot.roles.registry import get_role_module
        from bot.models import Role

        synthetic_citizen = None
        for uid, p in game.players.items():
            mod = get_role_module(Role.CITIZEN)
            if (
                uid < 0
                and p.is_alive
                and mod is not None
                and mod.is_simple_citizen(p)
            ):
                synthetic_citizen = uid
                break
        self.assertIsNotNone(synthetic_citizen, "fork roster must hold a citizen")
        entries = list(game.mirror_prompt_messages.values())
        self.assertTrue(
            any("observer" in entry for entry in entries),
            "observer mirror copies must be registered for night panels",
        )

        # Observer presses the citizen confirm mirror button for the synthetic.
        from bot.observer_delivery import PlayerMirrorCb
        from bot.nam10.no_host_citizen_night import _citizen_confirmed

        self.assertFalse(_citizen_confirmed(game, synthetic_citizen))
        self.feed_callback(
            PlayerMirrorCb(
                code=game.room_code, act="cic", as_uid=synthetic_citizen
            ).pack(),
            user=self.user(OBS_UID, "Obs"),
        )
        self.assertTrue(
            _citizen_confirmed(game, synthetic_citizen),
            "observer must be able to act for the synthetic citizen",
        )
        self.assertIn("تأیید ثبت شد.", self.answers())

        # A stranger (neither the player nor the observer) stays rejected.
        self.feed_callback(
            PlayerMirrorCb(
                code=game.room_code,
                act="cic",
                as_uid=synthetic_citizen,
            ).pack(),
            user=self.user(STRANGER_UID, "Away"),
        )
        self.assertIn(
            "فقط همان بازیکن می‌تواند این دکمه را بزند.", self.answers()
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
