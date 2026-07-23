"""Room 08 — Night 4 stuck on Sniper/Commander with 0 bullets (Mason only).

Documents the exact readiness blocker before the fix and proves it is gone after.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_ready import (
    _commander_ready,
    _commander_ready_reason,
    _sniper_ready,
    _sniper_ready_reason,
    all_mason_parallel_night_ready,
    build_mason_night_readiness_report,
    format_mason_night_readiness_report,
    maybe_finish_mason_parallel_night,
)
from bot.mason_night_role import dispatch_mason_sniper_panel
from bot.models import Player, Role
from bot.roles import mason_sniper as ms_sn


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
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
    game.bazpors_narrator_night_count = 4
    game.no_host_night_parallel_collect_active = True
    return game


def _arm_all_except_sniper_commander(game) -> None:
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    game.mason_night_saboteur_confirmed = True
    game.mason_night_doctor_confirmed = True
    game.mason_night_gunner_confirmed = True
    game.mason_night_guardian_confirmed = True
    game.mason_night_mason_confirmed = True
    game.mason_night_detective_confirmed = True
    game.mason_night_natasha_confirmed = True
    game.mason_night_priest_confirmed = True


def _sniper_ready_before_fix(game) -> bool:
    """Readiness gate as implemented before the Room 08 fix."""
    from bot.roles.registry import find_alive_role_holder

    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None:
        return game.mason_night_sniper_confirmed
    if not ms_sn.mason_sniper_needs_night_pick(game):
        return sn.user_id in game.mason_night_wait_ok_uids
    return game.mason_night_sniper_confirmed


def _commander_ready_before_fix(game) -> bool:
    """Readiness gate as implemented before the Room 08 fix."""
    from bot.roles.registry import find_alive_role_holder

    cmd = find_alive_role_holder(game, Role.COMMANDER)
    sn = find_alive_role_holder(game, Role.SNIPER)
    if cmd is None:
        return True
    if sn is None:
        return game.mason_night_commander_confirmed
    if not _sniper_ready_before_fix(game):
        return False
    return game.mason_night_commander_confirmed


def _sniper_ready_reason_before_fix(game) -> str | None:
    from bot.roles.registry import find_alive_role_holder

    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None:
        return None
    if not ms_sn.mason_sniper_needs_night_pick(game):
        if sn.user_id in game.mason_night_wait_ok_uids:
            return None
        return "تأیید اسنایپر (اوکی) ثبت نشده"
    if not game.mason_night_sniper_confirmed:
        return "اقدام اسنایپر تمام نشده"
    return None


def _commander_ready_reason_before_fix(game) -> str | None:
    from bot.roles.registry import find_alive_role_holder

    cmd = find_alive_role_holder(game, Role.COMMANDER)
    sn = find_alive_role_holder(game, Role.SNIPER)
    if cmd is None:
        return None
    sniper_reason = _sniper_ready_reason_before_fix(game)
    if sn is not None and sniper_reason:
        return sniper_reason
    if not game.mason_night_commander_confirmed:
        if game.mason_night_commander_panel_sent:
            return "پنل فرمانده باز است"
        return "پنل فرمانده ارسال نشده"
    return None


class Room08Night4StuckBlockerTests(unittest.TestCase):
    """Pinpoints which role blocked Night 4 readiness before the fix."""

    def test_primary_blocker_commander_inheriting_zero_bullets_sniper_dead(self) -> None:
        """Room 08 Night 4: Sniper gone, Commander got a shot panel with 0 bullets left."""
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except_sniper_commander(game)
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_panel_sent = True
        game.mason_night_commander_confirmed = False

        self.assertFalse(_commander_ready_before_fix(game))
        self.assertTrue(_sniper_ready_before_fix(game))
        self.assertEqual(
            _commander_ready_reason_before_fix(game),
            "پنل فرمانده باز است",
        )
        self.assertFalse(_commander_ready(game))

    def test_secondary_blocker_sniper_alive_zero_bullets_not_confirmed(self) -> None:
        """If Sniper was still alive on Night 4, readiness also waited on Sniper."""
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except_sniper_commander(game)
        game.mason_night_sniper_confirmed = False
        game.mason_night_commander_confirmed = False
        game.mason_night_wait_ok_uids = []

        self.assertFalse(_sniper_ready_before_fix(game))
        self.assertFalse(_commander_ready_before_fix(game))
        self.assertEqual(
            _sniper_ready_reason_before_fix(game),
            "تأیید اسنایپر (اوکی) ثبت نشده",
        )
        self.assertFalse(all_mason_parallel_night_ready(game))
        self.assertFalse(_sniper_ready(game))

    def test_commander_inherit_zero_bullets_waits_for_ok(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except_sniper_commander(game)
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_panel_sent = True
        game.mason_night_commander_confirmed = False

        self.assertFalse(_commander_ready(game))
        self.assertEqual(
            _commander_ready_reason(game),
            "تأیید فرمانده (اوکی) ثبت نشده",
        )
        self.assertFalse(all_mason_parallel_night_ready(game))

    def test_sniper_alive_zero_bullets_waits_for_ok(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except_sniper_commander(game)
        game.mason_night_sniper_confirmed = False
        game.mason_night_commander_confirmed = True
        game.mason_night_wait_ok_uids = []

        self.assertFalse(_sniper_ready(game))
        self.assertEqual(
            _sniper_ready_reason(game),
            "تأیید اسنایپر (اوکی) ثبت نشده",
        )
        self.assertFalse(_commander_ready(game))


class Room08Night4StuckDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_commander_inherit_zero_bullets_reaches_night_resolution(
        self,
    ) -> None:
        """End-to-end: Night 4 dispatch no longer leaves Commander as the waiter."""
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except_sniper_commander(game)
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role._show_mason_commander_panel",
            new=AsyncMock(),
        ) as show_cmd, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)
            await maybe_finish_mason_parallel_night(bot, game, gm)

        show_cmd.assert_not_awaited()
        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertFalse(all_mason_parallel_night_ready(game))
        finish.assert_not_awaited()

    async def test_dispatch_sniper_alive_zero_bullets_waits_for_ok(
        self,
    ) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_all_except_sniper_commander(game)
        game.mason_night_commander_confirmed = True
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role._show_mason_sniper_panel",
            new=AsyncMock(),
        ) as show_sn, patch(
            "bot.mason_night_role._send_commander_sniper_no_shot_info_panel",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)
            await maybe_finish_mason_parallel_night(bot, game, gm)

        show_sn.assert_not_awaited()
        self.assertFalse(game.mason_night_sniper_confirmed)
        self.assertFalse(all_mason_parallel_night_ready(game))
        finish.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
