"""Room 91 — Bazpors Chaos (کی‌آس) day-entry guard at every no-host day route.

Historical audit (data/game_logs/91_20261105_075710.jsonl):

* Every no-host day start went through
  ``no_host_finish_day_start_after_table_inquiry`` (the only live
  day-entry path — ``no_host_begin_day_after_night`` has no callers),
  which syncs ``bazpors_ki_as_today`` and calls
  ``ensure_chaos_handshake_started`` for a 1-mafia/2-town day.
* Room 91's alive roster reached exactly 1 Mafia (MAFIA_BOSS) + 2 Town
  (DOCTOR + INTERROGATOR) at the Day-6 vote elimination (09:46:33).
  Chaos is a DAY phase, so the game correctly entered Night 6 first —
  and Night 6 stalled (mafia shot target never confirmed; last audit
  line 09:47:09, pending «تیم مافیا»). Day 7 — the Chaos day — never
  began. No day boundary was skipped; the trigger was never reached.

These tests lock the EXISTING behavior: chaos activates at every real
day-entry boundary (normal and force-finished night), only for the
1M+2T composition, exactly once, and never during the night.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.chaos_handshake import (
    chaos_handshake_phase_active,
    ensure_chaos_handshake_started,
)

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


def _game91(
    roster: tuple[tuple[int, str, Role], ...],
    *,
    night: int = 6,
    day: int = 6,
    step: str = "no_host_table_inquiry",
) -> Game:
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "R91"
    gm.games["R91"] = game
    for seat, (uid, name, role) in enumerate(roster, start=1):
        gm.add_player(game, _p(uid, seat, name, role))
    game.bot_assistant_user_id = ASSISTANT
    game.no_host_assistant_narrator_active = True
    game.no_host_intro_night_started = True
    game.bazpors_narrator_night_count = night
    game.bazpors_narrator_host_day = day
    game.bazpors_narrator_step = step
    game.no_host_night_parallel_collect_active = False
    game._gm = gm
    return game


# Room 91's exact endgame roster: Doctor (real player) + MAFIA_BOSS +
# INTERROGATOR = exactly 1 mafia + 2 town.
ROOM91_ROSTER = (
    (101, "Amir Latifi", Role.DOCTOR),
    (201, "بهنام-رییس مافیا", Role.MAFIA_BOSS),
    (301, "بابک-بازپرس", Role.INTERROGATOR),
)


def _day_entry(game: Game):
    from bot.no_host_table_inquiry import (
        no_host_finish_day_start_after_table_inquiry,
    )

    async def go():
        with patch(
            "bot.no_host_table_inquiry.broadcast_to_alive_players", new=AsyncMock()
        ) as bc, patch(
            "bot.no_host_table_inquiry.push_host_step", new=AsyncMock()
        ), patch(
            "bot.chaos_handshake.push_host_step", new=AsyncMock()
        ), patch(
            "bot.no_host_day_vote.send_no_host_day_vote_prompt", new=AsyncMock()
        ) as vote_prompt, patch(
            "bot.chaos_handshake.send_to_player", new=AsyncMock()
        ) as to_player, patch(
            "bot.chaos_handshake.send_to_bot_assistant", new=AsyncMock()
        ) as to_assistant:
            await no_host_finish_day_start_after_table_inquiry(
                object(), game, game._gm
            )
            return {
                "broadcast": bc,
                "vote_prompt": vote_prompt,
                "to_player": to_player,
                "to_assistant": to_assistant,
            }

    return asyncio.new_event_loop().run_until_complete(go())


class Room91ChaosDayEntryTests(unittest.TestCase):
    def test_room91_composition_activates_chaos_on_day_entry(self) -> None:
        """Normal night → day with the exact Room-91 1M+2T roster → the
        real day-entry path arms the Chaos handshake."""
        game = _game91(ROOM91_ROSTER)
        sent = _day_entry(game)

        self.assertTrue(game.bazpors_ki_as_today)
        self.assertTrue(chaos_handshake_phase_active(game))
        self.assertEqual(
            game.bazpors_narrator_step, "chaos_day_handshake"
        )
        self.assertEqual(game.bazpors_chaos_handshake_round, 1)
        # day broadcast announces the chaos day
        bcast = sent["broadcast"].call_args
        self.assertIn("فاز آشوب", str(bcast))
        # handshake prompt went to all three alive players + assistant panel
        self.assertEqual(sent["to_player"].await_count, 3)
        self.assertEqual(sent["to_assistant"].await_count, 1)
        # and no normal day-vote panel was delivered
        sent["vote_prompt"].assert_not_called()

    def test_force_finished_night_still_reaches_chaos_day(self) -> None:
        """Force-finished night → next day with exactly 1M+2T → chaos
        still activates (the Room-91 force-finish work must not regress
        the chaos day-entry)."""
        from bot.bazpors_force_finish_night import force_finish_bazpors_night
        from bot import app_state

        game = _game91(ROOM91_ROSTER, night=5, day=5, step="night_actions")
        game.no_host_night_parallel_collect_active = True

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
                await force_finish_bazpors_night(object(), game, game._gm)

        asyncio.new_event_loop().run_until_complete(go())

        self.assertTrue(game.bazpors_night_force_finished)
        self.assertEqual(game.bazpors_night_force_finished_night, 5)

        _day_entry(game)
        self.assertTrue(game.bazpors_ki_as_today)
        self.assertTrue(chaos_handshake_phase_active(game))
        self.assertEqual(game.bazpors_chaos_handshake_round, 1)

    def test_other_three_player_compositions_get_normal_day(self) -> None:
        """2 Mafia + 1 Town, and 4-alive 1M+3T: no chaos, normal day vote
        panel delivered."""
        from bot.bazpors_narrator import DAY_DISCUSS

        two_mafia_roster = (
            (101, "doc", Role.DOCTOR),
            (201, "boss", Role.MAFIA_BOSS),
            (202, "basic", Role.MAFIA_BASIC),
        )
        for roster, night, day in (
            (two_mafia_roster, 6, 6),
            (ROOM91_ROSTER + ((401, "cit", Role.CITIZEN),), 6, 6),
        ):
            game = _game91(roster, night=night, day=day)
            sent = _day_entry(game)
            self.assertFalse(game.bazpors_ki_as_today, roster)
            self.assertFalse(chaos_handshake_phase_active(game))
            self.assertEqual(game.bazpors_narrator_step, DAY_DISCUSS)
            self.assertEqual(game.bazpors_chaos_handshake_round, 0)
            self.assertEqual(sent["to_player"].await_count, 0)
            sent["vote_prompt"].assert_called_once()

    def test_chaos_engages_only_once(self) -> None:
        """Repeated entry calls never create a second handshake round."""
        game = _game91(ROOM91_ROSTER)
        _day_entry(game)
        first_round = game.bazpors_chaos_handshake_round
        self.assertEqual(first_round, 1)

        async def again():
            with patch("bot.chaos_handshake.send_to_player", new=AsyncMock()), patch(
                "bot.chaos_handshake.send_to_bot_assistant", new=AsyncMock()
            ), patch("bot.chaos_handshake.push_host_step", new=AsyncMock()):
                await ensure_chaos_handshake_started(object(), game, game._gm)

        asyncio.new_event_loop().run_until_complete(again())
        self.assertEqual(game.bazpors_chaos_handshake_round, 1)

    def test_chaos_not_actable_during_night(self) -> None:
        """While the night collection is running (Room 91's stall point),
        the day-start handshake is not engaged by any production day-path,
        and a stale handshake pick pressed in a night step is rejected."""
        from bot.bazpors_narrator import NIGHT_ACTIONS
        from bot.chaos_handshake import (
            handle_chaos_handshake_pick,
        )

        game = _game91(ROOM91_ROSTER)
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.no_host_night_parallel_collect_active = True

        # stale pick from a chaos panel pressed during the night phase:
        # the handshake phase is inactive there → rejected, no round.
        class _Cb:
            from_user = type("U", (), {"id": 101})()

            async def answer(self, *a, **k):
                self.answered = (a, k)

        cb = _Cb()
        mm = {}

        async def go():
            with patch("bot.chaos_handshake.send_to_player", new=AsyncMock()), patch(
                "bot.chaos_handshake.send_to_bot_assistant", new=AsyncMock()
            ), patch(
                "bot.chaos_handshake.safe_callback_answer", new=AsyncMock()
            ) as sanswer:
                await handle_chaos_handshake_pick(
                    object(),
                    game,
                    game._gm,
                    chooser_uid=101,
                    target_uid=201,
                    round_no=1,
                    actor_uid=101,
                    callback=cb,
                )
                return sanswer.await_count

        count = asyncio.new_event_loop().run_until_complete(go())
        # rejected with an invalid-phase alert (phase not active at night)
        self.assertEqual(count, 1, "stale night-phase pick must be answered invalid")
        self.assertEqual(game.bazpors_chaos_handshake_round, 0)
        self.assertFalse(game.bazpors_chaos_choices)
        self.assertEqual(game.bazpors_narrator_step, NIGHT_ACTIONS)

    def test_night_step_rejects_hand_resolve_only_day_steps(self) -> None:
        """ki_as day-resolve eligibility: DAY_DISCUSS/handshake steps only —
        a night-step callback can never act as a chaos day item."""
        from bot.bazpors_narrator import (
            DAY_DISCUSS,
            NIGHT_ACTIONS,
            _sync_ki_as_today,
            ki_as_hand_resolve_day_active,
        )

        game = _game91(ROOM91_ROSTER)
        _sync_ki_as_today(game, game._gm)
        self.assertTrue(game.bazpors_ki_as_today)

        game.bazpors_narrator_step = NIGHT_ACTIONS
        self.assertFalse(ki_as_hand_resolve_day_active(game, game._gm))
        game.bazpors_narrator_step = DAY_DISCUSS
        self.assertTrue(ki_as_hand_resolve_day_active(game, game._gm))

    def test_room91_sequence_explained_no_chaos_day_existed(self) -> None:
        """Historical explanation pinned as a test: at Room 91's real
        endgame steps, every logged day start held >= 4 alive (1M+3T or
        more) → ki_as_today False on every day_started_after_night —
        matching all five audit log entries; the 1M+2T roster only
        existed DURING Day 6 / Night 6, so day 7 was the Chaos day and it
        never began (Night 6 stalled, room closed silently)."""
        # day 6 start roster: Doctor + Hunter + Boss + Interrog = 1M + 3T
        day6_roster = ROOM91_ROSTER + ((401, "امیر-هانتر", Role.HUNTER),)
        game = _game91(day6_roster, night=5, day=6)
        _day_entry(game)
        self.assertFalse(game.bazpors_ki_as_today)
        self.assertFalse(chaos_handshake_phase_active(game))
        from bot.bazpors_narrator import DAY_DISCUSS

        self.assertEqual(game.bazpors_narrator_step, DAY_DISCUSS)


if __name__ == "__main__":
    unittest.main()
