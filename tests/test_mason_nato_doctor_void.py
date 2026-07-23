"""Mason NATO voids doctor night action — regression tests."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_ready import (
    _doctor_ready,
    all_mason_parallel_night_ready,
    explain_mason_night_stuck,
)
from bot.mason_night_role import MSD_OK, apply_mason_doctor_nato_void_panel, dispatch_mason_night_role
from bot.models import Player, Role
from bot.no_host_mafia_nato import start_no_host_mafia_nato_flow
from bot.no_host_mafia_night1 import MAFIA_ACTION_NATO
from bot.roles import mason_doctor as ms_doc


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, night: int = 2) -> object:
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=18,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = night
    game.no_host_night_parallel_collect_active = True
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 900
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NATO
    return game


def _arm_other_roles(game) -> None:
    game.mason_night_saboteur_confirmed = True
    game.mason_night_sniper_confirmed = True
    game.mason_night_commander_confirmed = True
    game.mason_night_gunner_confirmed = True
    game.mason_night_guardian_confirmed = True
    game.mason_night_mason_confirmed = True
    game.mason_night_detective_confirmed = True
    game.mason_night_natasha_confirmed = True
    game.mason_night_priest_confirmed = True
    game.mason_night_wait_ok_uids = []


class MasonDoctorNatoVoidStateTests(unittest.TestCase):
    def test_void_before_doctor_selection_clears_and_confirms(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        ms_doc.snapshot_mason_doctor_night_baseline(game)
        ms_doc.void_mason_doctor_night_after_nato(game)
        self.assertEqual(game.mason_doctor_night_save_uids, [])
        self.assertFalse(game.mason_night_pending_doctor_self_save)
        self.assertFalse(game.mason_night_doctor_confirmed)
        self.assertTrue(game.mason_night_doctor_nato_void_pending)
        self.assertFalse(_doctor_ready(game))

    def test_void_after_doctor_selection_clears_saves(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        doc = _p(10, "Doc", Role.DOCTOR)
        other = _p(20, "Other", Role.TOWN_SIMPLE)
        gm.add_player(game, doc)
        gm.add_player(game, other)
        ms_doc.snapshot_mason_doctor_night_baseline(game)
        self.assertTrue(ms_doc.commit_mason_doctor_save(game, other.user_id))
        ms_doc.void_mason_doctor_night_after_nato(game)
        self.assertEqual(game.mason_doctor_night_save_uids, [])
        self.assertFalse(game.mason_night_doctor_confirmed)
        self.assertTrue(game.mason_night_doctor_nato_void_pending)

    def test_void_after_self_save_rolls_back_counter(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        doc = _p(10, "Doc", Role.DOCTOR)
        gm.add_player(game, doc)
        game.mason_doctor_self_save_count = 1
        ms_doc.snapshot_mason_doctor_night_baseline(game)
        self.assertTrue(ms_doc.commit_mason_doctor_save(game, doc.user_id))
        self.assertTrue(game.mason_night_pending_doctor_self_save)
        ms_doc.void_mason_doctor_night_after_nato(game)
        self.assertEqual(game.mason_doctor_self_save_count, 1)
        self.assertFalse(game.mason_night_pending_doctor_self_save)

    def test_void_rolls_back_incremented_self_save_same_night(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        doc = _p(10, "Doc", Role.DOCTOR)
        gm.add_player(game, doc)
        game.mason_doctor_self_save_count = 2
        game.mason_night_baseline_doctor_self_saves = 1
        game.mason_night_pending_doctor_self_save = True
        game.mason_doctor_night_save_uids = [doc.user_id]
        ms_doc.void_mason_doctor_night_after_nato(game)
        self.assertEqual(game.mason_doctor_self_save_count, 1)


class MasonDoctorNatoVoidFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_nato_start_voids_doctor_before_selection(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(5, "Nato", Role.NATO))
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(20, "Town", Role.TOWN_SIMPLE))
        bot = MagicMock()
        with patch(
            "bot.no_host_mafia_nato.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_mafia_nato.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.apply_mason_doctor_nato_void_panel",
            new=AsyncMock(),
        ) as void_panel:
            await start_no_host_mafia_nato_flow(bot, game, gm)
        void_panel.assert_awaited_once()

    async def test_apply_void_panel_sends_nato_message(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        bot = MagicMock()
        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as register:
            await apply_mason_doctor_nato_void_panel(bot, game, gm)
        register.assert_awaited_once()
        args = register.await_args
        self.assertIn(ms_doc.MASON_DOCTOR_NATO_VOID_TEXT, args.args[4])

    async def test_night_waits_for_doctor_ok_after_nato_void(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        _arm_other_roles(game)
        game.no_host_mafia_nato_done = True
        ms_doc.void_mason_doctor_night_after_nato(game)
        self.assertFalse(all_mason_parallel_night_ready(game))

    async def test_doctor_ok_after_nato_acknowledges_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        _arm_other_roles(game)
        game.no_host_mafia_nato_done = True
        ms_doc.void_mason_doctor_night_after_nato(game)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=10, actor_uid=10, act=MSD_OK, tid=0
            )
        cb.answer.assert_awaited()


class MasonDoctorNatoDiagnosticTests(unittest.TestCase):
    def test_explain_stuck_shows_doctor_when_unconfirmed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Doctor", report)
        self.assertIn("mason_night_doctor_confirmed = False", report)

    def test_explain_stuck_lists_doctor_after_nato_void_until_ok(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        _arm_other_roles(game)
        game.no_host_mafia_nato_done = True
        ms_doc.void_mason_doctor_night_after_nato(game)
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Doctor", report)
        self.assertIn("mason_night_doctor_confirmed = False", report)


if __name__ == "__main__":
    unittest.main()
