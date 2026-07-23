"""شبیه‌سازی جریان شب/روز ماسون — dispatch، مشورت، readiness."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_mafia_team
from bot.mason_helper_flow import (
    build_mason_mafia_consult_html,
    build_mason_team_consult_html,
    handle_mason_helper_action,
    mason_team_consult_required,
    send_mason_team_consult_prompt,
)
from bot.mason_intro_flow import (
    build_mason_intro_night_civilian_html,
    build_mason_intro_night_mafia_dm_html,
    deliver_mason_intro_night_started_messages,
)
from bot.mason_night_entry import MASON_NIGHT_WAIT_TEXT
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.mason_night_role import MSS_OK
from bot.models import Role

from tests.mason_simulation_harness import MASON_COUNTS, MasonSimHarness


class MasonSimulationConsultationTests(unittest.IsolatedAsyncioTestCase):
    async def test_night_one_mafia_consult_only(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.game.bazpors_narrator_night_count = 1
        self.assertFalse(mason_team_consult_required(h.game))
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_mafia_consult_prompt",
            new_callable=AsyncMock,
        ) as mafia, patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new_callable=AsyncMock,
        ) as team:
            from bot.mason_helper_flow import mason_on_no_host_entered_night

            await mason_on_no_host_entered_night(bot, h.game, h.gm)
        mafia.assert_awaited_once()
        team.assert_not_awaited()

    async def test_night_two_team_consult_after_mafia(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.game.bazpors_narrator_night_count = 2
        self.assertTrue(mason_team_consult_required(h.game))
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_helper_flow.send_mason_night_start_prompt",
            new_callable=AsyncMock,
        ) as night, patch(
            "bot.mason_helper_flow.send_mason_team_consult_prompt",
            new_callable=AsyncMock,
        ) as team:
            await handle_mason_helper_action(
                cb,
                bot,
                h.game,
                h.gm,
                assistant_uid=h.assistant_uid,
                actor_uid=h.assistant_uid,
                act="ok",
                kind="consult",
            )
        team.assert_awaited_once()
        night.assert_not_awaited()

    async def test_team_consult_not_sent_before_night_two(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.game.bazpors_narrator_night_count = 1
        with patch(
            "bot.mason_helper_flow.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as reg:
            await send_mason_team_consult_prompt(h.bot, h.game)
        reg.assert_not_awaited()


class MasonSimulationIntroTests(unittest.IsolatedAsyncioTestCase):
    async def test_apache_civilian_mafia_distinct_intros(self) -> None:
        from bot.models import Player

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(user_id=10, full_name="Ap", username=None, role=Role.APACHE))
        gm.add_player(game, Player(user_id=11, full_name="Spy", username=None, role=Role.SPY))
        gm.add_player(game, Player(user_id=20, full_name="Doc", username=None, role=Role.DOCTOR))
        sent: dict[int, str] = {}

        async def _capture(_bot, uid, text, **kw):
            sent[uid] = text

        with patch("bot.mason_intro_flow.safe_send_message", side_effect=_capture):
            await deliver_mason_intro_night_started_messages(MagicMock(), game)

        civ = build_mason_intro_night_civilian_html()
        self.assertEqual(sent[10], civ)
        self.assertIn("تیم مافیا", sent[11])
        self.assertEqual(sent[20], civ)


class MasonSimulationNightDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_night_dispatch_no_exceptions_all_counts(self) -> None:
        gm = GameManager()
        for n in MASON_COUNTS:
            with self.subTest(players=n):
                h = MasonSimHarness.build(gm, max_players=n)
                h.setup_night(night_count=1)
                errors = await h.dispatch_night_entry()
                self.assertEqual(errors, [], f"dispatch errors: {errors}")

    async def test_core_role_panels_dispatched(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        await h.dispatch_night_entry()
        for role in (
            Role.SABOTEUR,
            Role.DOCTOR,
            Role.SNIPER,
            Role.GUNMAN,
            Role.BODYGUARD,
            Role.MASON,
        ):
            with self.subTest(role=role.value):
                self.assertTrue(
                    h.has_prompt_for_role(role),
                    f"missing panel for {role}",
                )

    async def test_optional_roles_by_count(self) -> None:
        gm = GameManager()
        for n in (15, 16, 18):
            with self.subTest(players=n):
                h = MasonSimHarness.build(gm, max_players=n)
                h.setup_night(night_count=1)
                await h.dispatch_night_entry()
                if n >= 16:
                    self.assertTrue(h.has_prompt_for_role(Role.DETECTIVE))
                if n >= 18:
                    self.assertTrue(h.has_prompt_for_role(Role.NATASHA))
                    self.assertTrue(h.has_prompt_for_role(Role.PRIEST))

    async def test_observer_mirrors_on_night_dispatch(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        await h.dispatch_night_entry()
        self.assertGreater(h.observer_mirror_count(), 0)

    async def test_gather_dispatch_surfaces_exceptions(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        with patch(
            "bot.mason_night_role.dispatch_mason_saboteur_panel",
            side_effect=RuntimeError("simulated dispatch failure"),
        ):
            errors = await h.dispatch_night_entry_gather()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)


class MasonSimulationNoStuckTests(unittest.IsolatedAsyncioTestCase):
    async def test_minimal_night_actions_reach_readiness(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        await h.dispatch_night_entry()
        await h.complete_minimal_night_actions()
        h.assert_readiness(expected=True)

    async def test_sniper_no_shot_commander_chain_finishes(self) -> None:
        from bot.mason_night_role import MSS_NONE, dispatch_mason_night_role

        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        h.game.no_host_night_parallel_collect_active = True
        h.game.bazpors_narrator_step = NIGHT_START
        sn_uid = h.holder_uid(Role.SNIPER)
        assert sn_uid is not None
        cb = MagicMock()
        cb.answer = AsyncMock()
        with (
            patch(
                "bot.mason_night_role.finalize_no_host_role_pick_message",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_role.dispatch_mason_commander_panel",
                new_callable=AsyncMock,
            ),
            patch(
                "bot.mason_night_ready.maybe_finish_mason_parallel_night",
                new_callable=AsyncMock,
            ),
        ):
            await dispatch_mason_night_role(
                cb,
                h.bot,
                h.game,
                h.gm,
                as_uid=sn_uid,
                actor_uid=sn_uid,
                act=MSS_NONE,
                tid=0,
            )
        self.assertTrue(h.game.mason_night_sniper_confirmed)

    async def test_exhausted_sniper_role_ok_required(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=3)
        h.game.mason_sniper_bullets_spent = 3
        h.arm_mafia_shot_done()
        for flag in (
            "mason_night_saboteur_confirmed",
            "mason_night_doctor_confirmed",
            "mason_night_commander_confirmed",
            "mason_night_gunner_confirmed",
            "mason_night_guardian_confirmed",
            "mason_night_mason_confirmed",
            "mason_night_detective_confirmed",
        ):
            setattr(h.game, flag, True)
        sn_uid = h.holder_uid(Role.SNIPER)
        assert sn_uid is not None
        h.game.no_host_night_parallel_collect_active = True
        self.assertFalse(all_mason_parallel_night_ready(h.game))
        await h.click_role(as_uid=sn_uid, act=MSS_OK)
        self.assertTrue(h.game.mason_night_sniper_confirmed)

    async def test_multi_night_bullet_counter_persists(self) -> None:
        from bot.mason_night_entry import reset_mason_current_night_selections
        from bot.roles import mason_commander as ms_cmd
        from bot.roles import mason_sniper as ms_sn

        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        sn_uid = h.holder_uid(Role.SNIPER)
        assert sn_uid is not None
        targets = [
            uid
            for uid in h.alive_uids_except(sn_uid)
            if not is_mafia_team(h.game.players[uid].role)
        ][:3]
        ms_sn.commit_mason_sniper_night_selection(h.game, targets[:2])
        ms_cmd.commit_mason_commander_approval(h.game, targets[:2])
        reset_mason_current_night_selections(h.game)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(h.game), 2)
        ms_sn.commit_mason_sniper_night_selection(h.game, [targets[2]])
        ms_cmd.commit_mason_commander_approval(h.game, [targets[2]])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(h.game), 3)
        h.setup_night(night_count=3)
        await h.dispatch_night_entry()
        sn_prompts = h.prompts_for_uid(sn_uid)
        from bot.mason_night_role import MASON_NO_NIGHT_PICK_WAIT_TEXT

        self.assertTrue(
            any(MASON_NO_NIGHT_PICK_WAIT_TEXT in p.text for p in sn_prompts),
            "expected sniper no-pick role panel for exhausted sniper",
        )
        self.assertFalse(
            any(MASON_NIGHT_WAIT_TEXT in p.text for p in sn_prompts),
            "generic wait must not duplicate sniper role panel",
        )
        self.assertFalse(
            any("بدون شلیک" in p.text for p in sn_prompts),
            "sniper should not get selection panel when bullets exhausted",
        )


class MasonSimulationHelperTextTests(unittest.TestCase):
    def test_consult_copy(self) -> None:
        self.assertIn("مشورت", build_mason_mafia_consult_html())
        self.assertIn("تیم ماسون", build_mason_team_consult_html())
