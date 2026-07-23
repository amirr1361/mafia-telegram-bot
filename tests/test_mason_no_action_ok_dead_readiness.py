"""Mason — single-use no-action OK panels and dead-player readiness."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_ready import (
    _doctor_ready,
    _guardian_ready,
    _sniper_ready,
    all_mason_parallel_night_ready,
    explain_mason_night_stuck,
)
from bot.mason_night_role import (
    MASON_DEAD_PANEL_INACTIVE_TEXT,
    MASON_GUARDIAN_APACHE_GONE_TEXT,
    MASON_NO_NIGHT_PICK_WAIT_TEXT,
    MASON_NO_PICK_ALREADY_ACK_TEXT,
    MASON_OK_CONFIRMED_PANEL_TEXT,
    MSB_OK,
    MSD_OK,
    MGD_OK,
    MSC_INFO_OK,
    MSS_OK,
    dispatch_mason_commander_panel,
    dispatch_mason_night_role,
    dispatch_mason_sniper_panel,
)
from bot.models import Player, Role
from bot.roles import mason_doctor as ms_doc


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _mason_game(gm: GameManager, *, n: int = 16):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.no_host_night_parallel_collect_active = True
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    return game


def _arm_all_except(*, game, skip: Role) -> None:
    flags = {
        Role.SABOTEUR: "mason_night_saboteur_confirmed",
        Role.DOCTOR: "mason_night_doctor_confirmed",
        Role.SNIPER: "mason_night_sniper_confirmed",
        Role.COMMANDER: "mason_night_commander_confirmed",
        Role.GUNMAN: "mason_night_gunner_confirmed",
        Role.BODYGUARD: "mason_night_guardian_confirmed",
        Role.MASON: "mason_night_mason_confirmed",
        Role.DETECTIVE: "mason_night_detective_confirmed",
        Role.NATASHA: "mason_night_natasha_confirmed",
        Role.PRIEST: "mason_night_priest_confirmed",
    }
    for role, attr in flags.items():
        if role != skip:
            setattr(game, attr, True)


class MasonNoActionOkSingleUseTests(unittest.IsolatedAsyncioTestCase):
    async def _click_sniper_ok(self, game, gm, *, as_uid: int, actor_uid: int) -> MagicMock:
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        await dispatch_mason_night_role(
            cb, bot, game, gm, as_uid=as_uid, actor_uid=actor_uid, act=MSS_OK, tid=0
        )
        return cb

    async def test_sniper_ok_marks_ready_and_removes_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        updates: list[object | None] = []

        async def _capture(_b, _g, _ui, _text, kb, **kw):
            updates.append(kb)

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            side_effect=_capture,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            cb = await self._click_sniper_ok(game, gm, as_uid=50, actor_uid=50)

        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertIsNone(updates[-1])
        cb.answer.assert_awaited_with("ثبت شد.")

    async def test_sniper_double_ok_does_not_process_twice(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            finish,
        ):
            await self._click_sniper_ok(game, gm, as_uid=50, actor_uid=50)
            cb2 = await self._click_sniper_ok(game, gm, as_uid=50, actor_uid=50)

        finish.assert_awaited_once()
        cb2.answer.assert_awaited_with(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)

    async def test_commander_no_pick_ok_marks_ready(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_panel_sent = True
        updates: list[object | None] = []
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        async def _capture(_b, _g, _ui, text, kb, **kw):
            updates.append((text, kb))

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            side_effect=_capture,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=51, actor_uid=51, act=MSC_INFO_OK, tid=0
            )

        self.assertTrue(game.mason_night_commander_confirmed)
        self.assertIn(MASON_OK_CONFIRMED_PANEL_TEXT, updates[-1][0])
        self.assertIsNone(updates[-1][1])

    async def test_observer_ok_disables_mirror(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920050
        gm.add_player(game, _p(syn, "SynSn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        captured_kb: list[object | None] = []

        async def _capture(_b, _g, _ui, _text, kb, **kw):
            captured_kb.append(kb)

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            side_effect=_capture,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await self._click_sniper_ok(game, gm, as_uid=syn, actor_uid=999)

        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertIsNone(captured_kb[-1])

    async def test_night_readiness_after_sniper_ok_without_prior_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except(game=game, skip=Role.SNIPER)
        game.mason_night_commander_confirmed = True
        self.assertFalse(all_mason_parallel_night_ready(game))

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.dispatch_mason_commander_panel",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await self._click_sniper_ok(game, gm, as_uid=50, actor_uid=50)

        self.assertTrue(all_mason_parallel_night_ready(game))


class MasonDeadRoleReadinessTests(unittest.TestCase):
    def test_dead_sniper_does_not_block(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        game.mason_night_sniper_confirmed = False
        self.assertTrue(_sniper_ready(game))

    def test_dead_doctor_does_not_block(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR, alive=False))
        game.mason_night_doctor_confirmed = False
        self.assertTrue(_doctor_ready(game))

    def test_all_dead_night_roles_do_not_block(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        roles = (
            (Role.DOCTOR, 10),
            (Role.SNIPER, 11),
            (Role.COMMANDER, 12),
            (Role.BODYGUARD, 13),
            (Role.MASON, 14),
            (Role.NATASHA, 15),
            (Role.PRIEST, 16),
            (Role.DETECTIVE, 17),
            (Role.GUNMAN, 18),
            (Role.SABOTEUR, 19),
            (Role.GODFATHER, 20),
        )
        for role, uid in roles:
            gm.add_player(game, _p(uid, role.value, role, alive=False))
        _arm_all_except(game=game, skip=Role.DOCTOR)
        for attr in (
            "mason_night_doctor_confirmed",
            "mason_night_sniper_confirmed",
            "mason_night_commander_confirmed",
            "mason_night_guardian_confirmed",
            "mason_night_mason_confirmed",
            "mason_night_natasha_confirmed",
            "mason_night_priest_confirmed",
            "mason_night_detective_confirmed",
            "mason_night_gunner_confirmed",
            "mason_night_saboteur_confirmed",
        ):
            setattr(game, attr, False)
        self.assertTrue(all_mason_parallel_night_ready(game))


class MasonDeadPanelCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_dead_player_old_panel_is_inactive(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        before = game.mason_night_sniper_confirmed
        await dispatch_mason_night_role(
            cb, bot, game, gm, as_uid=50, actor_uid=50, act=MSS_OK, tid=0
        )
        self.assertEqual(game.mason_night_sniper_confirmed, before)
        cb.answer.assert_awaited_with(MASON_DEAD_PANEL_INACTIVE_TEXT, show_alert=True)


class MasonExplainStuckDiagnosticsTests(unittest.TestCase):
    def test_dead_roles_listed_as_skipped_not_blockers(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR, alive=False))
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        game.mason_night_doctor_confirmed = False
        game.mason_night_sniper_confirmed = False
        _arm_all_except(game=game, skip=Role.DOCTOR)
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("No blocker: Doctor is dead, skipped.", report)
        self.assertIn("No blocker: Sniper is dead, skipped.", report)
        self.assertNotIn("Waiting for:\n- Doctor", report)

    def test_alive_incomplete_role_still_listed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        game.mason_night_doctor_confirmed = False
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Waiting for:", report)
        self.assertIn("Doctor", report)
        self.assertIn("mason_night_doctor_confirmed = False", report)


class MasonNoActionDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_sniper_no_action_does_not_auto_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        bot = MagicMock()
        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.dispatch_mason_commander_panel",
            new=AsyncMock(),
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)
        self.assertFalse(game.mason_night_sniper_confirmed)

    async def test_dispatch_commander_no_pick_does_not_auto_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        game.mason_night_sniper_confirmed = True
        bot = MagicMock()
        captured: list[str] = []

        async def _cap(_b, _g, _uid, _ui, text, _kb, **kw):
            captured.append(text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_cap,
        ):
            await dispatch_mason_commander_panel(bot, game, gm)

        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertTrue(any(MASON_NO_NIGHT_PICK_WAIT_TEXT in t for t in captured))


class MasonGuardianOkSingleUseTests(unittest.IsolatedAsyncioTestCase):
    async def _click_guardian_ok(self, game, gm, *, as_uid: int, actor_uid: int) -> MagicMock:
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        await dispatch_mason_night_role(
            cb, bot, game, gm, as_uid=as_uid, actor_uid=actor_uid, act=MGD_OK, tid=0
        )
        return cb

    async def test_guardian_ok_marks_ready_and_removes_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE, alive=False))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        updates: list[tuple[str, object | None]] = []

        async def _capture(_b, _g, _ui, text, kb, **kw):
            updates.append((text, kb))

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            side_effect=_capture,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            cb = await self._click_guardian_ok(game, gm, as_uid=30, actor_uid=30)

        self.assertTrue(game.mason_night_guardian_confirmed)
        self.assertIn(MASON_GUARDIAN_APACHE_GONE_TEXT, updates[-1][0])
        self.assertIn(MASON_OK_CONFIRMED_PANEL_TEXT, updates[-1][0])
        self.assertIsNone(updates[-1][1])
        cb.answer.assert_awaited_with("ثبت شد.")

    async def test_guardian_double_ok_is_safe(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE, alive=False))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            finish,
        ):
            await self._click_guardian_ok(game, gm, as_uid=30, actor_uid=30)
            cb2 = await self._click_guardian_ok(game, gm, as_uid=30, actor_uid=30)

        finish.assert_awaited_once()
        cb2.answer.assert_awaited_with(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)

    def test_dead_guardian_does_not_block(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD, alive=False))
        game.mason_night_guardian_confirmed = False
        self.assertTrue(_guardian_ready(game))


class MasonSaboteurOkSingleUseTests(unittest.IsolatedAsyncioTestCase):
    async def test_saboteur_no_pick_ok_single_use(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(2, "Sb", Role.SABOTEUR))
        game.mason_gun_spent = True
        finish = AsyncMock()
        updates: list[object | None] = []
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        async def _capture(_b, _g, _ui, _text, kb, **kw):
            updates.append(kb)

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            side_effect=_capture,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            finish,
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=2, actor_uid=2, act=MSB_OK, tid=0
            )
            cb2 = MagicMock()
            cb2.answer = AsyncMock()
            await dispatch_mason_night_role(
                cb2, bot, game, gm, as_uid=2, actor_uid=2, act=MSB_OK, tid=0
            )

        self.assertTrue(game.mason_night_saboteur_confirmed)
        self.assertIsNone(updates[-1])
        finish.assert_awaited_once()
        cb2.answer.assert_awaited_with(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)


class MasonDoctorNatoOkSingleUseTests(unittest.IsolatedAsyncioTestCase):
    async def test_doctor_nato_ok_single_use_and_readiness(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        _arm_all_except(game=game, skip=Role.DOCTOR)
        game.no_host_mafia_nato_done = True
        ms_doc.void_mason_doctor_night_after_nato(game)
        self.assertFalse(_doctor_ready(game))
        finish = AsyncMock()
        updates: list[tuple[str, object | None]] = []
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        async def _capture(_b, _g, _ui, text, kb, **kw):
            updates.append((text, kb))

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            side_effect=_capture,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            finish,
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=10, actor_uid=10, act=MSD_OK, tid=0
            )
            cb2 = MagicMock()
            cb2.answer = AsyncMock()
            await dispatch_mason_night_role(
                cb2, bot, game, gm, as_uid=10, actor_uid=10, act=MSD_OK, tid=0
            )

        self.assertTrue(game.mason_night_doctor_confirmed)
        self.assertFalse(game.mason_night_doctor_nato_void_pending)
        self.assertIn(ms_doc.MASON_DOCTOR_NATO_VOID_TEXT, updates[-1][0])
        self.assertIn(MASON_OK_CONFIRMED_PANEL_TEXT, updates[-1][0])
        self.assertIsNone(updates[-1][1])
        finish.assert_awaited_once()
        cb2.answer.assert_awaited_with(MASON_NO_PICK_ALREADY_ACK_TEXT, show_alert=True)
        self.assertTrue(_doctor_ready(game))


class MasonOkUnchangedOtherScenariosTests(unittest.TestCase):
    def test_mason_ok_helpers_not_in_no_host_night_ready(self) -> None:
        import bot.no_host_night_ready as nhr

        self.assertFalse(hasattr(nhr, "process_mason_no_pick_ok_ack"))
        self.assertFalse(hasattr(nhr, "MASON_OK_CONFIRMED_PANEL_TEXT"))

    def test_mozakere_sniper_ready_still_uses_mozakere_shot_budget(self) -> None:
        from bot.no_host_night_ready import _sniper_ready as shared_sniper_ready
        from bot.roles.mozakere_sniper import can_mozakere_sniper_shoot

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(30, "Sn", Role.SNIPER))
        game.mozakere_sniper_shots_used = 2
        self.assertFalse(can_mozakere_sniper_shoot(game))
        self.assertTrue(shared_sniper_ready(game))


if __name__ == "__main__":
    unittest.main()
