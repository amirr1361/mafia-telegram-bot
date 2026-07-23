"""تست محافظ — سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_mafia_team, is_synthetic_player_uid
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.mason_night_role import (
    MASON_GUARDIAN_APACHE_USED_TEXT,
    MGD_OK,
    dispatch_mason_guardian_panel,
    dispatch_mason_night_role,
)
from bot.models import Player, Role
from bot.roles import mason_apache as ms_ap
from bot.roles import mason_guardian as ms_gd
from bot.roles.registry import get_role_module, is_registered_role


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
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
    return game


class MasonGuardianApacheUsedTests(unittest.TestCase):
    def test_no_pick_when_apache_dead_without_day_action(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE, alive=False))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        self.assertFalse(ms_gd.mason_guardian_needs_night_pick(game))
        self.assertFalse(game.mason_apache_day_action_used)

    def test_needs_pick_when_apache_alive_without_day_action(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        self.assertTrue(ms_gd.mason_guardian_needs_night_pick(game))

    def test_no_pick_after_apache_used_day_action(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE, alive=False))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        game.mason_apache_day_action_used = True
        self.assertFalse(ms_gd.mason_guardian_needs_night_pick(game))

    def test_mark_flag_only_on_apache_confirm_helper(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        self.assertFalse(game.mason_apache_day_action_used)
        ms_ap.mark_mason_apache_day_action_used(game)
        self.assertTrue(game.mason_apache_day_action_used)


class MasonGuardianNightDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_apache_used_action_sends_ok_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE, alive=False))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        game.mason_apache_day_action_used = True
        bot = MagicMock()
        captured: list[tuple[str, str | None]] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            captured.append((text, kb.inline_keyboard[0][0].text if kb else None))

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_guardian_panel(bot, game, gm)

        self.assertEqual(len(captured), 1)
        text, btn = captured[0]
        self.assertIn(MASON_GUARDIAN_APACHE_USED_TEXT, text)
        self.assertIn("اوکی", btn or "")
        self.assertFalse(game.mason_night_guardian_confirmed)

    async def test_apache_dead_without_action_sends_ok_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE, alive=False))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        bot = MagicMock()
        captured: list[tuple[str, str | None]] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            captured.append((text, kb.inline_keyboard[0][0].text if kb else None))

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_guardian_panel(bot, game, gm)

        self.assertEqual(len(captured), 1)
        text, btn = captured[0]
        from bot.mason_night_role import MASON_GUARDIAN_APACHE_GONE_TEXT

        self.assertIn(MASON_GUARDIAN_APACHE_GONE_TEXT, text)
        self.assertIn("اوکی", btn or "")
        self.assertFalse(game.mason_night_guardian_confirmed)

    async def test_apache_alive_sends_pick_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as reg:
            await dispatch_mason_guardian_panel(bot, game, gm)
        reg.assert_awaited_once()
        args = reg.await_args
        self.assertIn("محافظت در برابر آپاچی", args.args[4])

    async def test_observer_ok_for_guardian_no_pick(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920030
        gm.add_player(game, _p(syn, "SynGd", Role.BODYGUARD))
        game.mason_apache_day_action_used = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        self.assertTrue(is_synthetic_player_uid(syn))
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
                cb,
                bot,
                game,
                gm,
                as_uid=syn,
                actor_uid=999,
                act=MGD_OK,
                tid=0,
            )
        self.assertTrue(game.mason_night_guardian_confirmed)

    def test_readiness_blocked_until_guardian_ok(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        game.mason_apache_day_action_used = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 900
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        game.mason_night_saboteur_confirmed = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = False
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        game.mason_night_wait_ok_uids = []
        self.assertFalse(all_mason_parallel_night_ready(game))


class MasonGuardianNightPickTests(unittest.TestCase):
    def test_cannot_target_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        self.assertFalse(ms_gd.commit_mason_guardian_night_pick(game, 30))

    def test_stores_exactly_one_target(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        self.assertTrue(ms_gd.commit_mason_guardian_night_pick(game, 20))
        self.assertEqual(game.mason_guardian_night_target_uid, 20)
        self.assertTrue(ms_gd.commit_mason_guardian_night_pick(game, 20))


class MasonGuardianProtectionTests(unittest.TestCase):
    def test_guardian_blocks_apache_only_when_active(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_gd.commit_mason_guardian_night_pick(game, 20)
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 20))
        ms_gd.activate_mason_guardian_day_protection(game)
        self.assertEqual(ms_gd.guardian_current_target(game), 20)
        self.assertTrue(ms_gd.guardian_blocks_apache(game, 20))
        ms_gd.clear_mason_guardian_day_protection(game)
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 20))

    def test_does_not_block_cowboy(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_gd.commit_mason_guardian_night_pick(game, 20)
        ms_gd.activate_mason_guardian_day_protection(game)
        from bot.roles import mason_cowboy as ms_cw

        ms_cw.commit_mason_cowboy_day_pick(game, 20, confirmed=True)
        self.assertTrue(ms_cw.mason_cowboy_day_elimination_would_succeed(game, 20))


class MasonGuardianTownTests(unittest.TestCase):
    def test_guardian_is_town(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        guardian = _p(30, "Gd", Role.BODYGUARD)
        gm.add_player(game, guardian)
        self.assertTrue(ms_gd.is_mason_town_role(game, guardian))
        self.assertFalse(is_mafia_team(guardian.role))


class MasonGuardianMetadataTests(unittest.TestCase):
    def test_night_action_only(self) -> None:
        self.assertTrue(ms_gd.HAS_NIGHT_ACTION)
        self.assertFalse(ms_gd.HAS_DAY_ACTION)
        self.assertTrue(ms_gd.PROTECTS_ONLY_AGAINST_APACHE)

    def test_registered(self) -> None:
        self.assertTrue(is_registered_role(Role.BODYGUARD))
        self.assertIs(get_role_module(Role.BODYGUARD), ms_gd)
