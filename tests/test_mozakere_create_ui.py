"""مسیر UI ساخت اتاق سناریوی مذاکره."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.enums import ChatType

from bot.game import (
    BAZPORS_PLAYER_COUNTS,
    MOZAKERE_PLAYER_COUNTS,
    GameManager,
    mozakere_roles_for_count,
    role_roster_banner_text,
)
from bot.handlers.lobby import cb_create_host_mode, cb_create_players
from bot.main import (
    CreatePickHostMode,
    CreatePickPlayers,
    MOZAKERE_HOST_MODE_STUB_HTML,
    bazpors_host_mode_prompt_html,
    player_count_keyboard,
    scenario_menu_keyboard,
)


def _player_count_buttons(slug: str) -> list[tuple[int, str]]:
    kb = player_count_keyboard(slug)
    out: list[tuple[int, str]] = []
    for row in kb.inline_keyboard:
        for btn in row:
            data = CreatePickPlayers.unpack(btn.callback_data)
            out.append((data.count, btn.text))
    return out


class MozakereCreateUiTests(unittest.TestCase):
    def test_scenario_menu_includes_mozakere(self) -> None:
        labels = [
            btn.text
            for row in scenario_menu_keyboard().inline_keyboard
            for btn in row
        ]
        self.assertIn("💬 مذاکره", labels)

    def test_mozakere_player_counts_include_15_not_bazpors(self) -> None:
        self.assertEqual(MOZAKERE_PLAYER_COUNTS, frozenset({10, 11, 12, 13, 15}))
        self.assertEqual(BAZPORS_PLAYER_COUNTS, frozenset({10, 11, 12, 13}))
        moz = {n for n, _ in _player_count_buttons("mozakere")}
        baz = {n for n, _ in _player_count_buttons("bazpors")}
        self.assertEqual(moz, {10, 11, 12, 13, 15})
        self.assertEqual(baz, {10, 11, 12, 13})
        self.assertNotIn(15, baz)

    def test_mozakere_roles_for_all_counts(self) -> None:
        for n, mafia_n, town_n in (
            (10, 3, 7),
            (11, 3, 8),
            (12, 4, 8),
            (13, 4, 9),
            (15, 4, 11),
        ):
            roles = mozakere_roles_for_count(n)
            self.assertEqual(len(roles), n, n)
            mafia = sum(1 for r in roles if r.name.startswith("MAFIA"))
            town = n - mafia
            self.assertEqual(mafia, mafia_n, n)
            self.assertEqual(town, town_n, n)

    def test_mozakere_roster_labels_12p(self) -> None:
        gm = GameManager()
        plain = role_roster_banner_text("mozakere", 12, gm)
        for label in (
            "مافیا ساده دوم",
            "تک تیرانداز",
            "مذاکره کننده",
        ):
            self.assertIn(label, plain)
        self.assertIn("۱۲", plain)

    def test_mozakere_roster_labels_15p(self) -> None:
        gm = GameManager()
        plain = role_roster_banner_text("mozakere", 15, gm)
        self.assertEqual(plain.count("شهروند ساده"), 6)
        self.assertIn("۱۵", plain)


class MozakereCreateHandlerTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_no_host_creates_room_for_each_count(self) -> None:
        for count in (10, 11, 12, 13, 15):
            with self.subTest(count=count):
                cb = self._private_callback(uid=8000 + count)
                bot = MagicMock()
                bot.get_me = AsyncMock(return_value=MagicMock(username="testbot"))
                data = CreatePickHostMode(slug="mozakere", count=count, mode="no_host")
                gm = GameManager()
                with patch("bot.handlers.lobby.manager", gm):
                    await cb_create_host_mode(cb, data, bot)

                self.assertEqual(len(gm.games), 1)
                game = next(iter(gm.games.values()))
                self.assertEqual(game.scenario_name, "mozakere")
                self.assertEqual(game.max_players, count)
                text = cb.message.edit_text.await_args.args[0]
                self.assertIn("مذاکره", text)
                self.assertIn("اتاق ساخته شد", text)
                gm.games.clear()
                gm.host_to_room.clear()
                gm.player_to_room.clear()

    async def test_semi_auto_still_stub_for_mozakere(self) -> None:
        cb = self._private_callback()
        bot = MagicMock()
        data = CreatePickHostMode(slug="mozakere", count=15, mode="semi_auto")
        gm = GameManager()
        with patch("bot.handlers.lobby.manager", gm):
            await cb_create_host_mode(cb, data, bot)

        self.assertEqual(len(gm.games), 0)
        self.assertIn(MOZAKERE_HOST_MODE_STUB_HTML, cb.message.edit_text.await_args.args[0])

    async def test_bazpors_host_mode_still_creates_game(self) -> None:
        cb = self._private_callback(uid=9002)
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


if __name__ == "__main__":
    unittest.main()
