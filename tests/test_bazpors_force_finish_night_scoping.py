"""Room 91 — Bazpors force-finish latch night scoping (focused tests).

Root cause: ``bazpors_night_force_finished`` was set when the helper
force-finished Night N but never reset or night-scoped, so EVERY later
night's valid night-action callbacks were rejected with
«فاز شب به پایان رسیده است.» before reaching any dispatcher.

Fix: the latch keeps the night it was recorded on
(``bazpors_night_force_finished_night``); the gate blocks only the latched
night, legacy latches without a recorded night open when parallel
collection is active again (it was closed at force-finish time), and
``_reset_night_flags`` clears both fields on every new-night entry.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role

ASSISTANT = 108214166
OBSERVER = 8620239861


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _game(night: int = 3) -> Game:
    game = Game(
        room_code="91",
        host_id=ASSISTANT,
        scenario_name="bazpors",
        players={
            1: _p(1, 1, "one", Role.CITIZEN),
            2: _p(2, 2, "two", Role.CITIZEN),
            3: _p(3, 3, "three", Role.DOCTOR),
        },
    )
    game.bazpors_narrator_night_count = night
    game.bazpors_narrator_step = "night_actions"
    game.bazpors_host_mode = "no_host"
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = ASSISTANT
    game.observer_user_id = OBSERVER
    game.observer_prompt_status = "registered"
    game.no_host_night_parallel_collect_active = True
    return game


def _force_finish(game: Game, bot=None, gm=None) -> None:
    from bot.bazpors_force_finish_night import force_finish_bazpors_night
    from bot import app_state

    async def go():
        with patch(
            "bot.no_host_night_ready.finish_no_host_parallel_night_collect",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_force_finish_night.lock_bazpors_night_mirror_panels",
            new=AsyncMock(),
        ), patch.object(
            app_state.manager, "persist_snapshot", new=AsyncMock()
        ), patch(
            "bot.night_helper_reminder.cleanup_night_helper_reminder",
            new=AsyncMock(),
        ):
            await force_finish_bazpors_night(bot or object(), game, gm or GameManager())

    asyncio.new_event_loop().run_until_complete(go())


class ForceFinishLatchScopingTests(unittest.TestCase):
    def test_force_finish_blocks_night_N_only(self) -> None:
        from bot.bazpors_force_finish_night import (
            bazpors_night_act_is_closed_for_game,
            bazpors_night_player_actions_closed,
        )

        game = _game(night=3)
        _force_finish(game)

        self.assertTrue(game.bazpors_night_force_finished)
        self.assertEqual(game.bazpors_night_force_finished_night, 3)
        self.assertTrue(bazpors_night_player_actions_closed(game))
        # every night act is rejected inside the latched night
        for act in ("dkt", "nms", "ndp", "skt", "hnp", "cic", "ruc", "nii1"):
            self.assertTrue(bazpors_night_act_is_closed_for_game(game, act))
        self.assertTrue(bazpors_night_act_is_closed_for_game(game, "n1r-DOCTOR"))
        # day acts are not in the closed set
        self.assertFalse(bazpors_night_act_is_closed_for_game(game, "d1dt"))

    def test_new_night_enters_open_for_valid_actions(self) -> None:
        from bot.bazpors_force_finish_night import (
            bazpors_night_act_is_closed_for_game,
            bazpors_night_player_actions_closed,
        )
        from bot.bazpors_narrator import _reset_night_flags

        game = _game(night=3)
        _force_finish(game)
        self.assertTrue(bazpors_night_player_actions_closed(game))

        # Night 4 entry: the real per-night reset path clears the latch.
        game.bazpors_narrator_night_count = 4
        game.no_host_night_parallel_collect_active = True
        _reset_night_flags(game)

        self.assertFalse(game.bazpors_night_force_finished)
        self.assertIsNone(game.bazpors_night_force_finished_night)
        self.assertFalse(bazpors_night_player_actions_closed(game))
        for act in ("dkt", "nms", "hnp", "cic"):
            self.assertFalse(bazpors_night_act_is_closed_for_game(game, act))

    def test_next_night_can_be_force_finished_again(self) -> None:
        from bot.bazpors_force_finish_night import bazpors_night_player_actions_closed

        game = _game(night=3)
        _force_finish(game)
        game.bazpors_narrator_night_count = 4
        game.no_host_night_parallel_collect_active = True
        _force_finish(game)

        self.assertTrue(game.bazpors_night_force_finished)
        self.assertEqual(game.bazpors_night_force_finished_night, 4)
        self.assertTrue(bazpors_night_player_actions_closed(game))

    def test_room91_legacy_stale_latch_recovers(self) -> None:
        """Snapshot shape: flag=True with NO recorded night (legacy) while
        Night 4 collection is active — the gate must be OPEN."""
        from bot.bazpors_force_finish_night import (
            bazpors_night_act_is_closed_for_game,
            bazpors_night_player_actions_closed,
        )
        from bot.game_snapshot import restore_games_into_manager

        game = _game(night=4)
        game.bazpors_night_force_finished = True
        game.bazpors_night_force_finished_night = None
        game.no_host_night_parallel_collect_active = True

        self.assertFalse(bazpors_night_player_actions_closed(game))
        for act in ("dkt", "nms", "cic", "hnp"):
            self.assertFalse(bazpors_night_act_is_closed_for_game(game, act))

        # And a criteria-free force-finish relatches the CURRENT night.
        _force_finish(game)
        self.assertEqual(game.bazpors_night_force_finished_night, 4)
        self.assertTrue(bazpors_night_player_actions_closed(game))

    def test_legacy_snapshot_model_default_is_none(self) -> None:
        """A legacy snapshot without the new field restores with the
        recorded-night default (None) — verified on the model itself."""
        game = _game(night=4)
        self.assertIsNone(game.bazpors_night_force_finished_night)
        game.bazpors_night_force_finished = True
        game.no_host_night_parallel_collect_active = True
        from bot.bazpors_force_finish_night import bazpors_night_player_actions_closed

        self.assertFalse(bazpors_night_player_actions_closed(game))

    def test_legacy_latch_with_closed_collection_still_blocking(self) -> None:
        from bot.bazpors_force_finish_night import (
            bazpors_night_act_is_closed_for_game,
            bazpors_night_player_actions_closed,
        )

        game = _game(night=3)
        game.bazpors_night_force_finished = True
        game.bazpors_night_force_finished_night = None
        game.no_host_night_parallel_collect_active = False

        self.assertTrue(bazpors_night_player_actions_closed(game))
        self.assertTrue(bazpors_night_act_is_closed_for_game(game, "dkt"))

    def test_recorded_night_mismatch_reopens_gate(self) -> None:
        from bot.bazpors_force_finish_night import bazpors_night_player_actions_closed

        game = _game(night=4)
        game.bazpors_night_force_finished = True
        game.bazpors_night_force_finished_night = 3
        game.no_host_night_parallel_collect_active = True

        self.assertFalse(bazpors_night_player_actions_closed(game))
        # same night latch still blocks
        game.bazpors_narrator_night_count = 3
        self.assertTrue(bazpors_night_player_actions_closed(game))

    def test_stale_callbacks_cannot_commit_in_new_night(self) -> None:
        """An old night-N panel memory pressed in night N+1: the gate is
        open for NEW valid acts, but a stale act from night N can never
        reach the commit path — the per-night signature resets on entry so
        an old dm_signature cannot re-consolidate."""
        from bot.bazpors_narrator import _reset_night_flags

        game = _game(night=3)
        _force_finish(game)
        game.bazpors_narrator_night_count = 4
        game.no_host_night_parallel_collect_active = True
        _reset_night_flags(game)

        # commit structures for the force-finished night are gone
        self.assertFalse(getattr(game, "no_host_doctor_night_nato_blocked_panel", False))
        self.assertEqual(
            game.bazpors_night_force_finished_night,
            None,
            "the N-latch is cleared on the new night entry",
        )

    def test_other_scenarios_untouched(self) -> None:
        from bot.bazpors_force_finish_night import bazpors_night_player_actions_closed
        from bot.bazpors_narrator import _reset_night_flags

        # Mozakere room keeps its own gate (flag ignored by the Bazpors gate)
        game = _game(night=3)
        game.scenario_name = "mozakere"
        game.mozakere_night_force_finished = True
        self.assertFalse(bazpors_night_player_actions_closed(game))
        # mason flag must not be touched by the Bazpors reset
        game2 = _game(night=3)
        game2.scenario_name = "masoon"
        game2.mason_night_force_finished = True
        _reset_night_flags(game2)
        self.assertTrue(game2.mason_night_force_finished)
        # and the reused-reset must still clear the stale Bazpors latch only
        game2.bazpors_night_force_finished = True
        game2.bazpors_night_force_finished_night = 3
        _reset_night_flags(game2)
        self.assertFalse(game2.bazpors_night_force_finished)
        self.assertIsNone(game2.bazpors_night_force_finished_night)


if __name__ == "__main__":
    unittest.main()
