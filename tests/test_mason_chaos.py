"""تست فاز آشوب (Chaos) — سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import (
    CHAOS_DAY_HANDSHAKE,
    DAY_DISCUSS,
    _sync_ki_as_today,
    bazpors_chaos_phase_enabled,
)
from bot.game import GameManager
from bot.mason_chaos import (
    mason_chaos_counts_met,
    should_start_mason_chaos,
    start_mason_chaos_flow,
    sync_mason_chaos_today,
)
from bot.models import Game, Player, Role
from bot.no_host_day_vote import no_host_end_day_vote_cb_allowed
from bot.no_host_night_resolve import build_no_host_day_started_broadcast_html
from bot.no_host_table_inquiry import no_host_finish_day_start_after_table_inquiry


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 16) -> Game:
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
    game.bazpors_narrator_host_day = 5
    game.bazpors_narrator_night_count = 5
    game.bazpors_narrator_step = DAY_DISCUSS
    return game


def _setup_three_alive(
    gm: GameManager,
    *,
    mafia_role: Role = Role.GODFATHER,
    town_roles: tuple[Role, Role] = (Role.TOWN_SIMPLE, Role.MASON),
) -> Game:
    game = _mason_game(gm)
    gm.add_player(game, _p(1, "Mafia", mafia_role))
    gm.add_player(game, _p(2, "Town1", town_roles[0]))
    gm.add_player(game, _p(3, "Town2", town_roles[1]))
    return game


class MasonChaosTriggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_counts_met_for_one_mafia_two_town(self) -> None:
        game = _setup_three_alive(self.gm)
        self.assertTrue(mason_chaos_counts_met(game, self.gm))
        self.assertTrue(should_start_mason_chaos(game, self.gm))

    def test_sync_sets_ki_as_today(self) -> None:
        game = _setup_three_alive(self.gm)
        sync_mason_chaos_today(game, self.gm)
        self.assertTrue(game.bazpors_ki_as_today)

    def test_three_town_does_not_start_chaos(self) -> None:
        game = _mason_game(self.gm)
        self.gm.add_player(game, _p(1, "T1", Role.TOWN_SIMPLE))
        self.gm.add_player(game, _p(2, "T2", Role.MASON))
        self.gm.add_player(game, _p(3, "T3", Role.DOCTOR))
        self.assertFalse(mason_chaos_counts_met(game, self.gm))
        self.assertFalse(should_start_mason_chaos(game, self.gm))
        self.assertIsNotNone(self.gm.check_winner(game))

    def test_two_mafia_one_town_does_not_start_chaos(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gm.add_player(game, _p(1, "M1", Role.GODFATHER))
        gm.add_player(game, _p(2, "M2", Role.MAFIA_BASIC))
        gm.add_player(game, _p(3, "T", Role.TOWN_SIMPLE))
        self.assertFalse(mason_chaos_counts_met(game, self.gm))
        self.assertFalse(should_start_mason_chaos(game, self.gm))
        self.assertIsNotNone(self.gm.check_winner(game))

    def test_four_alive_does_not_start_chaos(self) -> None:
        game = _setup_three_alive(self.gm)
        self.gm.add_player(game, _p(4, "Extra", Role.TOWN_SIMPLE))
        self.assertFalse(mason_chaos_counts_met(game, self.gm))
        self.assertFalse(should_start_mason_chaos(game, self.gm))

    def test_two_alive_does_not_start_chaos(self) -> None:
        game = _mason_game(self.gm)
        self.gm.add_player(game, _p(1, "M", Role.GODFATHER))
        self.gm.add_player(game, _p(2, "T", Role.TOWN_SIMPLE))
        self.assertFalse(mason_chaos_counts_met(game, self.gm))
        self.assertFalse(should_start_mason_chaos(game, self.gm))

    def test_day_broadcast_mentions_chaos(self) -> None:
        game = _setup_three_alive(self.gm)
        sync_mason_chaos_today(game, self.gm)
        body = build_no_host_day_started_broadcast_html(game, self.gm)
        self.assertIn("فاز آشوب", body)


class MasonChaosDayStartFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_day_start_triggers_chaos_not_normal_mason_day(self) -> None:
        gm = GameManager()
        game = _setup_three_alive(gm)
        bot = MagicMock()
        chaos_started = AsyncMock()
        mason_day = AsyncMock()

        with patch(
            "bot.no_host_table_inquiry.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.chaos_handshake.start_chaos_handshake_round",
            new=chaos_started,
        ), patch(
            "bot.bazpors_narrator.push_host_step",
            new=AsyncMock(),
        ), patch(
            "bot.mason_game_flow.mason_on_day_started_after_inquiry",
            new=mason_day,
        ):
            await no_host_finish_day_start_after_table_inquiry(bot, game, gm)

        self.assertEqual(game.bazpors_narrator_host_day, 6)
        self.assertTrue(game.bazpors_ki_as_today)
        self.assertEqual(game.bazpors_narrator_step, CHAOS_DAY_HANDSHAKE)
        chaos_started.assert_awaited_once()
        mason_day.assert_not_awaited()

    async def test_day_start_normal_flow_when_not_chaos(self) -> None:
        gm = GameManager()
        game = _setup_three_alive(gm)
        gm.add_player(game, _p(4, "Extra", Role.TOWN_SIMPLE))
        bot = MagicMock()
        mason_day = AsyncMock()

        with patch(
            "bot.no_host_table_inquiry.broadcast_to_alive_players",
            new=AsyncMock(),
        ), patch(
            "bot.chaos_handshake.start_chaos_handshake_round",
            new=AsyncMock(),
        ), patch(
            "bot.mason_game_flow.mason_on_day_started_after_inquiry",
            new=mason_day,
        ):
            await no_host_finish_day_start_after_table_inquiry(bot, game, gm)

        mason_day.assert_awaited_once()
        self.assertEqual(game.bazpors_narrator_step, DAY_DISCUSS)
        self.assertFalse(game.bazpors_ki_as_today)

    async def test_start_mason_chaos_flow_sets_handshake_step(self) -> None:
        gm = GameManager()
        game = _setup_three_alive(gm)
        bot = MagicMock()

        with patch(
            "bot.chaos_handshake.start_chaos_handshake_round",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_narrator.push_host_step",
            new=AsyncMock(),
        ):
            await start_mason_chaos_flow(bot, game, gm)

        self.assertEqual(game.bazpors_narrator_step, CHAOS_DAY_HANDSHAKE)
        self.assertTrue(game.bazpors_ki_as_today)

    async def test_chaos_day_blocks_normal_vote(self) -> None:
        gm = GameManager()
        game = _setup_three_alive(gm)
        game.bazpors_ki_as_today = True
        game.no_host_day1_vote_prompt_sent = True
        self.assertFalse(no_host_end_day_vote_cb_allowed(game))


class MasonChaosWinnerResolutionTests(unittest.TestCase):
    def test_citizen_handshake_wins(self) -> None:
        from bot.chaos_handshake import decide_chaos_winner

        gm = GameManager()
        game = _setup_three_alive(gm)
        outcome = decide_chaos_winner(game, {2: 3, 3: 2, 1: 2})
        self.assertEqual(outcome["winner"], "citizens")

    def test_mafia_handshake_wins(self) -> None:
        from bot.chaos_handshake import decide_chaos_winner

        gm = GameManager()
        game = _setup_three_alive(gm)
        outcome = decide_chaos_winner(game, {1: 2, 2: 1, 3: 1})
        self.assertEqual(outcome["winner"], "mafia")


class BazporsMozakereChaosRegressionTests(unittest.TestCase):
    def test_bazpors_chaos_unchanged(self) -> None:
        from tests.test_no_host_ki_as import make_no_host_room84_day6

        gm = GameManager()
        game = make_no_host_room84_day6()
        self.assertTrue(bazpors_chaos_phase_enabled(game))
        _sync_ki_as_today(game, gm)
        self.assertTrue(game.bazpors_ki_as_today)
        self.assertFalse(should_start_mason_chaos(game, gm))

    def test_mozakere_does_not_use_mason_chaos(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(1, "M", Role.MAFIA_BOSS))
        gm.add_player(game, _p(2, "T1", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(3, "T2", Role.DOCTOR))
        self.assertFalse(should_start_mason_chaos(game, gm))
        sync_mason_chaos_today(game, gm)
        self.assertFalse(game.bazpors_ki_as_today)
