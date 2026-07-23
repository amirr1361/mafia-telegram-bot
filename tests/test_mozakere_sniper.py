"""تست تک‌تیرانداز در سناریوی مذاکره."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Phase, Player, Role
from bot.no_host_sniper_night import (
    _should_run_no_host_sniper_flow,
    build_no_host_sniper_pick_html,
    start_no_host_sniper_night_flow,
)
from bot.roles import mozakere_sniper as mz_sn
from bot.roles import sniper as sn_mod
from bot.roles.mozakere_sniper import mozakere_sniper_remaining_shots_panel_line


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_game(gm: GameManager, *, max_players: int = 12) -> Game:
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=max_players,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 999
    return game


def _add_player(game: Game, gm: GameManager, player: Player) -> None:
    if game.phase != Phase.LOBBY:
        game.phase = Phase.LOBBY
    err = gm.add_player(game, player)
    assert err is None, err


def _arm_night(game: Game) -> None:
    game.phase = Phase.NIGHT
    game.bazpors_narrator_step = "night_actions"
    game.bazpors_night_substep = "ns_sniper"


class MozakereSniperCapacityTests(unittest.TestCase):
    def test_shot_limit_10_11(self) -> None:
        gm = GameManager()
        for n in (10, 11):
            game = _mozakere_game(gm, max_players=n)
            self.assertEqual(mz_sn.mozakere_sniper_shot_limit(game), 1)
            self.assertEqual(sn_mod.shot_limit(game), 1)

    def test_shot_limit_12_13_15(self) -> None:
        gm = GameManager()
        for n in (12, 13, 15):
            game = _mozakere_game(gm, max_players=n)
            self.assertEqual(mz_sn.mozakere_sniper_shot_limit(game), 2)
            self.assertEqual(sn_mod.shots_remaining(game), 2)

    def test_two_shots_allowed_in_12p(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        _add_player(game, gm, _p(30, "M2", Role.MAFIA_SIMPLE))
        _arm_night(game)
        self.assertTrue(sn_mod.can_shoot(game))
        sn_mod.commit_pick(game, 20)
        sn_mod.apply_night_resolution(game, gm)
        self.assertEqual(game.mozakere_sniper_shots_used, 1)
        self.assertTrue(sn_mod.can_shoot(game))
        sn_mod.commit_pick(game, 30)
        sn_mod.apply_night_resolution(game, gm)
        self.assertEqual(game.mozakere_sniper_shots_used, 2)
        self.assertFalse(sn_mod.can_shoot(game))

    def test_one_shot_only_in_10p(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=10)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        _arm_night(game)
        sn_mod.commit_pick(game, 20)
        sn_mod.apply_night_resolution(game, gm)
        self.assertEqual(game.mozakere_sniper_shots_used, 1)
        self.assertFalse(sn_mod.can_shoot(game))


class MozakereSniperResolutionTests(unittest.TestCase):
    def test_kills_mafia_when_not_saved(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        _arm_night(game)
        sn_mod.commit_pick(game, 20)
        sn_mod.apply_night_resolution(game, gm)
        self.assertFalse(game.players[20].is_alive)
        self.assertTrue(game.players[10].is_alive)

    def test_mafia_saved_by_doctor_survives(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        _arm_night(game)
        game.bazpors_doctor_save_uids = [20]
        sn_mod.commit_pick(game, 20)
        sn_mod.apply_night_resolution(game, gm)
        self.assertTrue(game.players[20].is_alive)
        self.assertTrue(game.players[10].is_alive)

    def test_wrong_shot_on_citizen_kills_sniper(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(30, "C", Role.CITIZEN))
        _arm_night(game)
        sn_mod.commit_pick(game, 30)
        sn_mod.apply_night_resolution(game, gm)
        self.assertTrue(game.players[30].is_alive)
        self.assertFalse(game.players[10].is_alive)

    def test_boss_immune_no_one_dies(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "B", Role.MAFIA_BOSS))
        _arm_night(game)
        sn_mod.commit_pick(game, 20)
        sn_mod.apply_night_resolution(game, gm)
        self.assertTrue(game.players[20].is_alive)
        self.assertTrue(game.players[10].is_alive)
        self.assertEqual(game.mozakere_sniper_shots_used, 1)


class MozakereSniperPanelTests(unittest.TestCase):
    def test_no_host_panel_gate_enabled(self) -> None:
        game = _mozakere_game(GameManager(), max_players=12)
        _arm_night(game)
        self.assertTrue(_should_run_no_host_sniper_flow(game))

    def test_nights_enabled_for_mozakere(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=10)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        self.assertTrue(sn_mod.nights_enabled(game))

    def test_pick_html_mentions_two_shots_for_12p(self) -> None:
        game = _mozakere_game(GameManager(), max_players=12)
        html = build_no_host_sniper_pick_html(game)
        self.assertIn("تعداد تیرهای باقی‌مانده شما: 2 از 2", html)

    def test_pick_html_shows_one_remaining_after_first_shot(self) -> None:
        game = _mozakere_game(GameManager(), max_players=12)
        game.mozakere_sniper_shots_used = 1
        html = build_no_host_sniper_pick_html(game)
        self.assertIn("تعداد تیرهای باقی‌مانده شما: 1 از 2", html)

    def test_pick_html_shows_one_of_one_for_10p(self) -> None:
        game = _mozakere_game(GameManager(), max_players=10)
        html = build_no_host_sniper_pick_html(game)
        self.assertIn("تعداد تیرهای باقی‌مانده شما: 1 از 1", html)

    def test_remaining_shots_panel_line(self) -> None:
        game = _mozakere_game(GameManager(), max_players=12)
        self.assertEqual(
            mozakere_sniper_remaining_shots_panel_line(game),
            "تعداد تیرهای باقی‌مانده شما: 2 از 2",
        )
        game.mozakere_sniper_shots_used = 1
        self.assertEqual(
            mozakere_sniper_remaining_shots_panel_line(game),
            "تعداد تیرهای باقی‌مانده شما: 1 از 2",
        )


class MozakereSniperShotCounterRegressionTests(unittest.TestCase):
    def test_12p_starts_with_two_shots(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        self.assertEqual(mz_sn.mozakere_sniper_shot_limit(game), 2)
        self.assertEqual(game.mozakere_sniper_shots_used, 0)
        self.assertEqual(sn_mod.shots_remaining(game), 2)

    def test_commit_pick_increments_shots_used_without_resolution(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        sn_mod.commit_pick(game, 20)
        self.assertEqual(game.mozakere_sniper_shots_used, 1)
        self.assertTrue(sn_mod.can_shoot(game))

    def test_no_shot_choice_does_not_increment_counter(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        sn_mod.commit_pick(game, None)
        self.assertEqual(game.mozakere_sniper_shots_used, 0)

    def test_second_shot_exhausts_quota(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(20, "M", Role.MAFIA_NEGOTIATOR))
        _add_player(game, gm, _p(30, "M2", Role.MAFIA_SIMPLE))
        sn_mod.commit_pick(game, 20)
        self.assertEqual(game.mozakere_sniper_shots_used, 1)
        sn_mod.clear_pick(game)
        sn_mod.commit_pick(game, 30)
        self.assertEqual(game.mozakere_sniper_shots_used, 2)
        self.assertFalse(sn_mod.can_shoot(game))


class MozakereSniperNextNightPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_sent_when_one_shot_remains(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(30, "Sn", Role.SNIPER))
        game.bazpors_narrator_night_count = 2
        game.mozakere_sniper_shots_used = 1
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_shot_done = True

        with patch(
            "bot.no_host_sniper_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_sniper_night.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register_panel:
            ok = await start_no_host_sniper_night_flow(
                AsyncMock(), game, gm, at_night_entry=True
            )

        self.assertTrue(ok)
        register_panel.assert_awaited_once()
        text = register_panel.call_args.args[4]
        self.assertIn("تعداد تیرهای باقی‌مانده شما: 1 از 2", text)

    async def test_no_panel_when_both_shots_used(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, max_players=12)
        _add_player(game, gm, _p(30, "Sn", Role.SNIPER))
        game.mozakere_sniper_shots_used = 2

        with patch(
            "bot.no_host_sniper_night.no_host_night_wait_phase_active",
            return_value=True,
        ), patch(
            "bot.no_host_sniper_night.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register_panel:
            ok = await start_no_host_sniper_night_flow(
                AsyncMock(), game, gm, at_night_entry=True
            )

        self.assertFalse(ok)
        register_panel.assert_not_awaited()
        self.assertTrue(game.no_host_sniper_pick_confirmed)


class BazporsSniperRegressionTests(unittest.TestCase):
    def test_bazpors_still_one_shot(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        _add_player(game, gm, _p(30, "M", Role.MAFIA_BASIC))
        _arm_night(game)
        self.assertEqual(sn_mod.shot_limit(game), 1)
        html = build_no_host_sniper_pick_html(game)
        self.assertIn("یک‌بار", html)
        self.assertNotIn("تعداد تیرهای باقی‌مانده", html)
        sn_mod.commit_pick(game, 30)
        self.assertEqual(game.mozakere_sniper_shots_used, 0)
        sn_mod.apply_night_resolution(game, gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(sn_mod.can_shoot(game))

    def test_bazpors_10p_sniper_nights_disabled(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        _add_player(game, gm, _p(10, "S", Role.SNIPER))
        self.assertFalse(sn_mod.nights_enabled(game))


if __name__ == "__main__":
    unittest.main()
