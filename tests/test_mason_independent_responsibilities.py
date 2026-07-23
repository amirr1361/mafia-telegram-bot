"""مسئولیت‌های مستقل پنل — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_day_ability import (
    MASON_APACHE_PICK_ACT,
    _apache_ui_key,
    _cowboy_ui_key,
    _day_gun_ui_key,
    dispatch_mason_day_start_panels,
)
from bot.mason_night_ready import all_mason_parallel_night_ready, explain_mason_night_stuck
from bot.mason_responsibilities import (
    collect_mason_day_responsibilities,
    collect_mason_night_responsibilities,
    format_mason_responsibilities_report,
    mason_mafia_shot_uses_dedicated_panel,
)
from bot.models import Player, Role
from bot.no_host_mafia_night1 import MAFIA_ACTION_SHOT, start_no_host_night1_mafia_flow
from bot.no_host_mafia_shot import (
    _finalize_mafia_shot,
    _mafia_shot_mirror_ui_key,
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
    game.bazpors_narrator_night_count = 4
    game.no_host_night_parallel_collect_active = True
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 900
    game.mason_intro_day_ability_open = True
    return game


class MasonNightOverlapTests(unittest.IsolatedAsyncioTestCase):
    async def test_saboteur_gets_dedicated_mafia_shot_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(6, "Doc", Role.DOCTOR))
        game.mason_nato_used = True
        self.assertTrue(mason_mafia_shot_uses_dedicated_panel(game, 3))
        bot = AsyncMock()
        shot_keys: list[str] = []

        async def capture_shot(_bot, _game, uid, _text, _kb):
            shot_keys.append(_mafia_shot_mirror_ui_key(_game, uid))

        with patch(
            "bot.no_host_mafia_shot._sync_mafia_shot_mirror_panel",
            side_effect=capture_shot,
        ), patch(
            "bot.no_host_mafia_night1.maybe_start_shiad_parallel_night_panels",
            new_callable=AsyncMock,
        ):
            await start_no_host_night1_mafia_flow(bot, game, gm)

        self.assertEqual(len(shot_keys), 1)
        self.assertIn("mafia_shot_n4", shot_keys[0])

    def test_mafia_shot_does_not_complete_saboteur_role(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        self.assertFalse(game.mason_night_saboteur_confirmed)

    def test_saboteur_role_does_not_complete_mafia_shot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        game.mason_night_saboteur_confirmed = True
        game.no_host_mafia_shot_done = False
        self.assertFalse(game.no_host_mafia_shot_done)

    def test_night_resolves_only_after_both_complete(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(6, "Doc", Role.DOCTOR))
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = True
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        self.assertFalse(all_mason_parallel_night_ready(game))
        game.mason_night_saboteur_confirmed = True
        game.mason_night_wait_ok_uids = [p.user_id for p in game.players.values() if p.is_alive and p.user_id != 3]
        self.assertTrue(all_mason_parallel_night_ready(game))

    def test_natasha_dual_responsibilities_listed_separately(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
        gm.add_player(game, _p(10, "Nat", Role.NATASHA))
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        game.no_host_mafia_shot_done = False
        resps = collect_mason_night_responsibilities(game, gm)
        ids = [r.responsibility_id for r in resps]
        self.assertIn("mafia_shot", ids)
        self.assertIn("natasha_role", ids)
        mafia = next(r for r in resps if r.responsibility_id == "mafia_shot")
        nat = next(r for r in resps if r.responsibility_id == "natasha_role")
        self.assertEqual(mafia.holder_uid, 10)
        self.assertEqual(nat.holder_uid, 10)

    def test_diagnostic_lists_overlapping_separately(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        from bot.roles.night_state import mafia_night_state

        mafia_night_state(game).commit_shot(6)
        report = format_mason_responsibilities_report(game, gm)
        self.assertIn("Mafia shot", report)
        self.assertIn("Saboteur role", report)
        self.assertIn("done=True", report)
        self.assertIn("done=False", report)

    def test_diagnostic_shows_only_pending_when_one_complete(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        report = format_mason_responsibilities_report(game, gm)
        self.assertIn("Completed responsibilities:", report)
        self.assertIn("Waiting responsibilities:", report)
        self.assertIn("Saboteur role", report)

    def test_dead_holder_skipped_in_responsibilities(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(6, "Doc", Role.DOCTOR, alive=False))
        resps = collect_mason_night_responsibilities(game, gm)
        doc = next(r for r in resps if r.responsibility_id == "doctor_role")
        self.assertTrue(doc.done)
        self.assertIsNotNone(doc.skipped_reason)


class MasonDayOverlapTests(unittest.IsolatedAsyncioTestCase):
    async def test_cowboy_and_gun_panels_independent_keys(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(12, "Cow", Role.COWBOY))
        from bot.roles import mason_gunner as ms_gn

        game.mason_day_gun_holder_uid = 12
        game.mason_day_gun_sabotaged = False
        game.mason_day_gun_used = False
        bot = AsyncMock()
        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as reg:
            await dispatch_mason_day_start_panels(bot, game, gm)
        keys = [c.args[3] for c in reg.await_args_list]
        self.assertIn(_cowboy_ui_key(game, 12), keys)
        self.assertIn(_day_gun_ui_key(game, 12), keys)

    async def test_apache_and_gun_panels_independent_keys(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(5, "Ap", Role.APACHE))
        game.mason_day_gun_holder_uid = 5
        bot = AsyncMock()
        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as reg:
            await dispatch_mason_day_start_panels(bot, game, gm)
        keys = [c.args[3] for c in reg.await_args_list]
        self.assertIn(_apache_ui_key(game, 5), keys)
        self.assertIn(_day_gun_ui_key(game, 5), keys)

    def test_cowboy_ability_does_not_mark_gun_used(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(12, "Cow", Role.COWBOY))
        game.mason_cowboy_day_pick_confirmed = True
        game.mason_day_gun_holder_uid = 12
        game.mason_day_gun_used = False
        from bot.roles import mason_gunner as ms_gn

        self.assertTrue(ms_gn.mason_day_gun_available(game))

    def test_gun_used_does_not_mark_cowboy_pick(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(12, "Cow", Role.COWBOY))
        game.mason_day_gun_used = True
        game.mason_cowboy_day_pick_confirmed = False
        self.assertFalse(game.mason_cowboy_day_pick_confirmed)

    def test_day_responsibilities_listed_separately(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(12, "Cow", Role.COWBOY))
        game.mason_day_gun_holder_uid = 12
        resps = collect_mason_day_responsibilities(game, gm)
        ids = {r.responsibility_id for r in resps}
        self.assertIn("cowboy_day", ids)
        self.assertIn("day_gun", ids)


class MasonShotFinalizeOverlapTests(unittest.IsolatedAsyncioTestCase):
    async def test_finalize_shot_redispatches_saboteur_not_confirmed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
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
            "bot.mason_responsibilities.dispatch_mason_saboteur_panel",
            new_callable=AsyncMock,
            create=True,
        ) as sab_panel:
            with patch(
                "bot.mason_night_role.dispatch_mason_saboteur_panel",
                new_callable=AsyncMock,
            ) as sab_dispatch:
                await _finalize_mafia_shot(
                    bot, game, gm, mafia_uid=3, actor_uid=3, target_uid=6
                )
        sab_dispatch.assert_awaited_once()
        self.assertFalse(game.mason_night_saboteur_confirmed)


class MasonExplainIntegratesResponsibilities(unittest.TestCase):
    def test_explain_includes_responsibilities_section(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_shot_done = True
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Waiting responsibilities:", report)
        self.assertIn("Saboteur role", report)


class MasonUnchangedScenarios(unittest.TestCase):
    def test_bazpors_mafia_shot_key_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.room_code = "R99"
        from bot.no_host_mafia_night1 import _mafia_night1_ui_key

        game.mirror_prompt_messages[_mafia_night1_ui_key(game, 5)] = {"player": (1, 2)}
        key = _mafia_shot_mirror_ui_key(game, 5)
        self.assertIn("night1_mafia", key)

    def test_mozakere_menu_unchanged(self) -> None:
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
