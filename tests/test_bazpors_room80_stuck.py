"""Room 80 — Night 1 stuck waiting on Shiad + Interrogator (Bazpors only).

Reconstructed from audit log 80_20260624_100143.jsonl:
- 12-player bazpors no_host, Night 1 parallel collect
- Day 1 elim: Mafia Boss (seat 8)
- All night actors confirmed except Shiad (seat 1) and Interrogator (seat 4)
- parallel_night_collect_finished never fired
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_interrogator_night import (
    _interrog_panel_already_sent_for_night,
    dispatch_no_host_interrogator_night_panel,
    start_no_host_interrogator_night_flow,
)
from bot.no_host_night_ready import (
    all_no_host_parallel_night_ready,
    explain_bazpors_night_stuck,
    maybe_finish_no_host_parallel_night,
)
from bot.no_host_shiad_night import dispatch_no_host_shiad_night_panel
from tests.no_host_flow_harness import _callback


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def _room80_night1_stuck_game(gm: GameManager):
    """Night 1 state after hunter done — matches Room 80 audit log end."""
    game = gm.create_game(
        host_id=108214166,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "80"
    game.bot_assistant_user_id = 108214166
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    game.no_host_night_entry_dispatched_night = 1

    roster = (
        (30006146, 1, "Ehsan Pilzoor", Role.SHIAD),
        (108214166, 2, "Amir Latifi", Role.NATO),
        (106882355, 3, "Ehsan Goroohi", Role.CITIZEN),
        (313243161, 4, "Hassan Khosravi", Role.INTERROGATOR),
        (479369026, 5, "Behnam", Role.CITIZEN),
        (73526314, 6, "Abolfazl Alizadeh", Role.DOCTOR),
        (510540123, 7, "Erfan A", Role.SNIPER),
        (131662695, 8, "Hamed", Role.MAFIA_BOSS, False),
        (504542027, 9, "Ghasem", Role.DETECTIVE),
        (91576703, 10, "R Rah", Role.HUNTER),
        (126512798, 11, "Hassan", Role.RUINTAN),
        (344288807, 12, "Ram Moe", Role.MAFIA_BASIC),
    )
    for row in roster:
        uid, seat, name, role = row[0], row[1], row[2], row[3]
        alive = row[4] if len(row) > 4 else True
        gm.add_player(game, _p(uid, seat, name, role, alive=alive))

    game.no_host_citizen_night_confirmed_uids = [106882355, 479369026]
    game.no_host_ruintan_night_confirmed = True
    game.no_host_night1_hunter_done = True
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    game.bazpors_mafia_shot_registered = True
    game.no_host_detective_pick_confirmed = True
    game.no_host_doctor_pick_confirmed = True
    game.no_host_sniper_pick_confirmed = True

    game.no_host_shiad_dm_signature = "1:shiad:night_entry"
    game.no_host_shiad_flow_active = True
    game.no_host_shiad_pick_confirmed = False

    game.no_host_interrog_dm_signature = "1:interrog:night_entry"
    game.no_host_interrog_flow_active = True
    game.no_host_interrog_ui_phase = "int1"
    game.no_host_interrog_pick_confirmed = False

    return game


def _arm_all_but_shiad_interrog(game) -> None:
    game.no_host_citizen_night_confirmed_uids = [106882355, 479369026]
    game.no_host_ruintan_night_confirmed = True
    game.no_host_night1_hunter_done = True
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    game.no_host_detective_pick_confirmed = True
    game.no_host_doctor_pick_confirmed = True
    game.no_host_sniper_pick_confirmed = True


class Room80Night1DiagnosticTests(unittest.TestCase):
    def test_diagnostic_identifies_shiad_and_interrogator_blockers(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)

        self.assertFalse(all_no_host_parallel_night_ready(game))
        report = explain_bazpors_night_stuck(game, gm)
        self.assertIn("night 1", report.lower())
        self.assertIn("no_host_shiad_pick_confirmed=False", report)
        self.assertIn("no_host_interrog_pick_confirmed=False", report)
        self.assertIn("Ehsan Pilzoor", report)
        self.assertIn("Hassan Khosravi", report)
        self.assertIn("sgt", report)
        self.assertIn("nii1", report)

    def test_dead_mafia_boss_does_not_block(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        _arm_all_but_shiad_interrog(game)
        game.no_host_shiad_pick_confirmed = True
        game.no_host_interrog_pick_confirmed = True
        self.assertTrue(all_no_host_parallel_night_ready(game))


class Room80Night1FixTests(unittest.IsolatedAsyncioTestCase):
    async def test_stuck_state_completes_after_pending_roles_confirm(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        bot = AsyncMock()

        game.no_host_shiad_pick_confirmed = True
        game.no_host_shiad_flow_active = False
        self.assertFalse(all_no_host_parallel_night_ready(game))

        game.no_host_interrog_pick_confirmed = True
        game.no_host_interrog_flow_active = False
        self.assertTrue(all_no_host_parallel_night_ready(game))

        with patch(
            "bot.no_host_night_ready.push_host_step",
            new_callable=AsyncMock,
        ) as push:
            finished = await maybe_finish_no_host_parallel_night(bot, game, gm)
        self.assertTrue(finished)
        self.assertFalse(game.no_host_night_parallel_collect_active)
        push.assert_awaited_once()

    async def test_shiad_stale_flow_rearmed_on_dispatch(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        game.no_host_shiad_flow_active = False
        bot = AsyncMock()
        with patch(
            "bot.no_host_shiad_night.start_no_host_shiad_night_flow",
            new_callable=AsyncMock,
        ) as start_flow:
            await dispatch_no_host_shiad_night_panel(bot, game, gm)
            start_flow.assert_not_awaited()
        self.assertTrue(game.no_host_shiad_flow_active)

    async def test_interrogator_duplicate_dispatch_does_not_reset_panel(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        game.no_host_interrog_flow_active = False
        self.assertTrue(_interrog_panel_already_sent_for_night(game, 1))
        bot = AsyncMock()
        with patch(
            "bot.no_host_interrogator_night.start_no_host_interrogator_night_flow",
            new_callable=AsyncMock,
        ) as start_flow:
            await dispatch_no_host_interrogator_night_panel(bot, game, gm)
            start_flow.assert_not_awaited()
        self.assertEqual(game.no_host_interrog_dm_signature, "1:interrog:night_entry")
        self.assertTrue(game.no_host_interrog_flow_active)

    async def test_interrogator_second_start_with_flow_sig_skips_resend(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        bot = AsyncMock()
        with patch(
            "bot.no_host_interrogator_night.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as publish:
            sent = await start_no_host_interrogator_night_flow(bot, game, gm)
            self.assertFalse(sent)
            publish.assert_not_awaited()
        self.assertEqual(game.no_host_interrog_dm_signature, "1:interrog:night_entry")

    async def test_shiad_confirm_advances_night_readiness(self) -> None:
        from bot.no_host_shiad_night import dispatch_no_host_shiad_night

        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        _arm_all_but_shiad_interrog(game)
        game.no_host_interrog_pick_confirmed = True
        bot = AsyncMock()
        det_uid = 504542027
        cb = _callback(30006146)
        with patch(
            "bot.no_host_shiad_night.publish_no_host_night_wait_panel",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await dispatch_no_host_shiad_night(
                cb,
                bot,
                game,
                gm,
                sh_uid=30006146,
                actor_uid=30006146,
                act="sgt",
                tid=det_uid,
            )
            await dispatch_no_host_shiad_night(
                cb,
                bot,
                game,
                gm,
                sh_uid=30006146,
                actor_uid=30006146,
                act="sgc",
                tid=0,
            )
        self.assertTrue(game.no_host_shiad_pick_confirmed)
        self.assertTrue(all_no_host_parallel_night_ready(game))

    async def test_dead_interrogator_does_not_block_readiness(self) -> None:
        gm = GameManager()
        game = _room80_night1_stuck_game(gm)
        _arm_all_but_shiad_interrog(game)
        game.no_host_shiad_pick_confirmed = True
        intr = game.players[313243161]
        intr.is_alive = False
        self.assertTrue(_interrogator_ready_dead_skip(game))

    async def test_mason_explain_routes_to_mason_diagnostic(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.room_code = "m1"
        report = explain_bazpors_night_stuck(game, gm)
        self.assertIn("Mason", report)


def _interrogator_ready_dead_skip(game) -> bool:
    from bot.no_host_night_ready import _interrogator_ready

    return _interrogator_ready(game)


if __name__ == "__main__":
    unittest.main()
