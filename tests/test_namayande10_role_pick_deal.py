"""Namayande-10 fork: player-driven role selection (hidden-number deal).

Regression for the live defect where the fork deal panel only offered
"random role distribution" while Bazpors no-host also offered
"players pick their own roles". Exercises the REAL aiogram dispatch chain
(creation -> dev fill -> seat shuffle -> confirm -> deal panel -> pr ->
number claim -> finalize) through a genuine Dispatcher, with isolated
temporary storage only.
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

_T = tempfile.mkdtemp(prefix="nam10_pick_")
os.environ.setdefault("DATABASE_PATH", os.path.join(_T, "r.sqlite3"))
os.environ.setdefault("GAME_AUDIT_LOG_DIR", os.path.join(_T, "g"))
os.environ.setdefault("GAME_AUDIT_LOG_ENABLED", "0")

import bot.app_state as _app_state
from bot.game import GameManager as _GM

_app_state.manager = _GM()

from bot import db as _db

_db.init_db()

from bot.handlers import register_all_handlers

HOST_UID = 7712349

EXPECTED_ROSTER = sorted(
    [
        "MAFIA_BOSS",
        "NATO",
        "SHIAD",
        "HUNTER",
        "INTERROGATOR",
        "DETECTIVE",
        "DOCTOR",
        "RUINTAN",
        "CITIZEN",
        "CITIZEN",
    ]
)


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
            return asyncio.sleep(
                0,
                result=MagicMock(
                    message_id=1,
                    date=datetime.now(timezone.utc),
                    chat=MagicMock(id=kwargs.get("chat_id", args[0] if args else 0)),
                ),
            )

        return _record

    def edits(self):
        return [c for c in self.calls if type(c).__name__ == "EditMessageText"]

    def sends(self):
        return [c for c in self.calls if type(c).__name__ == "SendMessage"]

    def attr_sends(self):
        return [c for c in self.calls if getattr(c, "__class_name__", None) == "send_message"]

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


class Namayande10RolePickDealTest(unittest.TestCase):
    def setUp(self):
        self.bot = _RecordingBot()
        self.dp = _make_dispatcher()
        from bot.game import GameManager

        self.manager = GameManager()
        from unittest.mock import patch

        import bot.app_state as app_state
        import bot.handlers.lobby as lobby_mod
        import bot.handlers.no_host_player as nhp_mod
        import bot.main as main_mod
        import bot.handlers.host_panel as host_panel_mod

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
            id=HOST_UID, is_bot=False, first_name="Host", last_name="Pick"
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
        update = Update(update_id=2_000_000 + len(self.bot.calls), callback_query=cq)
        asyncio.run(self.dp.feed_update(self.bot, update))

    def room(self):
        found = self.manager.get_room_for_host(HOST_UID)
        game = found if hasattr(found, "room_code") else self.manager.get_game(found)
        return game

    def _build_fork_room_to_deal_panel(self):
        """Real-flow setup: create fork room, dev-fill, shuffle, confirm."""
        from bot.handlers.lobby import CreatePickPlayers
        from bot.main import HostPanel, SemiAutoDevLobby

        self.feed_callback(CreatePickPlayers(slug="namayande", count=10).pack())
        game = self.room()
        code = game.room_code
        self.assertEqual(len(game.players), 1)
        self.feed_callback(SemiAutoDevLobby(code=code, act="fill").pack())
        game = self.room()
        self.assertEqual(len(game.players), 10)
        self.feed_callback(HostPanel(code=code, act="fs").pack())
        self.feed_callback(HostPanel(code=code, act="sy").pack())
        game = self.room()
        return game, code

    def _dm_out(self, target=None):
        def _unpack(c):
            cls = getattr(c, "__class_name__", None)
            rec_args = getattr(c, "_rec_args", None)
            if cls is not None and rec_args is not None:
                # Attr-style recorded call: exact args/kwargs are stored.
                kw = c._rec_kwargs
                chat = kw.get("chat_id")
                text = kw.get("text")
                markup = kw.get("reply_markup")
                if chat is None and rec_args:
                    chat = rec_args[0]
                if text is None and len(rec_args) > 1:
                    text = rec_args[1]
                if text is None:
                    text = kw.get("caption")
            else:
                # Real aiogram method object (bot(method) path).
                chat = getattr(c, "chat_id", None)
                text = getattr(c, "text", None)
                if not text:
                    text = getattr(c, "caption", None)
                markup = getattr(c, "reply_markup", None)
            return (chat, text, markup)

        out = [_unpack(c) for c in self.bot.sends() + self.bot.attr_sends()]
        if target is not None:
            out = [o for o in out if o[0] == target]
        return out

    def _acks(self):
        """Callback acks; aiogram 3.x records AnswerCallbackQuery."""
        out = []
        for c in self.bot.calls:
            if type(c).__name__ in ("AnswerCallbackQuery", "CallbackQueryAnswer"):
                out.append(getattr(c, "text", None))
        return out

    def _keyboard_cbs(self, markup):
        return [b.callback_data for row in markup.inline_keyboard for b in row]

    def _keyboard_texts(self, markup):
        return [b.text for row in markup.inline_keyboard for b in row]

    # ------------------------------------------------------------------
    # 1) THE defect: fork deal panel must show BOTH distribution buttons.
    # ------------------------------------------------------------------
    def test_fork_deal_panel_shows_both_distribution_buttons(self):
        from bot.models import Phase

        game, code = self._build_fork_room_to_deal_panel()
        seen = []
        for text, markup in reversed(
            [(e.text, getattr(e, "reply_markup", None)) for e in self.bot.edits()]
        ):
            if "پخش نقش" in (text or ""):
                seen.append((text, markup))
                break
        self.assertTrue(seen, "deal panel edit must be emitted for the fork room")
        text, markup = seen[0]
        self.assertIsNotNone(markup, "deal panel must carry a keyboard")
        texts = self._keyboard_texts(markup)
        cbs = self._keyboard_cbs(markup)
        self.assertIn("🎭 پخش نقش‌های تصادفی", texts)
        self.assertIn("انتخاب نقش‌ها توسط بازیکنان", texts)
        self.assertIn(f"hp:{code}:pr", cbs)
        self.assertIn(f"hp:{code}:dr", cbs)
        self.assertEqual(game.phase, Phase.LOBBY)
        self.assertFalse(game.roles_dealt)

    # ------------------------------------------------------------------
    # 2) 'pr' through the real dispatcher starts the fork number-pick flow.
    # ------------------------------------------------------------------
    def test_pr_starts_fork_number_pick_panels(self):
        from bot.main import HostPanel

        game, code = self._build_fork_room_to_deal_panel()
        self.feed_callback(HostPanel(code=code, act="pr").pack())
        game = self.room()

        self.assertTrue(game.nam10_player_role_pick_active)
        self.assertFalse(game.roles_dealt)
        self.assertFalse(game.bazpors_player_role_pick_active)
        numbers = sorted(game.nam10_role_number_map)
        self.assertEqual(numbers, list(range(1, 11)))
        self.assertEqual(
            sorted(game.nam10_role_number_map.values()), EXPECTED_ROSTER
        )
        self.assertTrue(game.nam10_role_number_claims == {})
        self.assertIn(HOST_UID, game.nam10_role_pick_panel_messages)

        # Panel DM goes to the only real player (creator) with NAM10 callbacks.
        dms = [o for o in self._dm_out(HOST_UID) if o[1] == "لطفا یک شماره را انتخاب کنید تا نقش شما آشکار شود"]
        self.assertTrue(dms, "pick panel DM to creator missing")
        markup = dms[-1][2]
        self.assertIsNotNone(markup)
        texts = self._keyboard_texts(markup)
        self.assertEqual(len(texts), 10)
        self.assertIn("شماره ۱", texts)
        cbs = self._keyboard_cbs(markup)
        self.assertIn(f"nrp:{code}:1", cbs)
        self.assertFalse(any(c.startswith("brp:") for c in cbs))
        # No pick DMs to synthetic players.
        self.assertFalse(
            [o for o in self._dm_out() if isinstance(o[0], int) and o[0] < 0],
            "synthetic players must not receive pick panels",
        )

    # ------------------------------------------------------------------
    # 3) creator claims a number -> fork roles finalize like random deal.
    # ------------------------------------------------------------------
    def test_host_claim_finalizes_fork_roles_and_progression(self):
        from bot.main import HostPanel

        game, code = self._build_fork_room_to_deal_panel()
        self.feed_callback(HostPanel(code=code, act="pr").pack())
        game = self.room()
        chosen = 3
        self.feed_callback(f"nrp:{code}:{chosen}")
        game = self.room()

        # Ack recorded with the claim confirmation.
        acks = self._acks()
        self.assertIn("ثبت شد.", acks)

        # All ten players have roles; creator got the claimed number.
        self.assertTrue(game.roles_dealt)
        self.assertFalse(game.nam10_player_role_pick_active)
        self.assertTrue(game.nam10_non_real_role_assignment_completed)
        self.assertEqual(len(game.nam10_player_role_claims), 10)
        expected_role = game.nam10_role_number_map[chosen]
        self.assertEqual(game.players[HOST_UID].role.value, expected_role)
        roles = sorted(p.role.value for p in game.players.values())
        self.assertEqual(roles, EXPECTED_ROSTER)
        claims_by_source = {}
        for info in game.nam10_player_role_claims.values():
            claims_by_source[info["claim_source"]] = (
                claims_by_source.get(info["claim_source"], 0) + 1
            )
        self.assertEqual(claims_by_source.get("player"), 1)
        self.assertEqual(claims_by_source.get("automatic_non_real"), 9)
        # Host claimed number 3 -> host holds exactly that recorded claim.
        self.assertEqual(game.nam10_role_number_claims[chosen], HOST_UID)
        # Private role reveal delivered to the creator.
        self.assertTrue(any(o[1] and "نقش شما" in o[1] for o in self._dm_out(HOST_UID)))
        # Pick panels closed.
        closed = []
        for c in self.bot.calls:
            if getattr(c, "__class_name__", None) == "edit_message_text":
                ra = getattr(c, "_rec_args", ()) or ()
                kw = getattr(c, "_rec_kwargs", {}) or {}
                text = kw.get("text") or (ra[0] if ra else None)
                if text == "✅ نقش شما انتخاب شد.":
                    closed.append(c)
        self.assertTrue(closed, "pick panel must be closed after claim")

    # ------------------------------------------------------------------
    # 4) cross-flow isolation: other scenarios' callbacks stay inert here.
    # ------------------------------------------------------------------
    def test_cross_scenario_isolation_in_fork_room(self):
        from bot.main import HostPanel

        game, code = self._build_fork_room_to_deal_panel()
        # A stray Bazpors pick callback inside a fork room must be inert.
        self.feed_callback(f"brp:{code}:2")
        game = self.room()
        self.assertFalse(game.bazpors_player_role_pick_active)
        self.assertFalse(game.nam10_player_role_pick_active)
        self.assertEqual(game.nam10_role_number_map, {})
        self.assertEqual(game.nam10_role_number_claims, {})
        # Starting 'pr', then pressing 'dr' must hit the active-pick guard.
        self.feed_callback(HostPanel(code=code, act="pr").pack())
        game = self.room()
        self.assertTrue(game.nam10_player_role_pick_active)
        self.feed_callback(HostPanel(code=code, act="dr").pack())
        game = self.room()
        self.assertFalse(game.roles_dealt, "random deal must be blocked while pick active")
        self.assertTrue(game.nam10_player_role_pick_active)
        acks = [
            getattr(c, "text", None)
            for c in self.bot.calls
            if type(c).__name__ in ("AnswerCallbackQuery", "CallbackQueryAnswer")
        ]
        self.assertIn("جریان انتخاب نقش توسط بازیکنان فعال است.", acks)

    # ------------------------------------------------------------------
    # 5) classic Namayande counts stay classic: NO pick button, 'pr' inert.
    # ------------------------------------------------------------------
    def test_classic_namayande_has_no_pick_option(self):
        from bot.handlers.lobby import CreatePickPlayers
        from bot.main import HostPanel, host_deal_roles_keyboard

        stale = self.manager.get_room_for_host(HOST_UID)
        if stale is not None:
            code = stale.room_code if hasattr(stale, "room_code") else stale
            self.manager.games.pop(code, None)
            self.manager.host_to_room.pop(HOST_UID, None)
            for puid, pcode in list(self.manager.player_to_room.items()):
                if pcode == code:
                    self.manager.player_to_room.pop(puid, None)

        from bot.handlers.lobby import CreatePickPlayers as _CPP

        # Namayande supports only 10/11/12/13; the legacy classic count
        # path is gone, so the classic room is built directly to keep
        # pinning the 'pr' defence-in-depth rejection.
        self.feed_callback(_CPP(slug="namayande", count=16).pack())
        self.assertIsNone(self.manager.get_room_for_host(HOST_UID))
        game = self.manager.create_game(
            host_id=HOST_UID,
            scenario_name="namayande",
            max_players=13,
            nam10_no_host=False,
        )
        self.assertIsNotNone(game)
        game = self.room()
        self.assertEqual(game.scenario_name, "namayande")
        self.assertIsNone(game.nmnd_host_mode, "classic room has no fork mode")
        kb = host_deal_roles_keyboard(game)
        texts = self._keyboard_texts(kb)
        self.assertIn("🎭 پخش نقش‌های تصادفی", texts)
        self.assertNotIn("انتخاب نقش‌ها توسط بازیکنان", texts)
        # Direct 'pr' dispatch is rejected for classic rooms (defense in depth).
        self.feed_callback(HostPanel(code=game.room_code, act="pr").pack())
        acks = [
            getattr(c, "text", None)
            for c in self.bot.calls
            if type(c).__name__ in ("AnswerCallbackQuery", "CallbackQueryAnswer")
        ]
        self.assertIn("این گزینه برای این سناریو فعال نیست.", acks)
        self.assertFalse(getattr(game, "nam10_player_role_pick_active", False))

    # ------------------------------------------------------------------
    # 6) the random distribution option keeps working for the fork.
    # ------------------------------------------------------------------
    def test_random_distribution_still_works_for_fork(self):
        from bot.main import HostPanel

        game, code = self._build_fork_room_to_deal_panel()
        self.feed_callback(HostPanel(code=code, act="dr").pack())
        game = self.room()
        self.assertTrue(game.roles_dealt)
        self.assertFalse(game.nam10_player_role_pick_active)
        roles = sorted(p.role.value for p in game.players.values())
        self.assertEqual(roles, EXPECTED_ROSTER)
        self.assertIn(
            "✅ نقش‌ها پخش شد", self.bot.last_edit_text()
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
