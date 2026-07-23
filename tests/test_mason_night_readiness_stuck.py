"""Regression: Mason night readiness must not stick after sniper/commander chain."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_role import (
    MASON_NO_NIGHT_PICK_WAIT_TEXT,
    MSS_NONE,
    MSC_INFO_OK,
    dispatch_mason_night_role,
    dispatch_mason_sniper_panel,
)
from bot.mason_night_ready import (
    all_mason_parallel_night_ready,
    build_mason_night_readiness_report,
    format_mason_night_readiness_report,
)
from bot.mason_roles import masoon_roles_for_count
from bot.models import Player, Role


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int | None = None) -> Player:
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
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    return game


def _populate_room46(game, gm: GameManager) -> None:
    for seat, role in enumerate(masoon_roles_for_count(16), start=1):
        gm.add_player(game, _p(100 + seat, f"P{seat}", role, seat=seat))


def _arm_night1_except_commander_chain(game) -> None:
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
    holders = {
        Role.GODFATHER,
        Role.SABOTEUR,
        Role.DOCTOR,
        Role.SNIPER,
        Role.COMMANDER,
        Role.GUNMAN,
        Role.BODYGUARD,
        Role.MASON,
        Role.DETECTIVE,
    }
    game.mason_night_wait_ok_uids = [
        p.user_id
        for p in game.players.values()
        if p.is_alive and p.role not in holders
    ]


class MasonSniperCommanderChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_sniper_no_shot_auto_confirms_commander_and_finishes(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        _arm_night1_except_commander_chain(game)
        game.mason_night_wait_ok_uids = []

        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            finish,
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=50,
                actor_uid=50,
                act=MSS_NONE,
                tid=0,
            )
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=51,
                actor_uid=51,
                act=MSC_INFO_OK,
                tid=0,
            )

        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertTrue(game.mason_night_commander_confirmed)
        self.assertGreaterEqual(finish.await_count, 2)
        self.assertTrue(all_mason_parallel_night_ready(game))

    async def test_dead_sniper_at_dispatch_chains_commander(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER, alive=False))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        bot = MagicMock()

        with patch(
            "bot.mason_night_role._show_mason_commander_panel",
            new=AsyncMock(),
        ) as show_cmd, patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)

        self.assertTrue(game.mason_night_sniper_confirmed)
        show_cmd.assert_awaited_once()
        self.assertFalse(game.mason_night_commander_confirmed)

    async def test_sniper_no_bullets_at_dispatch_sends_wait_and_info_panels(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        bot = MagicMock()

        with patch(
            "bot.mason_night_role._show_mason_sniper_panel",
            new=AsyncMock(),
        ) as show_sn, patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role._send_commander_sniper_no_shot_info_panel",
            new=AsyncMock(),
        ) as info_panel, patch(
            "bot.mason_night_role._show_mason_commander_panel",
            new=AsyncMock(),
        ) as show_cmd, patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)

        self.assertFalse(game.mason_night_sniper_confirmed)
        show_sn.assert_not_awaited()
        show_cmd.assert_not_awaited()
        info_panel.assert_awaited_once()
        self.assertFalse(game.mason_night_commander_confirmed)

    async def test_night4_style_readiness_when_commander_inherits_zero_bullets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        game.bazpors_narrator_night_count = 4
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_night1_except_commander_chain(game)
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_wait_ok_uids = [51]

        self.assertTrue(all_mason_parallel_night_ready(game))
        _, ready = build_mason_night_readiness_report(game, gm)
        self.assertTrue(ready)


class MasonNightReadinessReportTests(unittest.TestCase):
    def test_room46_report_flags_unconfirmed_commander(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_room46(game, gm)
        _arm_night1_except_commander_chain(game)
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = False
        game.mason_night_commander_panel_sent = False

        _, ready = build_mason_night_readiness_report(game, gm)
        report = format_mason_night_readiness_report(game, gm)

        self.assertFalse(ready)
        self.assertIn("commander: waiting", report)
        self.assertIn("Final readiness = False", report)

    def test_room46_report_complete_when_commander_auto_confirmed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_room46(game, gm)
        _arm_night1_except_commander_chain(game)
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True

        _, ready = build_mason_night_readiness_report(game, gm)
        self.assertTrue(ready)
        self.assertTrue(all_mason_parallel_night_ready(game))


if __name__ == "__main__":
    unittest.main()
