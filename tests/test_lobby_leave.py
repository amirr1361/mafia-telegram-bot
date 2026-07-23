"""خروج از لابی قبل از پخش نقش."""

from __future__ import annotations

import unittest

from bot.game import (
    GameManager,
    LOBBY_FULL_READY_FOR_ROLES_MSG,
    LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG,
    LOBBY_NOT_FULL_FOR_ROLES_MSG,
    reset_lobby_seats_after_roster_change,
)
from bot.main import build_lobby_join_status_text, build_seat_assignment_player_message
from bot.models import Phase, Player


class LobbyLeaveTests(unittest.TestCase):
    _host_seq = 2000

    def setUp(self) -> None:
        self.gm = GameManager()

    def _game(self, *, max_players: int = 10) -> tuple[str, object]:
        LobbyLeaveTests._host_seq += 1
        host_id = LobbyLeaveTests._host_seq
        game = self.gm.create_game(
            host_id=host_id,
            scenario_name="bazpors",
            max_players=max_players,
        )
        assert game is not None
        return game.room_code, game

    def test_player_can_leave_before_roles(self) -> None:
        code, game = self._game()
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=20, full_name="B", username=None)
        )
        order_before = list(game.players.keys())
        self.assertTrue(self.gm.remove_player_from_lobby(game, 10))
        self.assertNotIn(10, game.players)
        self.assertEqual(list(game.players.keys()), [20])
        self.assertEqual(code, game.room_code)
        self.assertEqual(order_before[1:], list(game.players.keys()))

    def test_cannot_leave_after_roles_dealt(self) -> None:
        _, game = self._game()
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        self.assertFalse(self.gm.remove_player_from_lobby(game, 10))

    def test_cannot_leave_after_game_left_lobby(self) -> None:
        _, game = self._game()
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        game.phase = Phase.NIGHT
        self.assertFalse(self.gm.remove_player_from_lobby(game, 10))

    def test_leave_resets_seats_when_finalized(self) -> None:
        _, game = self._game()
        p = Player(user_id=10, full_name="A", username=None, seat=1)
        self.gm.add_player(game, p)
        self.gm.add_player(
            game, Player(user_id=20, full_name="B", username=None, seat=2)
        )
        game.seats_finalized = True
        game.pending_seat_order = [10, 20]
        self.assertTrue(self.gm.remove_player_from_lobby(game, 10))
        self.assertFalse(game.seats_finalized)
        self.assertIsNone(game.pending_seat_order)
        self.assertIsNone(game.players[20].seat)

    def test_room_joinable_again_after_leave(self) -> None:
        code, game = self._game(max_players=10)
        for i in range(10):
            self.gm.add_player(
                game,
                Player(user_id=100 + i, full_name=f"P{i}", username=None),
            )
        ready, _ = self.gm.lobby_ready_for_deal(game)
        self.assertTrue(ready)
        game.lobby_full_notice_sent = True
        self.assertTrue(self.gm.remove_player_from_lobby(game, 100))
        ready, _ = self.gm.lobby_ready_for_deal(game)
        self.assertFalse(ready)
        self.assertFalse(game.lobby_full_notice_sent)
        self.gm.add_player(
            game, Player(user_id=999, full_name="New", username=None)
        )
        ready, _ = self.gm.lobby_ready_for_deal(game)
        self.assertTrue(ready)
        self.assertEqual(code, game.room_code)

    def test_assert_can_deal_roles_blocked_when_not_full(self) -> None:
        _, game = self._game(max_players=10)
        for i in range(9):
            self.gm.add_player(
                game,
                Player(user_id=100 + i, full_name=f"P{i}", username=None),
            )
        game.seats_finalized = True
        with self.assertRaises(ValueError) as ctx:
            self.gm.assert_can_deal_roles(game)
        self.assertEqual(str(ctx.exception), LOBBY_NOT_FULL_FOR_ROLES_MSG)

    def test_assert_can_deal_roles_allowed_when_full(self) -> None:
        _, game = self._game(max_players=10)
        for i in range(10):
            self.gm.add_player(
                game,
                Player(user_id=100 + i, full_name=f"P{i}", username=None),
            )
        game.seats_finalized = True
        self.gm.assert_can_deal_roles(game)

    def test_assert_can_deal_roles_blocked_after_roles(self) -> None:
        _, game = self._game()
        game.seats_finalized = True
        game.roles_dealt = True
        with self.assertRaises(ValueError) as ctx:
            self.gm.assert_can_deal_roles(game)
        self.assertEqual(str(ctx.exception), LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG)

    def test_reset_seats_helper(self) -> None:
        _, game = self._game()
        self.gm.add_player(
            game,
            Player(user_id=10, full_name="A", username=None, seat=3),
        )
        game.seats_finalized = True
        game.pending_seat_order = [10]
        reset_lobby_seats_after_roster_change(game)
        self.assertFalse(game.seats_finalized)
        self.assertIsNone(game.players[10].seat)

    def test_full_prompt_message_constant(self) -> None:
        self.assertIn("ظرفیت اتاق کامل شد", LOBBY_FULL_READY_FOR_ROLES_MSG)
        self.assertIn("تقسیم", LOBBY_FULL_READY_FOR_ROLES_MSG)

    def test_lobby_join_status_includes_leave_hint(self) -> None:
        _, game = self._game(max_players=12)
        self.gm.add_player(
            game,
            Player(user_id=10, full_name="امیر لطیفی", username="amirlati"),
        )
        text = build_lobby_join_status_text(game)
        self.assertIn("🎲 اتاق:", text)
        self.assertIn("📋 بازیکن‌ها:", text)
        self.assertIn("/leave", text)
        self.assertIn("تا پیش از تقسیم و ارسال نقش‌ها", text)

    def test_seat_assignment_message_after_shuffle_confirm(self) -> None:
        _, game = self._game(max_players=10)
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username="ali")
        )
        self.gm.add_player(
            game, Player(user_id=20, full_name="B", username=None)
        )
        game.pending_seat_order = [20, 10]
        text = build_seat_assignment_player_message(game)
        self.assertIn("🏠 اتاق", text)
        self.assertIn("سناریو:", text)
        self.assertIn("تعداد:", text)
        self.assertIn("لیست بازیکنها به ترتیب شماره صندلی", text)
        self.assertIn("منتظر دریافت نقش", text)
        self.assertIn("B", text)
        self.assertIn("A", text)
        self.assertLess(text.index("B"), text.index("A"))


if __name__ == "__main__":
    unittest.main()
