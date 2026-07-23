"""شب معارفه — سناریوی مذاکره."""

from __future__ import annotations

import unittest

from bot.game import GameManager, scenario_role_label_fa
from bot.main import build_no_host_intro_night_mafia_dm_html
from bot.models import Player, Role


class MozakereIntroNightMafiaDmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_mafia_dm_uses_mozakere_role_labels(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        roles = [
            (20, "Boss", Role.MAFIA_BOSS, 1),
            (30, "Neg", Role.MAFIA_NEGOTIATOR, 2),
            (40, "Maf1", Role.MAFIA_SIMPLE, 3),
            (50, "Maf2", Role.MAFIA_SIMPLE_2, 4),
        ]
        for uid, name, role, seat in roles:
            game.players[uid] = Player(
                user_id=uid,
                full_name=name,
                username=None,
                role=role,
                seat=seat,
                is_alive=True,
            )

        html_msg = build_no_host_intro_night_mafia_dm_html(game)

        self.assertIn("اعضای تیم مافیا", html_msg)
        self.assertIn(f"Boss — <b>{scenario_role_label_fa(game, Role.MAFIA_BOSS)}</b>", html_msg)
        self.assertIn(
            f"Neg — <b>{scenario_role_label_fa(game, Role.MAFIA_NEGOTIATOR)}</b>",
            html_msg,
        )
        self.assertIn(
            f"Maf1 — <b>{scenario_role_label_fa(game, Role.MAFIA_SIMPLE)}</b>",
            html_msg,
        )
        self.assertIn(
            f"Maf2 — <b>{scenario_role_label_fa(game, Role.MAFIA_SIMPLE_2)}</b>",
            html_msg,
        )
        self.assertIn("رئیس مافیا", html_msg)
        self.assertIn("مذاکره کننده", html_msg)
        self.assertIn("مافیا ساده اول", html_msg)
        self.assertIn("مافیا ساده دوم", html_msg)
        self.assertNotIn("رییس مافیا", html_msg)
        self.assertNotIn("مذاکره‌کننده", html_msg)
        self.assertNotIn("مافیا اول ساده", html_msg)
        self.assertNotIn("مافیا دوم ساده", html_msg)

    def test_mafia_dm_omits_second_simple_when_absent(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for uid, name, role, seat in [
            (20, "Boss", Role.MAFIA_BOSS, 1),
            (30, "Neg", Role.MAFIA_NEGOTIATOR, 2),
            (40, "Maf1", Role.MAFIA_SIMPLE, 3),
        ]:
            game.players[uid] = Player(
                user_id=uid,
                full_name=name,
                username=None,
                role=role,
                seat=seat,
                is_alive=True,
            )

        html_msg = build_no_host_intro_night_mafia_dm_html(game)

        self.assertIn("مافیا ساده اول", html_msg)
        self.assertNotIn("مافیا ساده دوم", html_msg)
