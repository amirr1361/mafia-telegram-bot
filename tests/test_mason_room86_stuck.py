"""Room 86 — گادفادر مرده، ناتو زنده، شب گیر نکند."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_entry import dispatch_mason_night_entry_panels
from bot.mason_night_ready import (
    _mafia_ready,
    all_mason_parallel_night_ready,
    explain_mason_night_stuck,
)
from bot.models import Player, Role
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_NATO,
    MAFIA_ACTION_SHOT,
    _finalize_mafia_night1,
    mafia_night1_panel_delivered,
    start_no_host_night1_mafia_flow,
)
from bot.observer_delivery import mirror_ui_claim_key


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 14):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_step = NIGHT_START
    game.no_host_night_parallel_collect_active = True
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 900
    return game


def _populate_room86(game, gm: GameManager) -> None:
    gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
    gm.add_player(game, _p(2, "NATO", Role.NATO))
    gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
    gm.add_player(game, _p(4, "Spy", Role.SPY))
    gm.add_player(game, _p(5, "Apache", Role.APACHE))
    gm.add_player(game, _p(6, "Doc", Role.DOCTOR))
    gm.add_player(game, _p(7, "Sniper", Role.SNIPER))
    gm.add_player(game, _p(8, "Cmd", Role.COMMANDER))


def _patch_other_night_panels():
    return (
        patch("bot.mason_night_role.dispatch_mason_saboteur_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_doctor_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_sniper_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_gunner_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_guardian_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_mason_recruit_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_detective_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_natasha_panel", new_callable=AsyncMock),
        patch("bot.mason_night_role.dispatch_mason_priest_panel", new_callable=AsyncMock),
        patch("bot.mason_night_entry._dispatch_mason_wait_panels", new_callable=AsyncMock),
    )


class MasonRoom86NatoPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_godfather_dead_nato_unused_receives_mafia_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        _populate_room86(game, gm)
        bot = AsyncMock()
        sent: list[int] = []

        async def capture(_bot, _game, uid, _text, _kb, _gm):
            sent.append(uid)
            game.no_host_mafia_night1_refs[uid] = (uid, 1, "menu")

        patches = _patch_other_night_panels()
        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt", side_effect=capture
        ), patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            await dispatch_mason_night_entry_panels(bot, game, gm)

        self.assertEqual(sent, [2])
        self.assertTrue(game.no_host_mafia_night1_flow_active)
        self.assertEqual(game.no_host_mafia_night1_chooser_uid, 2)

    async def test_night_entry_does_not_stuck_before_panel_sent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        _populate_room86(game, gm)
        bot = AsyncMock()

        async def capture(_bot, _game, uid, _text, _kb, _gm):
            game.no_host_mafia_night1_refs[uid] = (uid, 1, "menu")

        patches = _patch_other_night_panels()
        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt", side_effect=capture
        ), patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            await dispatch_mason_night_entry_panels(bot, game, gm)

        self.assertFalse(game.no_host_mafia_night1_done)
        self.assertTrue(mafia_night1_panel_delivered(game, 2))
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("holder=NATO", report)
        self.assertIn("panel_sent=True", report)

    async def test_stale_dead_godfather_flow_restarts_for_nato(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        game.mason_night_entry_dispatched_night = 3
        _populate_room86(game, gm)
        game.no_host_mafia_night1_flow_active = True
        game.no_host_mafia_night1_chooser_uid = 1
        game.no_host_mafia_night1_panel_uids = [1]
        bot = AsyncMock()
        sent: list[int] = []

        async def capture(_bot, _game, uid, _text, _kb, _gm):
            sent.append(uid)
            game.no_host_mafia_night1_refs[uid] = (uid, 1, "menu")

        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt", side_effect=capture
        ):
            await start_no_host_night1_mafia_flow(bot, game, gm)

        self.assertEqual(sent, [2])
        self.assertEqual(game.no_host_mafia_night1_chooser_uid, 2)


class MasonRoom86MafiaActionReadyTests(unittest.IsolatedAsyncioTestCase):
    async def test_nato_shot_marks_mafia_ready(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_room86(game, gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_night1_chooser_uid = 2
        game.no_host_mafia_night1_panel_uids = [2]
        game.no_host_mafia_shot_done = True
        self.assertTrue(_mafia_ready(game))

    async def test_nato_choice_waits_for_nato_subflow(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_room86(game, gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NATO
        game.no_host_mafia_night1_chooser_uid = 2
        game.no_host_mafia_shot_done = True
        self.assertFalse(_mafia_ready(game))
        game.no_host_mafia_nato_done = True
        self.assertTrue(_mafia_ready(game))

    async def test_nato_shot_flow_advances_when_completed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        _populate_room86(game, gm)
        bot = AsyncMock()

        async def capture(_bot, _game, uid, _text, _kb, _gm):
            game.no_host_mafia_night1_refs[uid] = (uid, 1, "menu")

        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt", side_effect=capture
        ), patch(
            "bot.no_host_mafia_night1._edit_mafia_prompt", new_callable=AsyncMock
        ), patch(
            "bot.no_host_mafia_night1.notify_all_alive_mafia_team",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_night1.maybe_start_shiad_parallel_night_panels",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            await _finalize_mafia_night1(
                bot,
                game,
                gm,
                mafia_uid=2,
                actor_uid=2,
                action=MAFIA_ACTION_SHOT,
            )

        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertEqual(game.no_host_mafia_night1_chosen_action, MAFIA_ACTION_SHOT)
        self.assertTrue(game.no_host_mafia_shot_flow_active)


class MasonRoom86DiagnosticTests(unittest.TestCase):
    def test_explain_identifies_mafia_panel_not_sent(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 3
        game.mason_night_entry_dispatched_night = 3
        _populate_room86(game, gm)
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Waiting for Mafia action: holder=NATO", report)
        self.assertIn("panel_sent=False", report)
        self.assertIn("no_host_mafia_night1_done=False", report)
        self.assertNotIn("holder=Godfather", report)

    def test_explain_after_fix_no_godfather_blocker(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_room86(game, gm)
        game.no_host_mafia_night1_refs[2] = (2, 1, "menu")
        game.no_host_mafia_night1_panel_uids = [2]
        game.no_host_mafia_night1_flow_active = True
        game.no_host_mafia_night1_chooser_uid = 2
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("No blocker: Godfather dead, skipped.", report)
        self.assertNotIn("holder=Godfather", report)

    def test_dead_godfather_does_not_block_mafia_readiness_when_done(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_room86(game, gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_night1_chooser_uid = 2
        game.no_host_mafia_shot_done = True
        self.assertTrue(_mafia_ready(game))


class MasonRoom86Night4SaboteurShotTests(unittest.IsolatedAsyncioTestCase):
    """Night 4 — گادفادر مرده، ناتو غیرفعال، خرابکار شلیک می‌کند."""

    def _night4_game(self, gm: GameManager):
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 4
        game.mason_nato_used = True
        gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
        gm.add_player(game, _p(2, "NATO", Role.NATO, alive=False))
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(13, "Erfan", Role.RUINTAN))
        gm.add_player(game, _p(6, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(7, "Sniper", Role.SNIPER))
        gm.add_player(game, _p(8, "Cmd", Role.COMMANDER))
        return game

    async def test_saboteur_receives_direct_shot_panel_night4(self) -> None:
        gm = GameManager()
        game = self._night4_game(gm)
        bot = AsyncMock()
        sent: list[int] = []

        async def capture(_bot, _game, uid, _text, _kb):
            sent.append(uid)
            nc = game.bazpors_narrator_night_count
            key = mirror_ui_claim_key(game.room_code, f"mafia_shot_n{nc}", uid)
            game.mirror_prompt_messages[key] = {"player": (uid, 1)}

        with patch(
            "bot.no_host_mafia_shot._sync_mafia_shot_mirror_panel",
            side_effect=capture,
        ), patch(
            "bot.no_host_mafia_night1.maybe_start_shiad_parallel_night_panels",
            new_callable=AsyncMock,
        ):
            await start_no_host_night1_mafia_flow(bot, game, gm)

        self.assertEqual(sent, [3])
        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertEqual(game.no_host_mafia_night1_chosen_action, MAFIA_ACTION_SHOT)

    async def test_saboteur_shot_sets_flags_and_calls_maybe_finish(self) -> None:
        from bot.no_host_mafia_shot import _finalize_mafia_shot

        gm = GameManager()
        game = self._night4_game(gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_night1_chooser_uid = 3
        game.no_host_mafia_night1_panel_uids = [3]
        game.no_host_mafia_shot_flow_active = True
        bot = AsyncMock()

        with patch(
            "bot.no_host_mafia_shot.finalize_no_host_role_pick_message",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_shot.notify_mafia_team_shot_result",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ) as maybe_finish, patch(
            "bot.mason_night_role.dispatch_mason_saboteur_panel",
            new_callable=AsyncMock,
        ) as sab_panel:
            await _finalize_mafia_shot(
                bot,
                game,
                gm,
                mafia_uid=3,
                actor_uid=3,
                target_uid=13,
            )

        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertTrue(game.no_host_mafia_shot_done)
        self.assertEqual(game.actions.mafia_target, 13)
        maybe_finish.assert_awaited_once()
        sab_panel.assert_awaited_once()

    async def test_shot_without_night1_done_flag_is_repaired(self) -> None:
        from bot.no_host_mafia_shot import _finalize_mafia_shot

        gm = GameManager()
        game = self._night4_game(gm)
        game.no_host_mafia_night1_done = False
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_night1_panel_uids = [3]
        bot = AsyncMock()

        with patch(
            "bot.no_host_mafia_shot.finalize_no_host_role_pick_message",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_shot.notify_mafia_team_shot_result",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ), patch(
            "bot.mason_night_role.dispatch_mason_saboteur_panel",
            new_callable=AsyncMock,
        ):
            await _finalize_mafia_shot(
                bot,
                game,
                gm,
                mafia_uid=3,
                actor_uid=3,
                target_uid=13,
            )

        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertTrue(game.no_host_mafia_shot_done)
        self.assertTrue(_mafia_ready(game))

    def test_diagnostic_shows_mafia_complete_and_next_blocker(self) -> None:
        gm = GameManager()
        game = self._night4_game(gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_night1_chooser_uid = 3
        game.no_host_mafia_shot_done = True
        from bot.roles.night_state import mafia_night_state

        mafia_night_state(game).commit_shot(13)
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True

        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Mafia action complete", report)
        self.assertIn("shot", report.lower())
        self.assertIn("Waiting for Saboteur", report)
        self.assertIn("mason_night_saboteur_confirmed=False", report)
        self.assertNotIn("Waiting for Mafia action", report)

    def test_diagnostic_identifies_ruintan_wait_ok(self) -> None:
        gm = GameManager()
        game = self._night4_game(gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_shot_done = True
        game.mason_night_saboteur_confirmed = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True

        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Mafia action complete", report)
        self.assertIn("Waiting for no-action OK", report)
        self.assertIn("Erfan", report)


class MasonRoom86UnchangedScenarios(unittest.TestCase):
    def test_bazpors_nato_allowed_unchanged(self) -> None:
        from bot.no_host_mafia_nato import no_host_nato_allowed

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(20, "N", Role.NATO))
        self.assertTrue(no_host_nato_allowed(game))

    def test_mozakere_mafia_menu_unchanged(self) -> None:
        from bot.no_host_mafia_night1 import build_mozakere_mafia_operation_menu_html

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertIn("مذاکره", build_mozakere_mafia_operation_menu_html(game))


if __name__ == "__main__":
    unittest.main()
