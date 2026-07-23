"""شهروند ساده — فاز شب no_host."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_citizen_night import (
    _alive_citizens,
    _confirm_keyboard,
    build_no_host_citizen_night_html,
)
from bot.observer_delivery import PlayerMirrorCb


class NoHostCitizenNightTest(unittest.TestCase):
    def test_night_html(self) -> None:
        body = build_no_host_citizen_night_html(confirmed=False)
        self.assertIn("شهروند ساده", body)
        self.assertIn("منتظر اتمام فاز شب", body)
        self.assertNotIn("تأیید شما", body)

    def test_confirmed_html(self) -> None:
        body = build_no_host_citizen_night_html(confirmed=True)
        self.assertIn("تأیید شما ثبت شد", body)

    def test_confirm_keyboard_uses_cic_act(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        kb = _confirm_keyboard(game, 42)
        cb = PlayerMirrorCb.unpack(kb.inline_keyboard[0][0].callback_data)
        self.assertEqual(cb.act, "cic")
        self.assertEqual(cb.as_uid, 42)

    def test_alive_citizens_filter(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="C1", username=None, role=Role.CITIZEN),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Doc", username=None, role=Role.DOCTOR),
        )
        gm.add_player(
            game,
            Player(user_id=30, full_name="C2", username=None, role=Role.CITIZEN),
        )
        game.players[30].is_alive = False
        ids = [p.user_id for p in _alive_citizens(game)]
        self.assertEqual(ids, [10])


if __name__ == "__main__":
    unittest.main()
