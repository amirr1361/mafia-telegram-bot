"""دو مرحله‌ای شدن ورود به اتاق — پیش‌نمایش و تأیید."""

from __future__ import annotations

import unittest

from bot.game import role_label_fa
from bot.main import (
    JoinConfirmCb,
    _join_confirm_error_message,
    _players_in_lobby_join_order,
    build_join_preview_html,
    join_confirm_keyboard,
    manager,
)
from bot.models import Phase, Player, Role


class JoinConfirmFlowTests(unittest.TestCase):
    _host_seq = 1000

    def setUp(self) -> None:
        self.gm = manager

    def _lobby_game(self, *, max_players: int = 12) -> tuple[str, object]:
        JoinConfirmFlowTests._host_seq += 1
        host_id = JoinConfirmFlowTests._host_seq
        game = self.gm.create_game(
            host_id=host_id,
            scenario_name="bazpors",
            max_players=max_players,
        )
        assert game is not None
        return game.room_code, game

    def test_preview_contains_room_scenario_roles_and_players(self) -> None:
        code, game = self._lobby_game()
        self.gm.add_player(
            game, Player(user_id=10, full_name="Ali", username="ali")
        )
        self.gm.add_player(
            game, Player(user_id=20, full_name="Sara", username=None)
        )
        html = build_join_preview_html(game)
        self.assertIn("اتاق شماره", html)
        self.assertIn("بازپرس", html)
        self.assertIn("۱۲", html)
        self.assertIn("🟥 نقش‌های مافیا:", html)
        self.assertIn("🟦 نقش‌های شهروندی:", html)
        self.assertIn("رییس مافیا", html)
        self.assertIn("Ali", html)
        self.assertIn("Sara", html)
        self.assertIn("آیا تمایل دارید", html)

    def test_players_in_join_order(self) -> None:
        _, game = self._lobby_game()
        self.gm.add_player(
            game, Player(user_id=30, full_name="Third", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=10, full_name="First", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=20, full_name="Second", username=None)
        )
        names = [p.full_name for p in _players_in_lobby_join_order(game)]
        self.assertEqual(names, ["Third", "First", "Second"])
        html = build_join_preview_html(game)
        self.assertLess(html.index("Third"), html.index("First"))
        self.assertLess(html.index("First"), html.index("Second"))

    def test_confirm_keyboard_embeds_room_and_user(self) -> None:
        code, _game = self._lobby_game()
        kb = join_confirm_keyboard(code, 999)
        acts: list[str] = []
        uids: list[int] = []
        codes: list[str] = []
        for row in kb.inline_keyboard:
            for btn in row:
                data = JoinConfirmCb.unpack(btn.callback_data)
                acts.append(data.act)
                uids.append(data.uid)
                codes.append(data.code)
        self.assertEqual(set(acts), {"yes", "no"})
        self.assertTrue(all(u == 999 for u in uids))
        self.assertTrue(all(c == code for c in codes))
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("✅ بله  ", labels)
        self.assertIn("❌ خیر", labels)

    def test_join_validation_host_cannot_join(self) -> None:
        code, game = self._lobby_game()
        err = _join_confirm_error_message(game.host_id, code)
        self.assertIsNotNone(err)
        self.assertIn("گرداننده", err or "")

    def test_join_validation_full_room(self) -> None:
        code, game = self._lobby_game(max_players=10)
        for i in range(10):
            self.gm.add_player(
                game,
                Player(user_id=500 + i, full_name=f"P{i}", username=None),
            )
        err = _join_confirm_error_message(30, code)
        self.assertEqual(err, "ظرفیت اتاق پر است.")

    def test_join_validation_not_lobby(self) -> None:
        code, game = self._lobby_game()
        game.phase = Phase.NIGHT
        err = _join_confirm_error_message(9001, code)
        self.assertEqual(err, "این بازی دیگر در حالت لابی نیست.")

    def test_join_validation_already_in_room(self) -> None:
        code, game = self._lobby_game()
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        err = _join_confirm_error_message(10, code)
        self.assertIn("همین الان", err or "")

    def test_mafia_roles_listed_before_town_in_preview(self) -> None:
        _, game = self._lobby_game()
        html = build_join_preview_html(game)
        roles = self.gm.intended_roles_for_room(game.scenario_name, game.max_players)
        first_mafia = role_label_fa(next(r for r in roles if r == Role.MAFIA_BOSS))
        first_town = role_label_fa(next(r for r in roles if r == Role.DOCTOR))
        self.assertLess(html.index(first_mafia), html.index(first_town))


if __name__ == "__main__":
    unittest.main()
