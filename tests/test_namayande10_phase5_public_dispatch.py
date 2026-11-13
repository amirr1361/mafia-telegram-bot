"""Phase 5 — public Namayande 10-player regression through REAL aiogram dispatch.

Unlike the phase-2 suites (which call handlers directly), this module
registers every production router on a real ``aiogram.Dispatcher`` and feeds
genuine ``Update`` events, so the exact handler chain Telegram triggers is
exercised. Rendered Telegram messages (edited text, keyboards, DMs) are
captured through a recording stand-in bot and asserted.

Isolated storage only: temporary SQLite DB and audit dir, production
``data/`` untouched.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from aiogram import Dispatcher
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Chat, Message, Update, User

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

_T = tempfile.mkdtemp(prefix="nam10_phase5_")
os.environ.setdefault("DATABASE_PATH", os.path.join(_T, "r.sqlite3"))
os.environ.setdefault("GAME_AUDIT_LOG_DIR", os.path.join(_T, "g"))
os.environ.setdefault("GAME_AUDIT_LOG_ENABLED", "0")

# Rebind the production GameManager BEFORE any bot module imports it, so
# every router module shares one instance.
import bot.app_state as _app_state
from bot.game import GameManager as _GM

_app_state.manager = _GM()

from bot import db as _db

_db.init_db()

from bot.handlers import register_all_handlers

HOST_UID = 7712345


class _RecordingBot:
    """Stand-in aiogram Bot: records every method-call object it receives."""

    id = 42

    def __init__(self) -> None:
        self.calls = []

    async def __call__(self, method, *args, **kwargs):  # aiogram sends methods
        self.calls.append(method)
        return MagicMock(message_id=len(self.calls) + 1, date=datetime.now(timezone.utc))

    def __getattr__(self, name):
        # Explicit bot.send_message(...)-style calls used by main.py flows.
        if name.startswith("_"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append(
                MagicMock(
                    __class_name__=name,
                    args=args,
                    **kwargs,
                )
            )
            return asyncio.sleep(0, result=MagicMock(message_id=1))

        return _record

    def edits(self):
        calls = [c for c in self.calls if type(c).__name__ == "EditMessageText"]
        return calls

    def sends(self):
        calls = [c for c in self.calls if type(c).__name__ == "SendMessage"]
        return calls

    def last_edit_text(self):
        edits = self.edits()
        return edits[-1].text if edits else ""

    def edit_markup_texts(self):
        """EditMessageText texts together with their reply markup."""
        return [(c.text, getattr(c, "reply_markup", None)) for c in self.edits()]


def _force_reset_all_routers():
    """Force any attached-but-orphaned singleton routers back to unattached
    state by resetting aiogram's private attribute (the public setter refuses
    None). Fresh dispatchers per attach keep registration free of duplicates.
    """
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
    """Fresh Dispatcher; adopt (re-register) the production routers."""
    dp = Dispatcher()
    try:
        register_all_handlers(dp)
    except RuntimeError:
        _force_reset_all_routers()
        register_all_handlers(dp)
    return dp


class Namayande10RealDispatchTest(unittest.TestCase):
    def setUp(self):
        self.bot = _RecordingBot()
        self.dp = _make_dispatcher()
        # Hermetic GameManager: real production code paths are exercised, but
        # the rooms live in this instance, isolated from other suites (which
        # create/reset the ambient app_state manager mid-suite).
        from bot.game import GameManager

        self.manager = GameManager()
        from unittest.mock import patch

        import bot.app_state as app_state
        import bot.handlers.lobby as lobby_mod
        import bot.handlers.no_host_player as nhp_mod
        import bot.main as main_mod

        self._patches = [
            patch.object(app_state, "manager", self.manager),
            patch.object(main_mod, "manager", self.manager),
            patch.object(lobby_mod, "manager", self.manager),
            patch.object(nhp_mod, "manager", self.manager),
        ]
        for p in self._patches:
            p.start()
        from bot.app_state import manager

        self.manager = manager
        self.host_user = User(
            id=HOST_UID, is_bot=False, first_name="Host", last_name="Tester"
        )
        self.host_chat = Chat(id=HOST_UID, type=ChatType.PRIVATE)
        self.host_message = Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=self.host_chat,
            from_user=self.host_user,
        )

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
        update = Update(
            update_id=1_000_000 + len(self.bot.calls), callback_query=cq
        )
        asyncio.run(self.dp.feed_update(self.bot, update))
        return update

    def room(self):
        from bot.room_mode import is_namayande10_no_host_room

        found = self.manager.get_room_for_host(HOST_UID)
        game = found if hasattr(found, "room_code") else self.manager.get_game(found)
        return game, is_namayande10_no_host_room(game) if game else None

    # ------------------------------------------------------------------
    # 1) crp:namayande:10 through the REAL dispatcher → fork room, creator
    #    seated, no-host creation presentation + dev-fill keyboard.
    # ------------------------------------------------------------------
    def test_create_namayande_10_renders_no_host_presentation(self):
        from bot.handlers.lobby import CreatePickPlayers

        self.feed_callback(
            CreatePickPlayers(slug="namayande", count=10).pack()
        )
        game, is_fork = self.room()
        self.assertIsNotNone(game, "room must be created via real handler")
        self.assertTrue(is_fork, "real dispatch must yield a fork room")
        self.assertEqual(game.scenario_name, "namayande")
        self.assertEqual(game.nmnd_host_mode, "no_host")
        self.assertIn(HOST_UID, game.players, "creator must be seated by real handler")

        text = self.bot.last_edit_text()
        # No-host creation presentation (parity with Bazpors no-host):
        self.assertIn("بازیکن گرداننده", text)
        self.assertIn("شما به‌عنوان <b>بازیکن</b> در این اتاق ثبت شدید", text)
        self.assertIn("🎲 <b>لابی</b>", text)
        # Scenario header says نماینده, never بازپرس:
        self.assertIn("🎭 سناریو: نماینده", text)
        self.assertNotIn("سناریو: <b>بازپرس</b>", text)
        # Classic host line and classic invitation flow must be gone:
        self.assertNotIn("🎙 گرداننده:", text)
        # Fork roster composition is rendered (classic roster must not be):
        from bot.game import role_roster_banner_text

        fork_banner = role_roster_banner_text(
            "namayande", 10, self.manager, nam10_no_host=True
        )
        classic_banner = role_roster_banner_text("namayande", 10, self.manager)
        from bot.main import format_roster_plain_to_html

        self.assertIn(
            format_roster_plain_to_html(fork_banner), text, "fork roster rendered"
        )
        self.assertNotIn(
            format_roster_plain_to_html(classic_banner), text, "classic roster absent"
        )
        # Dev-fill keyboard is attached (the missing piece that stranded the
        # room in LOBBY before this fix):
        markup = self.bot.edits()[-1].reply_markup
        self.assertIsNotNone(markup, "no-host creation must attach dev keyboard")
        buttons = [b for row in markup.inline_keyboard for b in row]
        labels = [b.text for b in buttons]
        self.assertIn("🎲 پر کردن تصادفی بازیکن‌ها", labels)
        self.assertIn("⏳ منتظر بازیکن‌های واقعی می‌مانم", labels)
        cbdatas = [b.callback_data for b in buttons]
        self.assertTrue(any(d.startswith("sad:") for d in cbdatas))
        self.assertTrue(
            any(":fill" in d for d in cbdatas), "fill button callback data present"
        )
        return game

    # ------------------------------------------------------------------
    # 2) press the dev-fill button through the REAL dispatcher → lobby
    #    fills via the fork synthetic-lobby path (never classic).
    # ------------------------------------------------------------------
    def test_dev_fill_button_drives_fork_lobby(self):
        from bot.handlers.lobby import CreatePickPlayers
        from bot.main import SemiAutoDevLobby

        self.feed_callback(CreatePickPlayers(slug="namayande", count=10).pack())
        game, _ = self.room()
        code = game.room_code

        self.feed_callback(SemiAutoDevLobby(code=code, act="fill").pack())

        game, _ = self.room()
        self.assertEqual(len(game.players), 10, "lobby filled to 10 seats")
        self.assertTrue(
            any(uid == HOST_UID for uid in game.players),
            "creator stays seated after fill",
        )
        text = self.bot.last_edit_text()
        self.assertIn("بازیکن واقعی", text)
        self.assertIn("بازیکن تست", text)
        self.assertIn("۱۰/۱۰", text)

    # ------------------------------------------------------------------
    # 3) other Namayande counts through the REAL dispatcher stay classic:
    #    creator not seated, generic host creation text, no dev keyboard.
    # ------------------------------------------------------------------
    def test_other_namayande_counts_rejected_all_layers(self):
        from bot.handlers.lobby import CreatePickPlayers

        # No leftover room of this host may exist before the test starts.
        stale = self.manager.get_room_for_host(HOST_UID)
        if stale is not None:
            code = stale.room_code if hasattr(stale, "room_code") else stale
            g = self.manager.games.get(code)
            self.manager.games.pop(code, None)
            self.manager.host_to_room.pop(HOST_UID, None)
            for puid, pcode in list(self.manager.player_to_room.items()):
                if pcode == code:
                    self.manager.player_to_room.pop(puid, None)
            note = f"removed stale room {code!r} info={g!r}"

        self.feed_callback(CreatePickPlayers(slug="namayande", count=16).pack())
        # Lobby gate: no room is created for legacy counts anymore.
        self.assertIsNone(self.manager.get_room_for_host(HOST_UID))
        # Server-side gate: even a forged create call is rejected.
        for legacy in (14, 16):
            game = self.manager.create_game(
                host_id=HOST_UID + legacy,
                scenario_name="namayande",
                max_players=legacy,
                nam10_no_host=True,
            )
            self.assertIsNone(game, legacy)

    # ------------------------------------------------------------------
    # 4) full roster presentation is the fork composition (role labels).
    # ------------------------------------------------------------------
    def test_fork_room_role_composition_after_real_deal(self):
        from bot.handlers.lobby import CreatePickPlayers
        from bot.main import SemiAutoDevLobby
        from bot.room_mode import is_namayande10_no_host_room

        self.feed_callback(CreatePickPlayers(slug="namayande", count=10).pack())
        game, _ = self.room()
        self.feed_callback(SemiAutoDevLobby(code=game.room_code, act="fill").pack())

        # Same seat finalization the fork harness uses before a real deal.
        self.assertEqual(len(game.players), 10)
        game.seats_finalized = True
        self.manager.assign_roles(game)
        roles = [p.role for p in game.players.values()]
        self.assertEqual(roles.count("MAFIA_BOSS"), 1)
        self.assertIn("NATO", roles)
        self.assertIn("SHIAD", roles)
        self.assertEqual(roles.count("CITIZEN"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
