"""ارسال کارت نقش با اسپویلر و تحویل به کمک‌کننده ربات."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.models import Game, Player, Role
from bot.role_cards import role_card_image_path

try:
    import aiogram  # noqa: F401
except ImportError:
    aiogram = None  # type: ignore[assignment]


def _no_host_game() -> Game:
    game = Game(room_code="T01", host_id=1, max_players=10)
    game.narration_mode = "auto"
    game.bazpors_mode = "no_host"
    return game


@unittest.skipUnless(aiogram is not None, "aiogram not installed")
class BuildPrivateRoleMessageHtmlTest(unittest.TestCase):
    def test_with_role_card_mentions_blurred_image(self) -> None:
        from bot.main import build_private_role_message_html

        game = _no_host_game()
        html_msg = build_private_role_message_html(
            game, Role.DETECTIVE, with_role_card=True
        )
        self.assertIn("تصویر محو", html_msg)
        self.assertIn("tg-spoiler", html_msg)

    def test_without_role_card_uses_text_only_hint(self) -> None:
        from bot.main import build_private_role_message_html

        game = _no_host_game()
        html_msg = build_private_role_message_html(
            game, Role.HUNTER, with_role_card=False
        )
        self.assertNotIn("تصویر محو", html_msg)
        self.assertIn("نوار خاکستری", html_msg)


@unittest.skipUnless(aiogram is not None, "aiogram not installed")
class SendPrivateRoleSpoilerTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_photo_uses_has_spoiler(self) -> None:
        from bot.main import send_private_role

        game = _no_host_game()
        game.players[42] = Player(
            user_id=42, full_name="p", username="p", role=Role.DETECTIVE, seat=1
        )
        bot = MagicMock()
        bot.send_photo = AsyncMock(return_value=MagicMock(message_id=1))
        path = role_card_image_path(Role.DETECTIVE)
        self.assertIsNotNone(path)
        with patch("bot.tg_send.safe_send_photo_return", new_callable=AsyncMock) as send:
            send.return_value = MagicMock(message_id=1)
            ok = await send_private_role(bot, 42, Role.DETECTIVE, game=game)
        self.assertTrue(ok)
        send.assert_awaited_once()
        self.assertTrue(send.await_args.kwargs.get("has_spoiler"))
        self.assertIn(42, game.private_role_card_delivered_uids)


@unittest.skipUnless(aiogram is not None, "aiogram not installed")
class EnsurePrivateRoleCardDeliveredTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_already_delivered(self) -> None:
        from bot.main import ensure_private_role_card_delivered

        game = _no_host_game()
        game.private_role_card_delivered_uids.add(7)
        game.players[7] = Player(
            user_id=7, full_name="a", username="a", role=Role.CITIZEN, seat=1
        )
        bot = MagicMock()
        with patch("bot.main.send_private_role", new_callable=AsyncMock) as send:
            await ensure_private_role_card_delivered(bot, game, 7)
        send.assert_not_awaited()

    async def test_resends_when_missing(self) -> None:
        from bot.main import ensure_private_role_card_delivered

        game = _no_host_game()
        game.players[8] = Player(
            user_id=8, full_name="b", username="b", role=Role.NATO, seat=2
        )
        bot = MagicMock()
        with patch("bot.main.send_private_role", new_callable=AsyncMock) as send:
            send.return_value = True
            await ensure_private_role_card_delivered(bot, game, 8)
        send.assert_awaited_once_with(bot, 8, Role.NATO, game=game)

    async def test_skips_when_mozakere_text_role_already_delivered(self) -> None:
        from bot.main import ensure_private_role_card_delivered

        game = _no_host_game()
        game.scenario_name = "mozakere"
        game.players[8] = Player(
            user_id=8, full_name="b", username="b", role=Role.DOCTOR, seat=2
        )
        game.private_role_card_delivered_uids.add(8)
        bot = MagicMock()
        with patch("bot.main.send_private_role", new_callable=AsyncMock) as send:
            await ensure_private_role_card_delivered(bot, game, 8)
        send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
