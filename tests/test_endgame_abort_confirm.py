"""تأیید /endgame — پایان بدون نتیجه در semi_auto و manual."""

from __future__ import annotations

import unittest

from bot.post_game_flow import host_endgame_needs_abort_confirm, user_may_act_as_game_host
from bot.models import Game, Phase, Player, Role


def _game(*, mode: str = "semi_auto", host_may_pick: bool = False) -> Game:
    g = Game(
        room_code="99",
        host_id=1,
        scenario_name="bazpors",
        players={1: Player(1, "گرداننده", None, Role.CITIZEN, 1)},
        max_players=12,
    )
    g.bazpors_host_mode = mode
    g.roles_dealt = True
    g.phase = Phase.MANUAL
    g.host_may_pick_winner = host_may_pick
    return g


class EndgameAbortConfirmTests(unittest.TestCase):
    def test_semi_auto_in_progress_needs_confirm(self) -> None:
        self.assertTrue(host_endgame_needs_abort_confirm(_game(mode="semi_auto")))

    def test_manual_in_progress_needs_confirm(self) -> None:
        self.assertTrue(host_endgame_needs_abort_confirm(_game(mode="manual")))

    def test_no_host_in_progress_needs_confirm(self) -> None:
        self.assertTrue(host_endgame_needs_abort_confirm(_game(mode="no_host")))

    def test_natural_win_skips_confirm(self) -> None:
        self.assertFalse(
            host_endgame_needs_abort_confirm(_game(host_may_pick=True))
        )

    def test_lobby_skips_confirm(self) -> None:
        g = _game()
        g.roles_dealt = False
        self.assertFalse(host_endgame_needs_abort_confirm(g))

    def test_no_host_bot_assistant_may_end_as_host(self) -> None:
        g = _game(mode="no_host")
        g.host_id = 100
        g.bot_assistant_user_id = 200
        g.players[200] = Player(200, "کمک", None, Role.CITIZEN, 2)
        self.assertTrue(user_may_act_as_game_host(g, 200))
        self.assertFalse(user_may_act_as_game_host(g, 99))


if __name__ == "__main__":
    unittest.main()
