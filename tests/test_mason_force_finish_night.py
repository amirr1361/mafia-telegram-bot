"""اتمام اجباری شب ماسون — کمک‌کننده."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_force_finish_night import (
    MASON_FORCE_FINISH_CANCELLED_TEXT,
    MASON_FORCE_FINISH_CONFIRM_TEXT,
    MASON_FORCE_FINISH_NOT_NIGHT_TEXT,
    MASON_FORCE_FINISH_NIGHT_COMMAND,
    MASON_NIGHT_PHASE_ENDED_TEXT,
    find_mason_bot_assistant_game,
    force_finish_mason_night,
    handle_mason_force_finish_callback,
    handle_mason_force_finish_text,
    mason_night_force_finish_collection_active,
    normalize_pending_mason_night_actions,
    pending_mason_force_finish_labels,
    reject_mason_night_callback_if_closed,
)
from bot.mason_helper_flow import MasonHelperCb, handle_mason_helper_action
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.mason_night_role import (
    MSS_NONE,
    dispatch_mason_night_role,
)
from bot.models import Player, Role
from bot.roles import mason_sniper as ms_sn
from bot.roles.night_state import mafia_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _active_mason_night_game(gm: GameManager, *, assistant_uid: int = 900):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "FF1"
    game.bot_assistant_user_id = assistant_uid
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    game.mason_night_entry_dispatched_night = 1
    gm.add_player(
        game,
        _p(assistant_uid, "Helper", Role.TOWN_SIMPLE, seat=1),
    )
    return game


def _arm_mafia_done(game) -> None:
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True


class MasonForceFinishAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_helper_gets_confirmation_during_night_collect(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        msg = MagicMock()
        msg.answer = AsyncMock()
        await handle_mason_force_finish_text(msg, MagicMock(), 900, gm)
        msg.answer.assert_awaited_once()
        args = msg.answer.await_args
        self.assertEqual(args.args[0], MASON_FORCE_FINISH_CONFIRM_TEXT)
        self.assertIsNotNone(args.kwargs.get("reply_markup"))

    async def test_outside_night_collect_gets_not_night_message(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        game.no_host_night_parallel_collect_active = False
        msg = MagicMock()
        msg.answer = AsyncMock()
        await handle_mason_force_finish_text(msg, MagicMock(), 900, gm)
        msg.answer.assert_awaited_once_with(MASON_FORCE_FINISH_NOT_NIGHT_TEXT)

    async def test_unauthorized_player_ignored(self) -> None:
        gm = GameManager()
        _active_mason_night_game(gm)
        self.assertIsNone(find_mason_bot_assistant_game(42, gm))
        msg = MagicMock()
        msg.answer = AsyncMock()
        await handle_mason_force_finish_text(msg, MagicMock(), 42, gm)
        msg.answer.assert_not_awaited()

    async def test_press_no_cancels_without_state_change(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        game.mason_night_doctor_confirmed = False
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        await handle_mason_force_finish_callback(
            cb, MagicMock(), game, gm, assistant_uid=900, act="no"
        )
        self.assertFalse(game.mason_night_force_finished)
        self.assertFalse(game.mason_night_doctor_confirmed)
        cb.message.edit_text.assert_awaited_once_with(MASON_FORCE_FINISH_CANCELLED_TEXT)


class MasonForceFinishNormalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _active_mason_night_game(self.gm)
        _arm_mafia_done(self.game)

    def test_doctor_no_choice(self) -> None:
        self.gm.add_player(self.game, _p(10, "Doc", Role.DOCTOR))
        normalize_pending_mason_night_actions(self.game, self.gm)
        self.assertTrue(self.game.mason_night_doctor_confirmed)
        self.assertEqual(self.game.mason_doctor_night_save_uids, [])

    def test_sniper_no_choice_no_bullets(self) -> None:
        self.gm.add_player(self.game, _p(20, "Sn", Role.SNIPER))
        spent = self.game.mason_sniper_bullets_spent
        normalize_pending_mason_night_actions(self.game, self.gm)
        self.assertTrue(self.game.mason_night_sniper_confirmed)
        self.assertEqual(self.game.mason_sniper_night_selected_uids, [])
        self.assertEqual(self.game.mason_sniper_bullets_spent, spent)

    def test_commander_rejects_pending_shots(self) -> None:
        self.gm.add_player(self.game, _p(20, "Sn", Role.SNIPER))
        self.gm.add_player(self.game, _p(21, "Cmd", Role.COMMANDER))
        self.gm.add_player(self.game, _p(30, "T", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(self.game, [30])
        self.game.mason_night_sniper_confirmed = True
        spent = self.game.mason_sniper_bullets_spent
        normalize_pending_mason_night_actions(self.game, self.gm)
        self.assertTrue(self.game.mason_night_commander_confirmed)
        self.assertEqual(self.game.mason_commander_night_approved_uids, [])
        self.assertEqual(self.game.mason_sniper_bullets_spent, spent)

    def test_mason_no_recruit(self) -> None:
        self.gm.add_player(self.game, _p(40, "M", Role.MASON))
        normalize_pending_mason_night_actions(self.game, self.gm)
        self.assertTrue(self.game.mason_night_mason_confirmed)
        self.assertTrue(self.game.mason_mason_night_no_recruit)

    def test_natasha_priest_guardian_detective_saboteur_no_choice(self) -> None:
        self.gm.add_player(self.game, _p(50, "Nat", Role.NATASHA))
        self.gm.add_player(self.game, _p(51, "Pr", Role.PRIEST))
        self.gm.add_player(self.game, _p(52, "Gd", Role.BODYGUARD))
        self.gm.add_player(self.game, _p(53, "Det", Role.DETECTIVE))
        self.gm.add_player(self.game, _p(54, "Sab", Role.SABOTEUR))
        normalize_pending_mason_night_actions(self.game, self.gm)
        self.assertTrue(self.game.mason_night_natasha_confirmed)
        self.assertTrue(self.game.mason_night_priest_confirmed)
        self.assertTrue(self.game.mason_night_guardian_confirmed)
        self.assertTrue(self.game.mason_night_detective_confirmed)
        self.assertTrue(self.game.mason_night_saboteur_confirmed)

    def test_mafia_no_shot(self) -> None:
        self.game.no_host_mafia_night1_done = False
        self.game.no_host_mafia_shot_done = False
        normalize_pending_mason_night_actions(self.game, self.gm)
        self.assertTrue(self.game.no_host_mafia_night1_done)
        self.assertTrue(self.game.no_host_mafia_shot_done)
        self.assertFalse(mafia_night_state(self.game).shot_registered)

    def test_pending_labels_include_doctor(self) -> None:
        self.gm.add_player(self.game, _p(10, "Doc", Role.DOCTOR))
        labels = pending_mason_force_finish_labels(self.game, self.gm)
        self.assertIn("Doctor", labels)


class MasonForceFinishFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_yes_runs_normal_night_resolution(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        _arm_mafia_done(game)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        bot = MagicMock()
        finish = AsyncMock()
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        with patch(
            "bot.mason_force_finish_night.lock_mason_night_mirror_panels",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_ready.finish_no_host_parallel_night_collect",
            finish,
        ):
            await force_finish_mason_night(bot, game, gm)
        self.assertTrue(game.mason_night_force_finished)
        self.assertTrue(all_mason_parallel_night_ready(game))
        finish.assert_awaited_once()

    async def test_helper_callback_yes_via_msh_router(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        _arm_mafia_done(game)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.mason_force_finish_night.lock_mason_night_mirror_panels",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_ready.finish_no_host_parallel_night_collect",
            new=AsyncMock(),
        ):
            await handle_mason_helper_action(
                cb,
                bot,
                game,
                gm,
                assistant_uid=900,
                actor_uid=900,
                act="yes",
                kind="force_night",
            )
        self.assertTrue(game.mason_night_force_finished)
        self.assertTrue(game.mason_night_doctor_confirmed)

    async def test_late_callback_after_force_finish_rejected(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        game.mason_night_force_finished = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        self.assertTrue(await reject_mason_night_callback_if_closed(cb, game))
        cb.answer.assert_awaited_once_with(
            MASON_NIGHT_PHASE_ENDED_TEXT, show_alert=True
        )

    async def test_late_role_panel_callback_rejected(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        gm.add_player(game, _p(20, "Sn", Role.SNIPER))
        game.mason_night_force_finished = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        await dispatch_mason_night_role(
            cb,
            bot,
            game,
            gm,
            as_uid=20,
            actor_uid=20,
            act=MSS_NONE,
            tid=0,
        )
        cb.answer.assert_awaited_once_with(
            MASON_NIGHT_PHASE_ENDED_TEXT, show_alert=True
        )


class MasonForceFinishIsolationTests(unittest.TestCase):
    def test_command_text_constant(self) -> None:
        self.assertEqual(MASON_FORCE_FINISH_NIGHT_COMMAND, "اتمام شب")

    def test_collection_active_requires_entry_dispatched(self) -> None:
        gm = GameManager()
        game = _active_mason_night_game(gm)
        self.assertTrue(mason_night_force_finish_collection_active(game))
        game.mason_night_entry_dispatched_night = None
        self.assertFalse(mason_night_force_finish_collection_active(game))

    def test_bazpors_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(mason_night_force_finish_collection_active(game))

    def test_mozakere_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertFalse(mason_night_force_finish_collection_active(game))

    def test_force_night_callback_pack(self) -> None:
        packed = MasonHelperCb(code="FF1", act="yes", kind="force_night").pack()
        self.assertTrue(packed.startswith("msh:"))


if __name__ == "__main__":
    unittest.main()
