"""منطق دست دادن فاز آشوب."""

from __future__ import annotations

import unittest

from bot.chaos_handshake import decide_chaos_winner, find_valid_handshake
from bot.game import apply_bazpors_yakuzai_recruit
from bot.models import Game, Player, Role


def _game_3p() -> Game:
    game = Game(
        room_code="84",
        host_id=1,
        scenario_name="bazpors",
        players={
            1: Player(user_id=1, full_name="M", username=None, role=Role.MAFIA_BASIC, seat=1),
            2: Player(user_id=2, full_name="C1", username=None, role=Role.CITIZEN, seat=2),
            3: Player(user_id=3, full_name="C2", username=None, role=Role.HUNTER, seat=3),
        },
    )
    game.bazpors_host_mode = "no_host"
    return game


class ChaosHandshakeLogicTest(unittest.TestCase):
    def test_mafia_chaos_win_end_broadcast_text(self) -> None:
        from bot.main import build_bazpors_game_end_broadcast_html

        game = _game_3p()
        game.bazpors_mafia_win_via_chaos = True
        body = build_bazpors_game_end_broadcast_html(game, "mafia")
        self.assertIn("برد مافیا در فاز آشوب", body)
        self.assertNotIn("بیشتر از", body)

    def test_citizens_mutual_win(self) -> None:
        choices = {2: 3, 3: 2, 1: 2}
        self.assertEqual(find_valid_handshake(choices), (2, 3))
        out = decide_chaos_winner(_game_3p(), choices)
        self.assertEqual(out["winner"], "citizens")

    def test_mafia_citizen_mutual_mafia_wins(self) -> None:
        choices = {1: 2, 2: 1, 3: 2}
        out = decide_chaos_winner(_game_3p(), choices)
        self.assertEqual(out["winner"], "mafia")

    def test_no_mutual_pair(self) -> None:
        choices = {1: 2, 2: 3, 3: 1}
        self.assertIsNone(find_valid_handshake(choices))
        out = decide_chaos_winner(_game_3p(), choices)
        self.assertEqual(out["winner"], "no_valid_handshake")

    def test_yaku_recruit_counts_as_mafia(self) -> None:
        game = _game_3p()
        game.players[2] = Player(
            user_id=2, full_name="Y", username=None, role=Role.CITIZEN, seat=2
        )
        apply_bazpors_yakuzai_recruit(game, game.players[2])
        choices = {2: 3, 3: 2, 1: 3}
        out = decide_chaos_winner(game, choices)
        self.assertEqual(out["winner"], "mafia")


if __name__ == "__main__":
    unittest.main()
