"""Mozakere force-finish latch night scoping (focused tests).

Mozakere had the same sticky-state defect as Bazpors Room 91:
``mozakere_night_force_finished``` was set when the helper force-finished
Night N but never reset or night-scoped, so every later night's valid
night-action callbacks were rejected with «فاز شب به پایان رسیده است.».

The mirror fix keeps the latch with its night
(``mozakere_night_force_finished_night``); the gate blocks only the
latched night; legacy latches without a recorded night open when
parallel collection is active again (a real force-finish always closes
the collection it latched, so latch + active collection can only be a
later night); and the shared ``_reset_night_flags`` new-night entry
clears both fields. Bazpors/Mason/Nam10 keep their own mechanisms.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role

ASSISTANT = 108214166


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
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "MZF"
    gm.games["MZF"] = game
    for seat, (uid, name, role) in enumerate(
        [(1, "boss", Role.MAFIA_BOSS), (2, "doc", Role.DOCTOR), (3, "cit", Role.CITIZEN)],
        start=1,
    ):
        gm.add_player(game, _p(uid, seat, name, role))
    game.bazpors_narrator_night_count = night
    game.bazpors_narrator_step = "night_start"
    game.bot_assistant_user_id = ASSISTANT
    game.no_host_assistant_narrator_active = True
    game.no_host_night_parallel_collect_active = True
    game.no_host_night_entry_dispatched_night = night
    return game


def _force_finish(game: Game, bot=None, gm=None) -> None:
    from bot.mozakere_force_finish_night import force_finish_mozakere_night
    from bot import app_state

    async def go():
        with patch(
            "bot.no_host_night_ready.finish_no_host_parallel_night_collect",
            new=AsyncMock(),
        ), patch(
            "bot.mozakere_force_finish_night.lock_mozakere_night_mirror_panels",
            new=AsyncMock(),
        ), patch.object(
            app_state.manager, "persist_snapshot", new=AsyncMock()
        ), patch(
            "bot.night_helper_reminder.cleanup_night_helper_reminder",
            new=AsyncMock(),
        ):
            await force_finish_mozakere_night(
                bot or object(), game, gm or GameManager()
            )

    asyncio.new_event_loop().run_until_complete(go())


class MozakereForceFinishNightScopingTests(unittest.TestCase):
    def test_force_finish_blocks_night_N_only(self) -> None:
        from bot.mozakere_force_finish_night import (
            mozakere_night_act_is_closed_for_game,
            mozakere_night_player_actions_closed,
        )

        game = _game(night=3)
        _force_finish(game)

        self.assertTrue(game.mozakere_night_force_finished)
        self.assertEqual(game.mozakere_night_force_finished_night, 3)
        self.assertTrue(mozakere_night_player_actions_closed(game))
        # every closed-set night act is rejected inside the latched night
        for act in ("nms", "msk", "negp", "dkt", "dko", "ndp", "skt", "jrp", "cic", "ruc", "nwok"):
            self.assertTrue(mozakere_night_act_is_closed_for_game(game, act))

    def test_new_night_enters_open_for_valid_actions(self) -> None:
        from bot.mozakere_force_finish_night import (
            mozakere_night_act_is_closed_for_game,
            mozakere_night_player_actions_closed,
        )
        from bot.bazpors_narrator import _reset_night_flags

        game = _game(night=3)
        _force_finish(game)
        self.assertTrue(mozakere_night_player_actions_closed(game))

        # Night 4 entry: the real shared per-night reset path clears the latch.
        game.bazpors_narrator_night_count = 4
        game.no_host_night_parallel_collect_active = True
        game.no_host_night_entry_dispatched_night = 4
        _reset_night_flags(game)

        self.assertFalse(game.mozakere_night_force_finished)
        self.assertIsNone(game.mozakere_night_force_finished_night)
        self.assertFalse(mozakere_night_player_actions_closed(game))
        for act in ("nms", "dkt", "ndp", "skt", "cic"):
            self.assertFalse(mozakere_night_act_is_closed_for_game(game, act))

    def test_next_night_can_be_force_finished_again(self) -> None:
        from bot.mozakere_force_finish_night import mozakere_night_player_actions_closed

        game = _game(night=3)
        _force_finish(game)
        game.bazpors_narrator_night_count = 4
        game.no_host_night_parallel_collect_active = True
        game.no_host_night_entry_dispatched_night = 4
        _force_finish(game)

        self.assertTrue(game.mozakere_night_force_finished)
        self.assertEqual(game.mozakere_night_force_finished_night, 4)
        self.assertTrue(mozakere_night_player_actions_closed(game))

    def test_legacy_stale_latch_with_active_collection_reopens(self) -> None:
        """Legacy snapshot shape: flag=True with NO recorded night while a
        later night's parallel collection is active — the gate must be OPEN."""
        from bot.mozakere_force_finish_night import (
            mozakere_night_act_is_closed_for_game,
            mozakere_night_player_actions_closed,
        )

        game = _game(night=4)
        game.mozakere_night_force_finished = True
        # legacy snapshot: field key entirely absent -> model default None
        game.mozakere_night_force_finished_night = None

        self.assertFalse(mozakere_night_player_actions_closed(game))
        for act in ("nms", "dkt", "cic", "negp"):
            self.assertFalse(mozakere_night_act_is_closed_for_game(game, act))

        # A subsequent force-finish relatches the CURRENT night.
        _force_finish(game)
        self.assertEqual(game.mozakere_night_force_finished_night, 4)
        self.assertTrue(mozakere_night_player_actions_closed(game))

    def test_legacy_latch_with_closed_collection_still_blocking(self) -> None:
        """Legacy latch while collection is INACTIVE = same-night safety:
        the force-finished night stays closed."""
        from bot.mozakere_force_finish_night import (
            mozakere_night_act_is_closed_for_game,
            mozakere_night_player_actions_closed,
        )

        game = _game(night=3)
        game.mozakere_night_force_finished = True
        game.mozakere_night_force_finished_night = None
        game.no_host_night_parallel_collect_active = False

        self.assertTrue(mozakere_night_player_actions_closed(game))
        self.assertTrue(mozakere_night_act_is_closed_for_game(game, "dkt"))

    def test_recorded_night_mismatch_reopens_gate(self) -> None:
        from bot.mozakere_force_finish_night import mozakere_night_player_actions_closed

        game = _game(night=4)
        game.mozakere_night_force_finished = True
        game.mozakere_night_force_finished_night = 3
        game.no_host_night_parallel_collect_active = True

        self.assertFalse(mozakere_night_player_actions_closed(game))
        # a same-night latch still blocks
        game.bazpors_narrator_night_count = 3
        self.assertTrue(mozakere_night_player_actions_closed(game))

    def test_stale_buttons_cannot_reopen_or_relatch_without_collection(self) -> None:
        """Button/confirm handlers use the collection-generation check, so an
        old panel cannot act once the latched night closed its collection."""
        from bot.mozakere_force_finish_night import (
            mozakere_night_force_finish_collection_active,
        )

        game = _game(night=3)
        _force_finish(game)
        # The real finish closes the collection it latched; the AsyncMock
        # above doesn't reproduce that side effect, so mirror it here.
        game.no_host_night_parallel_collect_active = False
        self.assertFalse(game.no_host_night_parallel_collect_active)
        self.assertFalse(mozakere_night_force_finish_collection_active(game))
        # and the night-scoped gate keeps blocking same-night acts
        from bot.mozakere_force_finish_night import mozakere_night_player_actions_closed
        self.assertTrue(mozakere_night_player_actions_closed(game))

    def test_other_scenarios_untouched(self) -> None:
        from bot.mozakere_force_finish_night import mozakere_night_player_actions_closed
        from bot.bazpors_narrator import _reset_night_flags

        # a Bazpors room ignores the Mozakere flag
        game = _game(night=3)
        game.scenario_name = "bazpors"
        game.mozakere_night_force_finished = True
        self.assertFalse(mozakere_night_player_actions_closed(game))

        # the Mason per-night state survives the Mozakere reset path
        game2 = _game(night=3)
        game2.scenario_name = "masoon"
        game2.mason_night_force_finished = True
        _reset_night_flags(game2)
        self.assertTrue(game2.mason_night_force_finished)

        # and Mozakere itself is untouched by scenario isolation checks
        game3 = _game(night=3)
        game3.scenario_name = "namayande10"
        game3.mozakere_night_force_finished = True
        self.assertFalse(mozakere_night_player_actions_closed(game3))

    def test_alternating_nights_do_not_poison(self) -> None:
        """Normal → forced → normal → forced → normal: the shared night
        entry reset keeps every later night independently open."""
        from bot.mozakere_force_finish_night import (
            mozakere_night_player_actions_closed,
        )
        from bot.bazpors_narrator import _reset_night_flags

        game = _game(night=1)
        for night in (1, 2, 3, 4, 5):
            # enter night N (fresh collection + shared reset)
            game.bazpors_narrator_night_count = night
            game.no_host_night_parallel_collect_active = True
            game.no_host_night_entry_dispatched_night = night
            _reset_night_flags(game)
            self.assertFalse(
                mozakere_night_player_actions_closed(game),
                f"Night {night} must be open on entry",
            )
            if night % 2 == 1:
                _force_finish(game)
                self.assertTrue(
                    mozakere_night_player_actions_closed(game),
                    f"Forced Night {night} must stay closed",
                )
                game.no_host_night_parallel_collect_active = False
            # exit the night normally


if __name__ == "__main__":
    unittest.main()
