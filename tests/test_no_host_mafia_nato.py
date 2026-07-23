"""شب ۱ — ناتویی no_host."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Player, Role
from bot.bazpors_narrator import nato_denied_message
from bot.no_host_mafia_nato import (
    _nato_guess_roles_in_room,
    _non_mafia_roles_in_room,
    build_no_host_nato_done_broadcast_html,
    build_no_host_nato_wait_broadcast_html,
    mafia_nato_act_active,
    no_host_nato_allowed,
)


class NoHostMafiaNatoTest(unittest.TestCase):
    def test_nato_acts(self) -> None:
        self.assertTrue(mafia_nato_act_active(None, "n1r-CITIZEN"))
        self.assertTrue(mafia_nato_act_active(None, "n2c"))
        self.assertFalse(mafia_nato_act_active(None, "nms"))

    def test_denied_message_already_used(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_nato_used = True
        self.assertIn("قبلاً", nato_denied_message(game))

    def test_denied_message_nato_eliminated(self) -> None:
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
            Player(
                user_id=20,
                full_name="Nato",
                username=None,
                role=Role.NATO,
                is_alive=False,
            ),
        )
        self.assertIn("خارج شده", nato_denied_message(game))

    def test_wait_broadcast_html(self) -> None:
        html = build_no_host_nato_wait_broadcast_html()
        self.assertIn("در حال ناتویی", html)

    def test_done_broadcast_html(self) -> None:
        html = build_no_host_nato_done_broadcast_html()
        self.assertIn("انتخاب ناتو ثبت شد", html)

    def test_not_allowed_if_used(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        game.bazpors_nato_used = True
        self.assertFalse(no_host_nato_allowed(game))

    def test_not_allowed_without_nato(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        self.assertFalse(no_host_nato_allowed(game))

    def test_non_mafia_roles_includes_dead(self) -> None:
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
            Player(
                user_id=30,
                full_name="Doc",
                username=None,
                role=Role.DOCTOR,
                is_alive=False,
            ),
        )
        gm.add_player(
            game,
            Player(user_id=40, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Nato", username=None, role=Role.NATO),
        )
        roles = _non_mafia_roles_in_room(game)
        role_set = set(roles)
        self.assertIn(Role.DOCTOR, role_set)
        self.assertIn(Role.CITIZEN, role_set)
        self.assertTrue(all(not is_mafia_team(r) for r in roles))

    def test_nato_guess_roles_excludes_citizen(self) -> None:
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
            Player(user_id=30, full_name="Doc", username=None, role=Role.DOCTOR),
        )
        gm.add_player(
            game, Player(user_id=40, full_name="Cit", username=None, role=Role.CITIZEN)
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO),
        )
        roles = _nato_guess_roles_in_room(game)
        self.assertIn(Role.DOCTOR, roles)
        self.assertNotIn(Role.CITIZEN, roles)


if __name__ == "__main__":
    unittest.main()
