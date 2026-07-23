"""تست پیام پخش نقش — سناریوی ماسون."""

from __future__ import annotations

import html
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.main import build_private_role_message_html, send_private_role
from bot.mason_role_descriptions import (
    MASON_CARD_HINT_TEXT,
    MASON_ROLE_DESCRIPTIONS_FA,
    mason_role_description_fa,
)
from bot.mason_roles import MASON_PLAYER_COUNTS, masoon_roles_for_count
from bot.models import Game, Player, Role


def _mason_game(*, no_host: bool = True) -> Game:
    game = Game(
        room_code="MS01",
        host_id=1,
        scenario_name="masoon",
        max_players=12,
        players={},
    )
    if no_host:
        game.bazpors_host_mode = "no_host"
    return game


class MasonRoleDeliveryTests(unittest.TestCase):
    def test_each_mason_role_has_description(self) -> None:
        roles = set()
        for n in MASON_PLAYER_COUNTS:
            roles.update(masoon_roles_for_count(n))
        self.assertEqual(roles, set(MASON_ROLE_DESCRIPTIONS_FA))
        for role in roles:
            with self.subTest(role=role):
                desc = mason_role_description_fa(role)
                self.assertTrue(desc.startswith("🎭 نقش شما:"))
                self.assertGreater(len(desc), 40)

    def test_message_is_fully_spoilered(self) -> None:
        game = _mason_game()
        html_msg = build_private_role_message_html(game, Role.SNIPER)
        self.assertTrue(html_msg.startswith("<tg-spoiler>"))
        self.assertTrue(html_msg.endswith("</tg-spoiler>"))
        self.assertEqual(html_msg.count("<tg-spoiler>"), 1)
        self.assertEqual(html_msg.count("</tg-spoiler>"), 1)

    def test_message_contains_full_description(self) -> None:
        game = _mason_game()
        role = Role.GODFATHER
        html_msg = build_private_role_message_html(game, role)
        plain = html.unescape(
            html_msg.removeprefix("<tg-spoiler>").removesuffix("</tg-spoiler>")
        )
        self.assertEqual(plain, mason_role_description_fa(role))
        self.assertIn("گادفادر", plain)
        self.assertIn("استعلام شما برای کارآگاه", plain)

    def test_no_old_card_hint_text(self) -> None:
        game = _mason_game()
        for role in (Role.SNIPER, Role.DOCTOR, Role.MASON):
            with self.subTest(role=role):
                html_msg = build_private_role_message_html(game, role)
                self.assertNotIn(MASON_CARD_HINT_TEXT, html_msg)
                self.assertNotIn("تصویر محو", html_msg)
                self.assertNotIn("نوار خاکستری", html_msg)
                self.assertNotIn("بازی بدون گرداننده", html_msg)

    def test_mason_doctor_description_alive_capacity_rules(self) -> None:
        desc = mason_role_description_fa(Role.DOCTOR)
        self.assertIn("بر اساس تعداد بازیکنان زنده", desc)
        self.assertIn("۷ نفر یا کمتر زنده باشند ۱ نفر", desc)
        self.assertIn("۸ تا ۱۱ نفر زنده باشند ۲ نفر", desc)
        self.assertIn("۱۲ تا ۱۵ نفر زنده باشند ۳ نفر", desc)
        self.assertIn("۱۶ نفر یا بیشتر زنده باشند ۴ نفر", desc)
        self.assertIn("فقط دو بار اجازه نجات خودش را دارد", desc)
        self.assertNotIn("تا ۸ نفر: یک نجات", desc)
        self.assertNotIn("تا ۱۲ نفر: دو نجات", desc)

    def test_mason_doctor_description_in_spoilered_delivery(self) -> None:
        game = _mason_game()
        html_msg = build_private_role_message_html(game, Role.DOCTOR)
        plain = html.unescape(
            html_msg.removeprefix("<tg-spoiler>").removesuffix("</tg-spoiler>")
        )
        self.assertEqual(plain, mason_role_description_fa(Role.DOCTOR))


class MasonSendPrivateRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_mason_uses_text_not_photo(self) -> None:
        game = _mason_game()
        game.players[42] = Player(
            user_id=42, full_name="p", username="p", role=Role.SNIPER, seat=1
        )
        bot = MagicMock()
        with (
            patch("bot.main.safe_send_message", new_callable=AsyncMock) as send_msg,
            patch("bot.tg_send.safe_send_photo_return", new_callable=AsyncMock) as send_photo,
        ):
            send_msg.return_value = True
            ok = await send_private_role(bot, 42, Role.SNIPER, game=game)
        self.assertTrue(ok)
        send_msg.assert_awaited_once()
        send_photo.assert_not_awaited()
        caption = send_msg.await_args.args[2]
        self.assertTrue(caption.startswith("<tg-spoiler>"))


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_bazpors_still_uses_card_hint(self) -> None:
        game = Game(
            room_code="BZ01",
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            players={},
        )
        game.bazpors_host_mode = "no_host"
        html_msg = build_private_role_message_html(
            game, Role.SHIAD, with_role_card=True
        )
        self.assertIn("تصویر محو", html_msg)
        self.assertIn("بازی بدون گرداننده", html_msg)

    def test_bazpors_doctor_description_unchanged(self) -> None:
        game = Game(
            room_code="BZ03",
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            players={},
        )
        game.bazpors_host_mode = "no_host"
        html_msg = build_private_role_message_html(
            game, Role.DOCTOR, with_role_card=True
        )
        self.assertIn("تصویر محو", html_msg)
        self.assertNotIn("بر اساس تعداد بازیکنان زنده", html_msg)
        self.assertNotIn("تا ۸ نفر: یک نجات", html_msg)

    def test_mozakere_still_uses_partial_spoilers(self) -> None:
        game = Game(
            room_code="MZ01",
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            players={},
        )
        game.bazpors_host_mode = "no_host"
        html_msg = build_private_role_message_html(game, Role.DOCTOR)
        self.assertIn("درباره نقش شما:", html_msg)
        self.assertIn("بازی بدون گرداننده", html_msg)
        self.assertGreater(html_msg.count("<tg-spoiler>"), 1)


class BazporsSendPhotoRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bazpors_send_still_uses_photo(self) -> None:
        from bot.main import send_private_role

        game = Game(
            room_code="BZ02",
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            players={
                42: Player(42, "p", "p", Role.DETECTIVE, seat=1),
            },
        )
        bot = MagicMock()
        with (
            patch("bot.tg_send.safe_send_photo_return", new_callable=AsyncMock) as send_photo,
            patch("bot.main.safe_send_message", new_callable=AsyncMock) as send_msg,
            patch("bot.role_cards.role_card_image_path", return_value="/tmp/x.png"),
        ):
            send_photo.return_value = MagicMock(message_id=1)
            ok = await send_private_role(bot, 42, Role.DETECTIVE, game=game)
        self.assertTrue(ok)
        send_photo.assert_awaited_once()
        send_msg.assert_not_awaited()
