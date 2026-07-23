"""آینهٔ ناظر: کپی تازه در شب/روز بعد و صندلی مصنوعی."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.models import Player, Role
from bot.observer_delivery import (
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    publish_mirror_prompt_pair,
    update_mirror_prompt_pair,
)


class ObserverMirrorPanelRefreshTest(unittest.IsolatedAsyncioTestCase):
    def _game_with_observer(self) -> tuple:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=100, full_name="Host", username=None)
        )
        game.observer_prompt_status = "registered"
        game.observer_user_id = 300
        return gm, game

    async def test_synthetic_seat_always_mirrors_to_observer(self) -> None:
        _, game = self._game_with_observer()
        bot = AsyncMock()
        with patch(
            "bot.observer_delivery.safe_send_message",
            new_callable=AsyncMock,
        ) as send:
            await deliver_no_host_player_game_copy(
                bot,
                game,
                -920001,
                "پیام صندلی تست",
                is_synthetic_uid=is_synthetic_player_uid,
                parse_mode="HTML",
            )
            self.assertEqual(len(send.call_args_list), 1)
            self.assertEqual(send.call_args_list[0].args[1], 300)

    async def test_fresh_observer_copy_sends_new_message(self) -> None:
        _, game = self._game_with_observer()
        ui_key = mirror_ui_claim_key(game.room_code, "no_host_doctor", -920001)
        game.mirror_prompt_messages[ui_key] = {
            "text": "قدیمی",
            "observer": (300, 111),
        }
        bot = AsyncMock()
        new_msg = MagicMock(message_id=222)
        with patch(
            "bot.observer_delivery.safe_send_message_return",
            new_callable=AsyncMock,
            return_value=new_msg,
        ) as send_ret:
            with patch(
                "bot.observer_delivery._try_edit_mirror_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                await update_mirror_prompt_pair(
                    bot,
                    game,
                    ui_key,
                    "پنل جدید",
                    None,
                    assistant_uid=-920001,
                    fresh_observer_copy=True,
                    parse_mode="HTML",
                )
            send_ret.assert_called_once()
            self.assertEqual(send_ret.call_args.args[1], 300)
            self.assertEqual(
                game.mirror_prompt_messages[ui_key]["observer"],
                (300, 222),
            )

    async def test_publish_existing_ui_key_refreshes_observer(self) -> None:
        _, game = self._game_with_observer()
        ui_key = mirror_ui_claim_key(game.room_code, "no_host_doctor", 200)
        game.mirror_prompt_messages[ui_key] = {
            "text": "شب قبل",
            "player": (200, 10),
            "observer": (300, 20),
        }
        bot = AsyncMock()
        new_msg = MagicMock(message_id=99)
        with patch(
            "bot.observer_delivery.safe_send_message_return",
            new_callable=AsyncMock,
            return_value=new_msg,
        ) as send_ret:
            with patch(
                "bot.observer_delivery._try_edit_mirror_message",
                new_callable=AsyncMock,
                return_value=True,
            ):
                await publish_mirror_prompt_pair(
                    bot,
                    game,
                    200,
                    ui_key,
                    "شب جدید",
                    None,
                    fresh_observer_copy=True,
                    send_player=False,
                    send_observer=True,
                    parse_mode="HTML",
                )
            send_ret.assert_called_once()
            self.assertEqual(
                game.mirror_prompt_messages[ui_key]["observer"],
                (300, 99),
            )


if __name__ == "__main__":
    unittest.main()
