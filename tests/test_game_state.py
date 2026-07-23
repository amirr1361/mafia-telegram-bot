"""فاز ۳ — nested game state views."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_synthetic_player_uid
from bot.game_state import (
    NO_HOST_ROLE_PICK_SPECS,
    arm_no_host_role_pick,
    bazpors_narrator_state,
    no_host_day_state,
    no_host_night_state,
    reset_no_host_per_night_role_state,
)
from bot.models import Game, Player, Role


class GameStateViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _no_host_game(self, *, n: int = 10) -> Game:
        game = self.gm.create_game(
            host_id=100,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="bazpors",
            max_players=n,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=100, full_name="سازنده", username=None)
        )
        self.gm.fill_bazpors_no_host_synthetic_lobby(game)
        return game

    def test_role_pick_view_read_write(self) -> None:
        game = self._no_host_game()
        view = no_host_night_state(game).role_pick("doctor")
        view.flow_active = True
        view.dm_signature = "sig-1"
        self.assertTrue(game.no_host_doctor_flow_active)
        self.assertEqual(game.no_host_doctor_dm_signature, "sig-1")
        view.reset()
        self.assertFalse(game.no_host_doctor_flow_active)
        self.assertIsNone(game.no_host_doctor_dm_signature)

    def test_arm_role_pick_reactivates_stale_flow(self) -> None:
        game = self._no_host_game()
        game.no_host_detective_flow_active = False
        game.no_host_detective_dm_signature = "already-sent"
        arm_no_host_role_pick(game, "detective")
        self.assertTrue(game.no_host_detective_flow_active)

    def test_reset_clears_all_role_picks(self) -> None:
        game = self._no_host_game()
        for spec in NO_HOST_ROLE_PICK_SPECS:
            setattr(game, spec.flow_active, True)
            setattr(game, spec.pick_confirmed, True)
            setattr(game, spec.dm_signature, "x")
        game.no_host_mafia_night1_flow_active = True
        game.no_host_night1_hunter_flow_active = True
        reset_no_host_per_night_role_state(game)
        for spec in NO_HOST_ROLE_PICK_SPECS:
            self.assertFalse(getattr(game, spec.flow_active))
            self.assertFalse(getattr(game, spec.pick_confirmed))
            self.assertIsNone(getattr(game, spec.dm_signature))
        self.assertFalse(game.no_host_mafia_night1_flow_active)
        self.assertFalse(game.no_host_night1_hunter_flow_active)

    def test_narrator_and_day_views(self) -> None:
        game = self._no_host_game()
        narr = bazpors_narrator_state(game)
        narr.step = "night_start"
        narr.night_count = 2
        self.assertEqual(game.bazpors_narrator_step, "night_start")
        self.assertEqual(game.bazpors_narrator_night_count, 2)
        day = no_host_day_state(game)
        day.intro_night_started = True
        self.assertTrue(game.no_host_intro_night_started)


if __name__ == "__main__":
    unittest.main()
