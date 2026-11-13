"""Namayande-10 fork: text-only private role reveal (no role image).

Covers the Namayande-10-only change in ``bot.main.send_private_role`` /
``build_private_role_message_html``:

- every Namayande-10 role gets the text-only notification built from the
  Persian role label plus the short capability description;
- no role photo/attachment is ever sent in this path;
- exactly one reveal per real player (retry-safe); synthetic seats are
  skipped entirely;
- unrelated scenarios keep their original role delivery (spoiler +
  card default, Mozakere spoiler builder);
- in the shared deal pipeline the private role messages are still
  delivered to every real player (synthetic skipped) before the
  Observer code prompt.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import bot.app_state as _app_state
from bot.game import GameManager as _GM

_app_state.manager = _GM()

import bot.db as _db

_db.init_db()

from bot.game import GameManager
from bot.models import Player, Role

ASSIST_UID = 80012
OBS_UID = 80013
BOSS_UID = 901
NATO_UID = 902
SHIAD_UID = 903
LAW_UID = 904
GUIDE_UID = 905
GUARD_UID = 906
DOC_UID = 907
MINE_UID = 908
CIT1_UID = 909
SYN_UID = -930001  # seat 10, synthetic citizen
REAL_UIDS = list(range(901, 910))


class _ParaBot:
    """Minimal recording bot (send_message / send_photo only)."""

    id = 42

    def __init__(self):
        self.photos = []
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))
        return SimpleNamespace(
            message_id=len(self.messages) + 100,
            chat=SimpleNamespace(id=chat_id),
            date=datetime.now(timezone.utc),
        )

    async def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append((chat_id, photo, kwargs))
        return SimpleNamespace(
            message_id=len(self.messages) + 100,
            chat=SimpleNamespace(id=chat_id),
            date=datetime.now(timezone.utc),
        )

    def texts_to(self, chat_id):
        return [t for c, t in self.messages if c == chat_id]


class _TolerantBot:
    """No-op bot for the pipeline test (records nothing, tolerates all)."""

    id = 42

    def __getattr__(self, name):
        async def _noop(*args, **kwargs):
            return SimpleNamespace(
                message_id=1,
                chat=SimpleNamespace(id=args[0] if args else None),
                date=datetime.now(timezone.utc),
            )

        return _noop()


class TextRoleRevealTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._db = root / "t.sqlite3"
        self._audit = root / "audit"
        self._audit.mkdir()
        self._patches = [
            patch("bot.config.get_database_path", return_value=self._db),
            patch(
                "bot.config.get_game_audit_log_dir", return_value=self._audit
            ),
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
        import bot.main as main_mod

        self.main_mod = main_mod
        self._mgr_patches = [
            patch.object(_app_state, "manager", self.manager),
            patch.object(main_mod, "manager", self.manager),
        ]
        for name, mod in list(sys.modules.items()):
            m = getattr(mod, "manager", None)
            if isinstance(m, _GM) and m is not self.manager:
                self._mgr_patches.append(
                    patch.object(mod, "manager", self.manager)
                )
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
        from bot.models import Phase

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
            assert err is None
        seat += 1
        self.manager.add_player(
            game,
            Player(
                user_id=SYN_UID,
                full_name=f"بازیکن {seat}",
                username=None,
                role=None,
                is_alive=True,
                seat=seat,
            ),
        )
        game.phase = Phase.LOBBY
        self.manager.assign_roles(game)
        return game

    def _build(self, game, role):
        from bot.main import build_private_role_message_html

        return build_private_role_message_html(game, role)

    # ------------------------------------------------------------------
    async def test_01_every_role_gets_text_only_header_and_description(self):
        game = self._fork_room()
        from bot.nam10.role_labels import nam10_role_label_fa

        expected_markers = {
            Role.MAFIA_BOSS: "استعلام شما منفی است",
            Role.NATO: "قابلیت ترور شما فعال می‌شود",
            Role.SHIAD: "بی‌اثر کنید",
            Role.DOCTOR: "نجات دهید",
            Role.INTERROGATOR: "هویت شما برای همان بازیکن فاش می‌شود",
            Role.RUINTAN: "مین بگذارید",
            Role.HUNTER: "وارد دفاعیه نخواهد شد",
            Role.DETECTIVE: "زره ضدترور",
            Role.CITIZEN: "قابلیت ویژه شبانه ندارید",
        }
        for role, marker in expected_markers.items():
            html_msg = self._build(game, role)
            self.assertTrue(html_msg.startswith("🎭 نقش شما: <b>"), role)
            self.assertIn(nam10_role_label_fa(role), html_msg, role)
            self.assertIn(marker, html_msg, role)
            # text-only branch: no image hint; the role name AND
            # the description stay behind Telegram spoilers, with
            # nothing readable outside the wrappers
            import re as _re
            self.assertIn("tg-spoiler", html_msg, role)
            outside = _re.sub(
                r"<tg-spoiler>.*?</tg-spoiler>", "", html_msg,
                flags=_re.S,
            )
            self.assertNotIn(nam10_role_label_fa(role), outside, role)
            self.assertNotIn(marker, outside, role)
            self.assertNotIn("کارت نقش", html_msg, role)

    async def test_02_send_private_role_text_only_once_retry_safe(self):
        game = self._fork_room()
        from bot.main import send_private_role
        from bot.nam10.role_labels import nam10_role_description_fa
        from bot.nam10.role_labels import nam10_role_label_fa

        bot = _ParaBot()
        uid = DOC_UID
        role = game.players[uid].role
        for _ in range(3):  # retries must never duplicate the reveal
            ok = await send_private_role(
                bot, uid, game.players[uid].role, game=game
            )
            self.assertTrue(ok)
        body = "\n".join(bot.texts_to(uid))
        self.assertEqual(
            sum(1 for t in bot.texts_to(uid) if "🎭 نقش شما" in t), 1
        )
        # Spoiler-restored format: name and description wrapped.
        self.assertIn("<tg-spoiler>", body)
        self.assertIn(nam10_role_label_fa(role), body)
        self.assertIn(nam10_role_description_fa(role), body)
        self.assertEqual(bot.photos, [])
        self.assertIn(uid, game.private_role_card_delivered_uids)

    async def test_03_no_photo_for_any_namayande10_role(self):
        game = self._fork_room()
        from bot.main import send_private_role

        for uid in REAL_UIDS:
            bot = _ParaBot()
            ok = await send_private_role(
                bot, uid, game.players[uid].role, game=game
            )
            self.assertTrue(ok, uid)
            self.assertEqual(bot.photos, [], uid)
            texts = bot.texts_to(uid)
            self.assertEqual(len(texts), 1, uid)
            self.assertIn("🎭 نقش شما: <b>", texts[0], uid)
            self.assertIn(uid, game.private_role_card_delivered_uids, uid)

    async def test_04_synthetic_seats_never_receive_reveal(self):
        game = self._fork_room()
        from bot.main import send_private_role

        bot = _ParaBot()
        ok = await send_private_role(
            bot, SYN_UID, game.players[SYN_UID].role, game=game
        )
        self.assertTrue(ok)
        self.assertEqual(bot.messages, [])
        self.assertEqual(bot.photos, [])
        self.assertNotIn(SYN_UID, game.private_role_card_delivered_uids)

    async def test_05_unrelated_scenarios_keep_original_delivery(self):
        # classic Namayande (hosted) keeps the spoiler + card default flow
        game_classic = self.manager.create_game(
            host_id=1, scenario_name="namayande", max_players=10
        )
        html_msg = self._build(game_classic, Role.MAFIA_BOSS)
        self.assertIn("tg-spoiler", html_msg)
        self.assertIn("برای دیدن نقش روی نوار خاکستری بزنید", html_msg)
        # ...and does NOT contain the Namayande-10 description text
        self.assertNotIn("استعلام شما منفی است", html_msg)

        # mozakere rooms retain the mozakere spoiler builder
        game_moz = self.manager.create_game(
            host_id=1, scenario_name="mozakere", max_players=7
        )
        html_msg = self._build(game_moz, Role.MAFIA_BOSS)
        self.assertIn("tg-spoiler", html_msg)
        self.assertNotIn("استعلام شما منفی است", html_msg)

    async def test_06_roles_dealt_before_observer_prompt_in_pipeline(self):
        game = self._fork_room()
        game.seats_finalized = True
        events = []

        async def rec_send(bot, uid, role, *, game=None):
            events.append(("role", uid))
            return True

        async def rec_prompt(bot, gm):
            events.append(("observer_prompt", None))

        async def rec_narrator(bot, gm, manager=None):
            events.append(("narrator", None))

        async def rec_notify(bot, gm):
            events.append(("hub", None))

        with patch.object(
            self.main_mod, "send_private_role", rec_send
        ), patch.object(
            self.main_mod, "send_no_host_observer_prompt", rec_prompt
        ), patch.object(
            self.main_mod,
            "begin_narrator_assist_after_roles_dealt",
            rec_narrator,
        ), patch.object(
            self.main_mod, "notify_players_after_roles_dealt", rec_notify
        ):
            result = await self.main_mod.deal_roles_full_pipeline(
                _TolerantBot(), game
            )
        # roles were assigned; every real player got the private reveal and
        # the synthetic seat was skipped entirely
        self.assertIsNone(result)
        role_events = [u for k, u in events if k == "role"]
        self.assertEqual(role_events, REAL_UIDS)
        self.assertNotIn(SYN_UID, role_events)
        # the Observer code prompt happens after every role delivery
        self.assertEqual(events[-1], ("observer_prompt", None))
        self.assertIn(("hub", None), events)
