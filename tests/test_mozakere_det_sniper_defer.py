"""پنل‌های فوری کارآگاه/تک‌تیرانداز در شب مذاکره (بدون انتظار برای مافیا)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_mafia_night1 import MAFIA_ACTION_NEGOTIATE, MAFIA_ACTION_SHOT
from bot.no_host_mozakere_mafia_gate import mozakere_mafia_night_action_finalized
from bot.no_host_night_ready import _detective_ready, _sniper_ready
from bot.roles.mozakere_sniper import can_mozakere_sniper_shoot


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_12p(gm: GameManager, *, night: int = 2):
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
    gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS))
    gm.add_player(game, _p(11, "Neg", Role.MAFIA_NEGOTIATOR))
    gm.add_player(game, _p(20, "Det", Role.DETECTIVE))
    gm.add_player(game, _p(30, "Sn", Role.SNIPER))
    game.mafia_ids.update({10, 11})
    return game


class MozakereMafiaGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_mafia_not_finalized_before_shot(self) -> None:
        game = _mozakere_12p(self.gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        self.assertFalse(mozakere_mafia_night_action_finalized(game))

    def test_mafia_finalized_after_shot(self) -> None:
        game = _mozakere_12p(self.gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        self.assertTrue(mozakere_mafia_night_action_finalized(game))

    def test_mafia_finalized_after_negotiation(self) -> None:
        game = _mozakere_12p(self.gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
        game.no_host_negotiator_pick_confirmed = True
        self.assertTrue(mozakere_mafia_night_action_finalized(game))

    def test_detective_not_ready_before_pick_even_if_mafia_pending(self) -> None:
        game = _mozakere_12p(self.gm)
        game.no_host_mafia_night1_done = False
        self.assertFalse(_detective_ready(game))

    def test_detective_not_ready_after_mafia_until_pick(self) -> None:
        game = _mozakere_12p(self.gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        self.assertFalse(_detective_ready(game))

    def test_sniper_not_ready_before_pick(self) -> None:
        game = _mozakere_12p(self.gm)
        self.assertFalse(_sniper_ready(game))

    def test_sniper_ready_when_no_shots_left(self) -> None:
        game = _mozakere_12p(self.gm)
        game.mozakere_sniper_shots_used = 2
        self.assertFalse(can_mozakere_sniper_shoot(game))
        self.assertTrue(_sniper_ready(game))


class MozakereImmediatePanelFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_detective_pick_at_night_entry_without_mafia_finalized(self) -> None:
        from bot.no_host_detective_night import start_no_host_detective_night_flow

        game = _mozakere_12p(self.gm)
        game.bazpors_narrator_step = "night_start"
        game.no_host_mafia_night1_done = False

        with patch(
            "bot.no_host_detective_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_detective_night.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register_panel:
            ok = await start_no_host_detective_night_flow(
                AsyncMock(), game, self.gm, at_night_entry=True
            )

        self.assertTrue(ok)
        register_panel.assert_awaited_once()
        self.assertIn("mozakere_pick", game.no_host_detective_dm_signature or "")

    async def test_sniper_pick_at_night_entry_without_mafia_finalized(self) -> None:
        from bot.no_host_sniper_night import start_no_host_sniper_night_flow

        game = _mozakere_12p(self.gm)
        game.bazpors_narrator_step = "night_start"
        game.no_host_mafia_night1_done = False

        with patch(
            "bot.no_host_sniper_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_sniper_night.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register_panel:
            ok = await start_no_host_sniper_night_flow(
                AsyncMock(), game, self.gm, at_night_entry=True
            )

        self.assertTrue(ok)
        register_panel.assert_awaited_once()
        self.assertIn("mozakere_pick", game.no_host_sniper_dm_signature or "")

    async def test_sniper_no_panel_when_no_shots(self) -> None:
        from bot.no_host_sniper_night import start_no_host_sniper_night_flow

        game = _mozakere_12p(self.gm)
        game.mozakere_sniper_shots_used = 2

        with patch(
            "bot.no_host_sniper_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_sniper_night.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register_panel:
            ok = await start_no_host_sniper_night_flow(
                AsyncMock(), game, self.gm, at_night_entry=True
            )

        self.assertFalse(ok)
        register_panel.assert_not_awaited()
        self.assertTrue(game.no_host_sniper_pick_confirmed)

    def test_bazpors_detective_ready_unchanged(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(20, "Det", Role.DETECTIVE))
        self.assertFalse(_detective_ready(game))


class MozakereNoBeginNightActionsPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _mozakere_night_start_game(self):
        game = _mozakere_12p(self.gm, night=1)
        game.bazpors_narrator_step = "night_start"
        game.bot_assistant_user_id = 1
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        game.no_host_night1_hunter_done = True
        return game

    def test_night_start_panel_has_no_begin_night_actions_button(self) -> None:
        from bot.bazpors_narrator import build_host_message_and_keyboard

        game = self._mozakere_night_start_game()
        text, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertNotIn("شروع اجرای نقش‌های شب", text)
        self.assertNotIn("همه بازیکنان را بخوابان", text)
        self.assertIsNone(kb)

    def test_bazpors_night_start_still_has_begin_night_actions_when_needed(self) -> None:
        from bot.bazpors_narrator import build_host_message_and_keyboard

        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 2
        game.bazpors_narrator_step = "night_start"
        game.no_host_assistant_narrator_active = True
        game.no_host_night1_hunter_done = True
        game.no_host_mafia_night1_done = True
        text, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("شروع اجرای نقش‌های شب", text)
        self.assertIsNotNone(kb)


class MozakereMafiaShotFinalizeNoLegacyPromptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_finalize_shot_does_not_dispatch_det_sn_panels(self) -> None:
        from bot.no_host_mafia_shot import _finalize_mafia_shot

        game = _mozakere_12p(self.gm, night=1)
        game.bazpors_narrator_step = "night_start"
        game.bot_assistant_user_id = 1
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_flow_active = True

        with patch(
            "bot.no_host_mafia_shot.push_host_step",
            new_callable=AsyncMock,
        ) as push_host, patch(
            "bot.no_host_mafia_shot.finalize_no_host_role_pick_message",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_shot.notify_mafia_team_shot_result",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_detective_night.start_no_host_detective_night_flow",
            new_callable=AsyncMock,
        ) as det_flow, patch(
            "bot.no_host_sniper_night.start_no_host_sniper_night_flow",
            new_callable=AsyncMock,
        ) as sn_flow, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ) as maybe_finish:
            await _finalize_mafia_shot(
                AsyncMock(),
                game,
                self.gm,
                mafia_uid=10,
                actor_uid=10,
                target_uid=20,
            )

        push_host.assert_not_awaited()
        det_flow.assert_not_awaited()
        sn_flow.assert_not_awaited()
        maybe_finish.assert_awaited_once()
