"""مسیر UI ساخت اتاق سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.enums import ChatType

from bot.game import (
    BAZPORS_PLAYER_COUNTS,
    MASOON_PLAYER_COUNTS,
    GameManager,
    role_roster_banner_text,
)
from bot.handlers.lobby import cb_create_host_mode, cb_create_players
from bot.main import (
    CreatePickHostMode,
    CreatePickPlayers,
    MOZAKERE_HOST_MODE_STUB_HTML,
    bazpors_host_mode_prompt_html,
    build_no_host_intro_night_start_html,
    finalize_no_host_bot_assistant,
    player_count_keyboard,
)
from bot.mason_create_flow import (
    MASON_HOST_MODE_STUB_HTML,
    mason_host_mode_keyboard,
    mason_host_mode_prompt_html,
)
from bot.models import Player
from bot.room_mode import is_mason_no_host_room, is_no_host_player_room


def _player_count_buttons(slug: str) -> list[tuple[int, str]]:
    kb = player_count_keyboard(slug)
    out: list[tuple[int, str]] = []
    for row in kb.inline_keyboard:
        for btn in row:
            data = CreatePickPlayers.unpack(btn.callback_data)
            out.append((data.count, btn.text))
    return out


class MasonCreateUiTests(unittest.TestCase):
    def test_mason_player_counts(self) -> None:
        self.assertEqual(MASOON_PLAYER_COUNTS, frozenset(range(12, 19)))
        mason = {n for n, _ in _player_count_buttons("masoon")}
        self.assertEqual(mason, MASOON_PLAYER_COUNTS)
        self.assertNotEqual(mason, BAZPORS_PLAYER_COUNTS)

    def test_host_mode_prompt_uses_mason_label(self) -> None:
        gm = GameManager()
        label = gm.scenario_display_name("masoon")
        self.assertEqual(label, "ماسون")
        html_msg = mason_host_mode_prompt_html(label, 12)
        self.assertIn("ماسون", html_msg)
        self.assertIn("۱۲", html_msg)
        self.assertEqual(
            mason_host_mode_prompt_html(label, 12),
            bazpors_host_mode_prompt_html(label, 12),
        )

    def test_host_mode_keyboard_has_three_buttons(self) -> None:
        labels = [
            btn.text
            for row in mason_host_mode_keyboard("masoon", 12).inline_keyboard
            for btn in row
        ]
        self.assertEqual(
            labels,
            [
                "گردانندگی خودکار مستقل",
                "بازیکن گرداننده",
                "گردانندگی دستی",
            ],
        )

    def test_mason_roster_labels_12p(self) -> None:
        gm = GameManager()
        plain = role_roster_banner_text("masoon", 12, gm)
        self.assertIn("گادفادر", plain)
        self.assertIn("پزشک", plain)
        self.assertIn("۱۲", plain)


class MasonCreateHandlerTests(unittest.IsolatedAsyncioTestCase):
    def _private_callback(self, *, uid: int = 9001) -> MagicMock:
        cb = MagicMock()
        cb.from_user = MagicMock()
        cb.from_user.id = uid
        cb.from_user.full_name = "Host"
        cb.from_user.username = None
        cb.message = MagicMock()
        cb.message.chat = MagicMock()
        cb.message.chat.type = ChatType.PRIVATE
        cb.message.edit_text = AsyncMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        return cb

    async def test_player_count_shows_host_mode_panel(self) -> None:
        cb = self._private_callback()
        data = CreatePickPlayers(slug="masoon", count=12)
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_players(cb, data, MagicMock())

        self.assertEqual(len(gm.games), 0)
        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("ماسون", text)
        self.assertIn("۱۲", text)
        kb = cb.message.edit_text.await_args.kwargs.get("reply_markup")
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(len(labels), 3)

    async def test_semi_auto_stub_does_not_create_room(self) -> None:
        cb = self._private_callback()
        data = CreatePickHostMode(slug="masoon", count=12, mode="semi_auto")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, MagicMock())

        self.assertEqual(len(gm.games), 0)
        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("ماسون", text)
        self.assertIn(MASON_HOST_MODE_STUB_HTML, text)

    async def test_manual_creates_room_like_old_flow(self) -> None:
        cb = self._private_callback(uid=9100)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
        data = CreatePickHostMode(slug="masoon", count=12, mode="manual")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, bot)

        self.assertEqual(len(gm.games), 1)
        game = next(iter(gm.games.values()))
        self.assertEqual(game.scenario_name, "masoon")
        self.assertEqual(game.max_players, 12)
        self.assertIsNone(game.bazpors_host_mode)
        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("اتاق ساخته شد", text)
        self.assertIn("ماسون", text)

    async def test_no_host_creates_player_host_room(self) -> None:
        cb = self._private_callback(uid=9200)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
        data = CreatePickHostMode(slug="masoon", count=12, mode="no_host")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, bot)

        self.assertEqual(len(gm.games), 1)
        game = next(iter(gm.games.values()))
        self.assertEqual(game.scenario_name, "masoon")
        self.assertEqual(game.bazpors_host_mode, "no_host")
        self.assertTrue(is_mason_no_host_room(game))
        self.assertTrue(is_no_host_player_room(game))
        self.assertIn(9200, game.players)
        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("بازیکن گرداننده", text)
        self.assertIn("اتاق ساخته شد", text)

    async def test_no_host_reaches_intro_night_start_prompt(self) -> None:
        from bot.main import deal_roles_full_pipeline

        gm = GameManager()
        game = gm.create_game(
            host_id=9300,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=9300, full_name="Host", username="host")
        )
        gm.add_player(game, Player(user_id=9301, full_name="B", username="b"))
        gm.fill_no_host_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="bot"))
        intro_prompt = AsyncMock()

        async def _track_send(_bot, user_id, _role, game=None):
            if game is not None:
                game.private_role_card_delivered_uids.add(user_id)
            return True

        with (
            patch("bot.main.send_private_role", side_effect=_track_send),
            patch("bot.main.send_no_host_observer_prompt", new=AsyncMock()),
            patch("bot.main.send_to_player", new=AsyncMock(return_value=True)),
            patch("bot.main.broadcast_to_players", new=AsyncMock()),
            patch(
                "bot.main.ensure_private_role_card_delivered",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "bot.main.send_no_host_intro_night_start_prompt",
                new=intro_prompt,
            ),
        ):
            err = await deal_roles_full_pipeline(bot, game)
            self.assertIsNone(err)
            await finalize_no_host_bot_assistant(bot, game, 9301, random_pick=False)

        intro_prompt.assert_awaited_once_with(bot, game)
        self.assertIn("شروع شب معارفه", build_no_host_intro_night_start_html())


class BazporsMozakereRegressionTests(unittest.IsolatedAsyncioTestCase):
    def _private_callback(self, *, uid: int = 9002) -> MagicMock:
        cb = MagicMock()
        cb.from_user = MagicMock()
        cb.from_user.id = uid
        cb.from_user.full_name = "Host"
        cb.from_user.username = None
        cb.message = MagicMock()
        cb.message.chat = MagicMock()
        cb.message.chat.type = ChatType.PRIVATE
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        return cb

    async def test_bazpors_player_count_still_shows_host_mode(self) -> None:
        cb = self._private_callback()
        data = CreatePickPlayers(slug="bazpors", count=10)
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_players(cb, data, MagicMock())

        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("بازپرس", text)
        self.assertEqual(len(gm.games), 0)

    async def test_bazpors_manual_still_creates_game(self) -> None:
        cb = self._private_callback(uid=9003)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
        data = CreatePickHostMode(slug="bazpors", count=10, mode="manual")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, bot)

        self.assertEqual(len(gm.games), 1)
        game = next(iter(gm.games.values()))
        self.assertEqual(game.scenario_name, "bazpors")
        self.assertEqual(game.bazpors_host_mode, "manual")

    async def test_mozakere_semi_auto_still_stub(self) -> None:
        cb = self._private_callback()
        data = CreatePickHostMode(slug="mozakere", count=15, mode="semi_auto")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, MagicMock())

        self.assertEqual(len(gm.games), 0)
        self.assertIn(
            MOZAKERE_HOST_MODE_STUB_HTML,
            cb.message.edit_text.await_args.args[0],
        )

    async def test_mozakere_no_host_still_creates_game(self) -> None:
        cb = self._private_callback(uid=9004)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
        data = CreatePickHostMode(slug="mozakere", count=10, mode="no_host")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, bot)

        self.assertEqual(len(gm.games), 1)
        game = next(iter(gm.games.values()))
        self.assertEqual(game.scenario_name, "mozakere")
