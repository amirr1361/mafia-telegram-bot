"""سیاست اجباری آینهٔ ناظر در مسیر Player-Moderator."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.models import Player, Role
from aiogram.types import ReplyKeyboardRemove

from bot.observer_delivery import (
    _coerce_mirror_delivery,
    _is_mirror_ui_markup,
    close_mirror_prompt_keyboards,
    deliver_no_host_player_game_copy,
    register_mirror_prompt_pair,
)


class NoHostObserverMirrorPolicyTest(unittest.IsolatedAsyncioTestCase):
    def _game_with_observer(self) -> tuple:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.observer_user_id = 300
        game.observer_prompt_status = "registered"
        game.no_host_assistant_narrator_active = True
        return gm, game

    def test_coerce_forces_observer_even_when_caller_says_false(self) -> None:
        _, game = self._game_with_observer()
        sp, so = _coerce_mirror_delivery(
            game, -920001, send_player=False, send_observer=False
        )
        self.assertFalse(sp)
        self.assertTrue(so)

    async def test_register_mirror_preserves_player_ref_on_observer_only(self) -> None:
        _, game = self._game_with_observer()
        bot = AsyncMock()
        ui_key = "11:intro_night_start:100"
        game.mirror_prompt_messages[ui_key] = {
            "text": "قدیم",
            "player": (100, 501),
        }
        with patch(
            "bot.observer_delivery._send_observer_mirror_ref",
            new_callable=AsyncMock,
        ) as obs_send:
            obs_send.return_value = True
            await register_mirror_prompt_pair(
                bot,
                game,
                100,
                ui_key,
                "جدید",
                None,
                send_player=False,
                send_observer=True,
                parse_mode="HTML",
            )
        entry = game.mirror_prompt_messages[ui_key]
        self.assertEqual(entry["text"], "جدید")
        self.assertEqual(entry["player"], (100, 501))
        obs_send.assert_awaited_once()

    async def test_close_mirror_prompt_keyboards_skips_message(self) -> None:
        _, game = self._game_with_observer()
        bot = AsyncMock()
        ui_key = "11:day1_defense_outcome:100"
        game.mirror_prompt_messages[ui_key] = {
            "text": "پنل",
            "player": (100, 501),
            "observer": (300, 601),
        }
        with patch(
            "bot.observer_delivery._edit_remove_keyboard",
            new_callable=AsyncMock,
        ) as rm:
            await close_mirror_prompt_keyboards(
                bot, game, ui_key, skip_message_ids=frozenset({501})
            )
        self.assertEqual(rm.await_count, 1)
        rm.assert_awaited_with(bot, 300, 601)

    async def test_register_mirror_synthetic_sends_only_observer(self) -> None:
        _, game = self._game_with_observer()
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message_return",
            new_callable=AsyncMock,
        ) as send_ret:
            send_ret.return_value = None
            with patch(
                "bot.observer_delivery._send_observer_mirror_ref",
                new_callable=AsyncMock,
            ) as obs_send:
                obs_send.return_value = True
                await register_mirror_prompt_pair(
                    bot,
                    game,
                    -920001,
                    "k:14:-920001",
                    "پنل تست",
                    None,
                    send_player=True,
                    send_observer=False,
                    parse_mode="HTML",
                )
                obs_send.assert_awaited_once()
                for call in send_ret.call_args_list:
                    self.assertNotEqual(call.args[1], -920001)

    def test_reply_keyboard_remove_not_mirror_markup(self) -> None:
        self.assertFalse(_is_mirror_ui_markup(ReplyKeyboardRemove()))
        self.assertFalse(_is_mirror_ui_markup(None))

    async def test_deliver_reply_keyboard_remove_skips_mirror_register(self) -> None:
        _, game = self._game_with_observer()
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            send.return_value = True
            with patch(
                "bot.observer_delivery.register_mirror_prompt_pair",
                new_callable=AsyncMock,
            ) as reg:
                await deliver_no_host_player_game_copy(
                    bot,
                    game,
                    100,
                    "نقش شما",
                    parse_mode="HTML",
                    reply_markup=ReplyKeyboardRemove(),
                )
                reg.assert_not_awaited()
                player_calls = [c for c in send.call_args_list if c.args[1] == 100]
                self.assertEqual(len(player_calls), 1)

    async def test_deliver_synthetic_always_mirrors(self) -> None:
        _, game = self._game_with_observer()
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            await deliver_no_host_player_game_copy(
                bot,
                game,
                -920002,
                "سلام میز",
                is_synthetic_uid=is_synthetic_player_uid,
                parse_mode="HTML",
            )
            self.assertEqual(len(send.call_args_list), 1)
            self.assertEqual(send.call_args_list[0].args[1], 300)


if __name__ == "__main__":
    unittest.main()
