"""جمع‌آوری موازی شب — هانتر/مافیا هم‌زمان با بقیه در ورود شب."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT
from bot.no_host_mafia_shot import no_host_requires_mafia_shot_pick
from bot.no_host_night_ready import (
    _interrogator_ready,
    all_no_host_parallel_night_ready,
    pending_no_host_night_actor_labels,
)


def _parallel_game() -> Game:
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 99
    game.no_host_assistant_narrator_active = True
    game.no_host_night_parallel_collect_active = True
    game.bazpors_narrator_step = "night_start"
    game.bazpors_narrator_night_count = 1
    game.no_host_night1_hunter_done = False
    game.no_host_mafia_night1_done = False
    game.no_host_citizen_night_confirmed_uids = [2]
    game.no_host_ruintan_night_confirmed = True
    game.no_host_shiad_pick_confirmed = True
    game.no_host_detective_pick_confirmed = True
    game.no_host_doctor_pick_confirmed = True
    game.no_host_sniper_pick_confirmed = True
    game.no_host_interrog_pick_confirmed = True
    gm.add_player(
        game, Player(2, "Cit", None, Role.CITIZEN, seat=2, is_alive=True)
    )
    gm.add_player(
        game, Player(-10, "امیر-هانتر", None, Role.HUNTER, seat=5, is_alive=True)
    )
    gm.add_player(
        game,
        Player(-11, "رییس-رییس مافیا", None, Role.MAFIA_BOSS, seat=6, is_alive=True),
    )
    return game


class NoHostParallelNightTests(unittest.TestCase):
    def test_parallel_waits_for_synthetic_hunter_mafia_night1(self) -> None:
        game = _parallel_game()
        self.assertFalse(all_no_host_parallel_night_ready(game))
        game.no_host_night1_hunter_done = True
        game.no_host_mafia_night1_done = True
        self.assertTrue(all_no_host_parallel_night_ready(game))

    def test_parallel_waits_for_human_hunter_including_assistant(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 108214166
        game.no_host_assistant_narrator_active = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = "night_start"
        game.bazpors_narrator_night_count = 1
        game.no_host_night1_hunter_done = False
        game.no_host_mafia_night1_done = True
        game.no_host_citizen_night_confirmed_uids = [2]
        game.no_host_ruintan_night_confirmed = True
        game.no_host_shiad_pick_confirmed = True
        game.no_host_detective_pick_confirmed = True
        game.no_host_doctor_pick_confirmed = True
        game.no_host_sniper_pick_confirmed = True
        game.no_host_interrog_pick_confirmed = True
        gm.add_player(
            game,
            Player(108214166, "Host", None, Role.HUNTER, seat=1, is_alive=True),
        )
        gm.add_player(
            game, Player(2, "Cit", None, Role.CITIZEN, seat=2, is_alive=True)
        )
        self.assertFalse(all_no_host_parallel_night_ready(game))
        game.no_host_night1_hunter_done = True
        self.assertTrue(all_no_host_parallel_night_ready(game))

    def test_pending_labels_include_hunter_mafia_when_pending(self) -> None:
        game = _parallel_game()
        pending = pending_no_host_night_actor_labels(game)
        self.assertIn("هانتر", pending)
        self.assertIn("تیم مافیا", pending)

    def test_parallel_waits_for_mafia_shot_night2(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 99
        game.no_host_assistant_narrator_active = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = "night_start"
        game.bazpors_narrator_night_count = 2
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = False
        game.no_host_citizen_night_confirmed_uids = [2]
        game.no_host_ruintan_night_confirmed = True
        game.no_host_shiad_pick_confirmed = True
        game.no_host_detective_pick_confirmed = True
        game.no_host_doctor_pick_confirmed = True
        game.no_host_sniper_pick_confirmed = True
        game.no_host_interrog_pick_confirmed = True
        gm.add_player(
            game,
            Player(-11, "ناتو", None, Role.NATO, seat=4, is_alive=True),
        )
        gm.add_player(
            game, Player(2, "Cit", None, Role.CITIZEN, seat=2, is_alive=True)
        )
        self.assertTrue(no_host_requires_mafia_shot_pick(game))
        self.assertFalse(all_no_host_parallel_night_ready(game))
        game.no_host_mafia_shot_done = True
        self.assertTrue(all_no_host_parallel_night_ready(game))

    def test_interrogator_ready_when_dead_or_night_finished(self) -> None:
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
            Player(-9, "بازپرس", None, Role.INTERROGATOR, seat=9, is_alive=False),
        )
        game.no_host_interrog_pick_confirmed = False
        self.assertTrue(_interrogator_ready(game))
        gm.add_player(
            game,
            Player(-8, "بازپرس۲", None, Role.INTERROGATOR, seat=8, is_alive=True),
        )
        game.no_host_interrog_pick_confirmed = False
        game.bazpors_interrog_night_finished = True
        self.assertTrue(_interrogator_ready(game))

    def test_pending_labels_include_shiad_when_pending(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_night_count = 1
        game.no_host_night1_hunter_done = True
        game.no_host_mafia_night1_done = True
        game.no_host_shiad_pick_confirmed = False
        gm.add_player(
            game, Player(3, "Sh", None, Role.SHIAD, seat=3, is_alive=True)
        )
        pending = pending_no_host_night_actor_labels(game)
        self.assertIn("شیاد", pending)


if __name__ == "__main__":
    unittest.main()
