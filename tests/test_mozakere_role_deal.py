"""پخش نقش‌های تصادفی — سناریوی مذاکره."""

from __future__ import annotations

import unittest
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import (
    GameManager,
    MOZAKERE_ROLE_LABELS_FA,
    bazpors_roles_for_count,
    mozakere_roles_for_count,
    scenario_role_label_fa,
)
from bot.models import Phase, Player, Role
from bot.mozakere_role_descriptions import (
    MOZAKERE_ROLE_DESCRIPTIONS_FA,
    mozakere_role_description_fa,
)
from bot.roles.registry import BAZPORS_SCENARIO_ROLES
from bot.room_mode import narrator_assist_after_roles_dealt


def _mozakere_lobby_ready(gm: GameManager, *, n: int, host_id: int = 9001):
    game = gm.create_game(
        host_id=host_id,
        scenario_name="mozakere",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    gm.add_player(game, Player(user_id=host_id, full_name="Host", username=None))
    gm.fill_no_host_synthetic_lobby(game)
    gm.prepare_shuffle(game)
    gm.confirm_shuffle(game)
    return game


class MozakereRoleAssignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_assign_roles_for_all_mozakere_counts(self) -> None:
        expected_lengths = {10: 10, 11: 11, 12: 12, 13: 13, 15: 15}
        for n, length in expected_lengths.items():
            with self.subTest(players=n):
                game = _mozakere_lobby_ready(self.gm, n=n, host_id=8000 + n)
                self.gm.assign_roles(game)
                dealt = [p.role for p in game.players.values()]
                expected = mozakere_roles_for_count(n)
                self.assertEqual(len(dealt), length)
                self.assertEqual(Counter(dealt), Counter(expected))
                self.assertFalse(set(dealt) & (BAZPORS_SCENARIO_ROLES - set(expected)))
                self.gm.games.clear()
                self.gm.host_to_room.clear()
                self.gm.player_to_room.clear()

    def test_mozakere_state_reset_on_assign(self) -> None:
        game = _mozakere_lobby_ready(self.gm, n=10)
        game.mozakere_negotiation_used = True
        game.mozakere_mafia_recruit_ids.add(99)
        game.mozakere_sniper_shots_used = 2
        self.gm.assign_roles(game)
        self.assertFalse(game.mozakere_negotiation_used)
        self.assertEqual(game.mozakere_mafia_recruit_ids, set())
        self.assertEqual(game.mozakere_sniper_shots_used, 0)
        for p in game.players.values():
            self.assertFalse(p.mozakere_armored_armor_used)
            self.assertFalse(p.mozakere_converted_by_negotiation)

    def test_bazpors_assign_unchanged(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.gm.add_player(game, Player(1, "H", None))
        self.gm.fill_bazpors_semi_auto_synthetic_lobby(game)
        self.gm.prepare_shuffle(game)
        self.gm.confirm_shuffle(game)
        self.gm.assign_roles(game)
        dealt = {p.role for p in game.players.values()}
        self.assertEqual(dealt, set(bazpors_roles_for_count(10)))
        moz_only = {Role.JOURNALIST, Role.MAFIA_NEGOTIATOR, Role.ARMORED}
        self.assertFalse(dealt & moz_only)


class MozakereRoleLabelTests(unittest.TestCase):
    def _mozakere_no_host_game(self):
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        return game

    def test_private_role_labels_use_mozakere_names(self) -> None:
        from bot.main import build_private_role_message_html

        game = self._mozakere_no_host_game()
        html_neg = build_private_role_message_html(
            game, Role.MAFIA_NEGOTIATOR, with_role_card=False
        )
        self.assertIn("مذاکره کننده", html_neg)
        self.assertNotIn("مذاکره‌کننده", html_neg)
        html_arm = build_private_role_message_html(
            game, Role.ARMORED, with_role_card=False
        )
        self.assertIn("زره پوش", html_arm)

    def test_private_role_message_is_text_only_with_spoilers(self) -> None:
        from bot.main import build_private_role_message_html

        game = self._mozakere_no_host_game()
        html_msg = build_private_role_message_html(
            game, Role.DOCTOR, with_role_card=False
        )
        self.assertIn("🎭 نقش شما:", html_msg)
        self.assertIn("بازی بدون گرداننده برگزار می‌شود.", html_msg)
        self.assertIn("درباره نقش شما:", html_msg)
        self.assertIn("tg-spoiler", html_msg)
        self.assertIn("پزشک", html_msg)
        self.assertIn("بر اساس تعداد بازیکنان زنده", html_msg)
        self.assertNotIn("شب‌های اول تا سوم", html_msg)
        self.assertNotIn("تصویر محو", html_msg)
        self.assertNotIn("نوار خاکستری", html_msg)
        self.assertEqual(html_msg.count("<tg-spoiler>"), 2)

    def test_each_mozakere_role_has_description(self) -> None:
        from bot.main import build_private_role_message_html

        game = self._mozakere_no_host_game()
        for role in MOZAKERE_ROLE_LABELS_FA:
            with self.subTest(role=role.value):
                desc = mozakere_role_description_fa(role)
                self.assertTrue(desc, msg=f"missing description for {role}")
                self.assertEqual(desc, MOZAKERE_ROLE_DESCRIPTIONS_FA[role])
                html_msg = build_private_role_message_html(game, role)
                self.assertIn(
                    scenario_role_label_fa(game, role),
                    html_msg,
                )
                self.assertIn(desc, html_msg)

    def test_scenario_role_label_fa(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
        )
        assert game is not None
        self.assertEqual(
            scenario_role_label_fa(game, Role.SNIPER),
            "تک تیرانداز",
        )


class MozakereDealPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_deal_pipeline_mozakere_no_host(self) -> None:
        from bot.main import deal_roles_full_pipeline

        gm = GameManager()
        game = _mozakere_lobby_ready(gm, n=12)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="bot"))
        with (
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)),
            patch(
                "bot.main.send_no_host_observer_prompt",
                new=AsyncMock(),
            ) as obs,
            patch(
                "bot.main.begin_narrator_assist_after_roles_dealt",
                new=AsyncMock(),
            ) as narr,
        ):
            err = await deal_roles_full_pipeline(bot, game)
        self.assertIsNone(err)
        self.assertTrue(game.roles_dealt)
        self.assertEqual(game.phase, Phase.MANUAL)
        obs.assert_awaited_once()
        narr.assert_not_awaited()
        roles = {p.role for p in game.players.values()}
        self.assertEqual(roles, set(mozakere_roles_for_count(12)))

    def test_narrator_assist_flag_mozakere_semi_auto_only(self) -> None:
        gm = GameManager()
        moz_no = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert moz_no is not None
        self.assertFalse(narrator_assist_after_roles_dealt(moz_no))
        moz_semi = gm.create_game(
            host_id=2,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert moz_semi is not None
        self.assertTrue(narrator_assist_after_roles_dealt(moz_semi))


class MozakereRoleDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_mozakere_send_private_role_uses_text_not_photo(self) -> None:
        from bot.main import send_private_role

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.players[42] = Player(
            user_id=42, full_name="p", username="p", role=Role.DOCTOR, seat=1
        )
        bot = MagicMock()
        with (
            patch("bot.main.safe_send_message", new_callable=AsyncMock) as send_msg,
            patch("bot.tg_send.safe_send_photo_return", new_callable=AsyncMock) as send_photo,
        ):
            send_msg.return_value = True
            ok = await send_private_role(bot, 42, Role.DOCTOR, game=game)
        self.assertTrue(ok)
        send_msg.assert_awaited_once()
        send_photo.assert_not_awaited()
        caption = send_msg.await_args.args[2]
        self.assertIn("درباره نقش شما:", caption)
        self.assertIn("tg-spoiler", caption)
        self.assertIn(42, game.private_role_card_delivered_uids)

    async def test_send_private_role_is_idempotent(self) -> None:
        from bot.main import send_private_role

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.players[42] = Player(
            user_id=42, full_name="p", username="p", role=Role.DOCTOR, seat=1
        )
        bot = MagicMock()
        with patch("bot.main.safe_send_message", new_callable=AsyncMock) as send_msg:
            send_msg.return_value = True
            ok1 = await send_private_role(bot, 42, Role.DOCTOR, game=game)
            ok2 = await send_private_role(bot, 42, Role.DOCTOR, game=game)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        send_msg.assert_awaited_once()

    async def test_bazpors_send_private_role_still_uses_photo(self) -> None:
        from bot.main import send_private_role
        from bot.role_cards import role_card_image_path

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.players[42] = Player(
            user_id=42, full_name="p", username="p", role=Role.DETECTIVE, seat=1
        )
        self.assertIsNotNone(role_card_image_path(Role.DETECTIVE))
        bot = MagicMock()
        with (
            patch("bot.main.safe_send_message", new_callable=AsyncMock) as send_msg,
            patch("bot.tg_send.safe_send_photo_return", new_callable=AsyncMock) as send_photo,
        ):
            send_photo.return_value = MagicMock(message_id=1)
            ok = await send_private_role(bot, 42, Role.DETECTIVE, game=game)
        self.assertTrue(ok)
        send_photo.assert_awaited_once()
        send_msg.assert_not_awaited()
        self.assertIn(42, game.private_role_card_delivered_uids)
        caption = send_photo.await_args.kwargs.get("caption") or send_photo.await_args.args[2]
        self.assertIn("تصویر محو", caption)


class MozakereRoleDealIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_deal_once_then_retry_sends_roles_once_per_player(self) -> None:
        from bot.main import deal_roles_full_pipeline

        gm = GameManager()
        game = gm.create_game(
            host_id=9001,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(user_id=9001, full_name="Host", username="host"))
        gm.add_player(game, Player(user_id=9002, full_name="B", username="b"))
        gm.add_player(game, Player(user_id=9003, full_name="C", username="c"))
        gm.fill_no_host_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="bot"))
        send_log: list[int] = []

        async def _track_send(_bot, user_id, _role, game=None):
            send_log.append(user_id)
            return True

        with (
            patch("bot.main.send_private_role", side_effect=_track_send),
            patch("bot.main.send_no_host_observer_prompt", new=AsyncMock()),
        ):
            err1 = await deal_roles_full_pipeline(bot, game)
            err2 = await deal_roles_full_pipeline(bot, game)

        self.assertIsNone(err1)
        self.assertEqual(err2, "نقش‌ها قبلاً پخش شده‌اند.")
        self.assertTrue(game.roles_dealt)
        self.assertEqual(send_log, [9001, 9002, 9003])
        self.assertEqual(len(game.private_role_card_delivered_uids), 0)

    async def test_bot_assistant_finalize_does_not_resend_role(self) -> None:
        from bot.main import deal_roles_full_pipeline, finalize_no_host_bot_assistant

        gm = GameManager()
        game = gm.create_game(
            host_id=9001,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(user_id=9001, full_name="Host", username="host"))
        gm.add_player(game, Player(user_id=9002, full_name="B", username="b"))
        gm.fill_no_host_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="bot"))
        send_log: list[int] = []

        async def _track_send(_bot, user_id, _role, game=None):
            send_log.append(user_id)
            if game is not None:
                game.private_role_card_delivered_uids.add(user_id)
            return True

        with (
            patch("bot.main.send_private_role", side_effect=_track_send),
            patch("bot.main.send_no_host_observer_prompt", new=AsyncMock()),
            patch("bot.main.send_to_player", new=AsyncMock(return_value=True)),
            patch("bot.main.broadcast_to_players", new=AsyncMock()),
            patch("bot.main.send_no_host_intro_night_start_prompt", new=AsyncMock()),
        ):
            err = await deal_roles_full_pipeline(bot, game)
            self.assertIsNone(err)
            send_log.clear()
            await finalize_no_host_bot_assistant(bot, game, 9002, random_pick=False)

        self.assertEqual(send_log, [])


class BazporsRoleDealIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_bazpors_deal_retry_does_not_resend_roles(self) -> None:
        from bot.main import deal_roles_full_pipeline

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(user_id=1, full_name="Host", username="host"))
        gm.fill_bazpors_no_host_synthetic_lobby(game)
        gm.prepare_shuffle(game)
        gm.confirm_shuffle(game)
        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(username="bot"))
        send_log: list[int] = []

        async def _track_send(_bot, user_id, _role, game=None):
            send_log.append(user_id)
            if game is not None:
                game.private_role_card_delivered_uids.add(user_id)
            return True

        with (
            patch("bot.main.send_private_role", side_effect=_track_send),
            patch("bot.main.send_no_host_observer_prompt", new=AsyncMock()),
        ):
            err1 = await deal_roles_full_pipeline(bot, game)
            err2 = await deal_roles_full_pipeline(bot, game)

        self.assertIsNone(err1)
        self.assertEqual(err2, "نقش‌ها قبلاً پخش شده‌اند.")
        self.assertEqual(send_log.count(1), 1)


if __name__ == "__main__":
    unittest.main()
