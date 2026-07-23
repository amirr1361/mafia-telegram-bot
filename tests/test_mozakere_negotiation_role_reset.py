"""ریست پزشک/کارآگاه/تک‌تیرانداز پس از commit مذاکره — سناریوی مذاکره."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import _arm_night_actions_baseline
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE
from bot.no_host_mozakere_negotiation_reset import (
    MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML,
    apply_mozakere_negotiation_citizen_resets,
    reset_mozakere_detective_after_negotiation,
    reset_mozakere_sniper_after_negotiation,
    void_mozakere_doctor_night_pick,
)
from bot.no_host_night_ready import _detective_ready, _doctor_ready, all_no_host_parallel_night_ready
from bot.roles import detective as det_mod
from bot.roles import doctor as dr_mod
from bot.roles import sniper as sn_mod
from bot.roles.night_state import doctor_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_night_game(
    gm: GameManager,
    *,
    night: int = 2,
    with_doctor: bool = True,
) -> Game:
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_night_count = night
    game.no_host_night_parallel_collect_active = True
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = "night_start"
    gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS))
    gm.add_player(game, _p(11, "Neg", Role.MAFIA_NEGOTIATOR))
    gm.add_player(game, _p(20, "Det", Role.DETECTIVE))
    gm.add_player(game, _p(30, "Sn", Role.SNIPER))
    if with_doctor:
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
    game.mafia_ids.update({10, 11})
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
    game.no_host_negotiator_pick_confirmed = True
    _arm_night_actions_baseline(game)
    return game


class MozakereNightStartDoctorPanelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_doctor_panel_sent_immediately_at_night_start(self) -> None:
        from bot.no_host_doctor_night import start_no_host_doctor_night_flow

        game = _mozakere_night_game(self.gm)
        game.no_host_mafia_night1_done = False
        game.no_host_negotiator_pick_confirmed = False

        with patch(
            "bot.no_host_doctor_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_doctor_night.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register_panel:
            ok = await start_no_host_doctor_night_flow(
                AsyncMock(), game, self.gm, at_night_entry=True
            )

        self.assertTrue(ok)
        register_panel.assert_awaited_once()


class MozakereNegotiationDetectiveResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_no_reset_when_detective_not_confirmed(self) -> None:
        game = _mozakere_night_game(self.gm)
        game.no_host_detective_flow_active = True
        game.no_host_detective_dm_signature = "2:det:mozakere_pick"

        self.assertFalse(reset_mozakere_detective_after_negotiation(game))
        self.assertFalse(game.no_host_detective_pick_confirmed)
        self.assertEqual(game.no_host_detective_dm_signature, "2:det:mozakere_pick")

    def test_reset_when_detective_confirmed_clears_pick(self) -> None:
        game = _mozakere_night_game(self.gm)
        det_mod.commit_pick(game, 40)
        game.no_host_detective_pick_confirmed = True
        game.no_host_detective_dm_signature = "2:det:mozakere_pick"

        self.assertTrue(reset_mozakere_detective_after_negotiation(game))
        self.assertFalse(game.no_host_detective_pick_confirmed)
        self.assertIsNone(game.actions.detective_check)
        self.assertIsNone(game.no_host_detective_dm_signature)


class MozakereNegotiationSniperResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_no_reset_when_sniper_not_confirmed(self) -> None:
        game = _mozakere_night_game(self.gm)
        game.no_host_sniper_flow_active = True
        game.no_host_sniper_dm_signature = "2:sniper:mozakere_pick"

        self.assertFalse(reset_mozakere_sniper_after_negotiation(game))
        self.assertEqual(game.no_host_sniper_dm_signature, "2:sniper:mozakere_pick")

    def test_reset_one_shot_reverts_counter_and_clears_target(self) -> None:
        game = _mozakere_night_game(self.gm)
        sn_mod.commit_pick(game, 20)
        game.no_host_sniper_pick_confirmed = True
        self.assertEqual(game.mozakere_sniper_shots_used, 1)

        self.assertTrue(reset_mozakere_sniper_after_negotiation(game))
        self.assertEqual(game.mozakere_sniper_shots_used, 0)
        self.assertFalse(game.no_host_sniper_pick_confirmed)
        self.assertIsNone(sn_mod.night_target_uid(game))

    def test_reset_two_shots_reverts_counter(self) -> None:
        from bot.roles.night_state import sniper_night_state

        game = _mozakere_night_game(self.gm)
        game.mozakere_sniper_shots_used_at_night_start = 0
        game.mozakere_sniper_shots_used = 2
        sniper_night_state(game).night_target_uid = 20
        game.no_host_sniper_pick_confirmed = True

        self.assertTrue(reset_mozakere_sniper_after_negotiation(game))
        self.assertEqual(game.mozakere_sniper_shots_used, 0)
        self.assertIsNone(sn_mod.night_target_uid(game))


class MozakereNegotiationDoctorResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_confirmed_doctor_clears_saves_and_is_ready(self) -> None:
        game = _mozakere_night_game(self.gm)
        dr_mod.commit_pick(game, 20)
        game.no_host_doctor_pick_confirmed = True

        void_mozakere_doctor_night_pick(game)
        game.no_host_doctor_pick_confirmed = True

        self.assertEqual(dr_mod.save_uid_set_raw(game), set())
        self.assertTrue(_doctor_ready(game))

    def test_self_save_count_reverted_when_incremented(self) -> None:
        game = _mozakere_night_game(self.gm)
        doctor_night_state(game).snapshot_night_baseline()
        game.mozakere_doctor_self_save_count = 1
        dr_mod.commit_pick(game, 40)
        game.no_host_doctor_pick_confirmed = True

        void_mozakere_doctor_night_pick(game)

        self.assertEqual(game.mozakere_doctor_self_save_count, 0)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)


class MozakereNegotiationApplyResetsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_doctor_unconfirmed_gets_skip_message(self) -> None:
        game = _mozakere_night_game(self.gm)
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_dm_signature = "2:doc:night_entry"

        with patch(
            "bot.no_host_mozakere_negotiation_reset.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as update_panel, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            await apply_mozakere_negotiation_citizen_resets(
                AsyncMock(), game, self.gm
            )

        update_panel.assert_awaited()
        body = update_panel.call_args.args[3]
        self.assertEqual(body, MOZAKERE_DOCTOR_NEGOTIATION_SKIP_HTML)
        self.assertTrue(game.no_host_doctor_pick_confirmed)
        self.assertTrue(_doctor_ready(game))

    async def test_detective_confirmed_triggers_panel_resend(self) -> None:
        game = _mozakere_night_game(self.gm)
        det_mod.commit_pick(game, 40)
        game.no_host_detective_pick_confirmed = True

        with patch(
            "bot.no_host_mozakere_negotiation_reset.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_detective_night.start_no_host_detective_night_flow",
            new_callable=AsyncMock,
        ) as det_flow, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            await apply_mozakere_negotiation_citizen_resets(
                AsyncMock(), game, self.gm
            )

        det_flow.assert_awaited_once()

    async def test_sniper_confirmed_triggers_panel_resend(self) -> None:
        game = _mozakere_night_game(self.gm)
        sn_mod.commit_pick(game, 20)
        game.no_host_sniper_pick_confirmed = True

        with patch(
            "bot.no_host_mozakere_negotiation_reset.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_sniper_night.start_no_host_sniper_night_flow",
            new_callable=AsyncMock,
        ) as sn_flow, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            await apply_mozakere_negotiation_citizen_resets(
                AsyncMock(), game, self.gm
            )

        sn_flow.assert_awaited_once()

    async def test_readiness_after_resets_when_roles_done(self) -> None:
        game = _mozakere_night_game(self.gm)
        game.no_host_doctor_pick_confirmed = False
        game.no_host_detective_pick_confirmed = False
        game.no_host_sniper_pick_confirmed = False
        game.no_host_mafia_shot_done = True
        game.no_host_night1_hunter_done = True
        game.no_host_shiad_pick_confirmed = True
        game.no_host_interrog_pick_confirmed = True
        game.no_host_journalist_idle_confirmed = True

        with patch(
            "bot.no_host_mozakere_negotiation_reset.update_mirror_prompt_pair",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            await apply_mozakere_negotiation_citizen_resets(
                AsyncMock(), game, self.gm
            )

        self.assertTrue(_doctor_ready(game))
        self.assertFalse(all_no_host_parallel_night_ready(game))


class BazporsRegressionTests(unittest.TestCase):
    def test_bazpors_detective_readiness_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(20, "Det", Role.DETECTIVE))
        self.assertFalse(_detective_ready(game))
        game.no_host_detective_pick_confirmed = True
        self.assertTrue(_detective_ready(game))
