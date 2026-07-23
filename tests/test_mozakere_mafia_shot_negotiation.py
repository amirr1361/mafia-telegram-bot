"""شات / مذاکره مافیا — سناریوی مذاکره (no_host)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import _enter_night_from_day_end, mafia_shot_allowed
from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_NEGOTIATE,
    MAFIA_ACTION_SHOT,
    _available_mafia_actions,
    _mozakere_available_mafia_actions,
    build_mozakere_mafia_operation_menu_html,
    build_no_host_mafia_night1_menu_html,
    start_no_host_night1_mafia_flow,
)
from bot.no_host_mafia_shot import build_no_host_mafia_shot_pick_html
from bot.no_host_mozakere_negotiation import (
    build_mozakere_negotiation_broadcast_html,
    build_no_host_negotiator_pick_html,
)
from bot.no_host_journalist_night import build_no_host_journalist_pick_html
from bot.roles.mozakere_journalist import mozakere_journalist_active
from bot.roles.mozakere_negotiator import (
    eliminated_mafia_teammate_count,
    negotiation_allowed,
)


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def _mozakere_10p(gm: GameManager, *, night: int = 1) -> object:
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=10,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_night_count = night
    game.no_host_assistant_narrator_active = True
    gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
    gm.add_player(game, _p(11, "Neg", Role.MAFIA_NEGOTIATOR, seat=2))
    gm.add_player(game, _p(12, "M", Role.MAFIA_SIMPLE, seat=3))
    for uid, seat in ((20, 4), (21, 5), (22, 6), (23, 7), (24, 8), (25, 9), (26, 10)):
        gm.add_player(game, _p(uid, f"C{uid}", Role.CITIZEN, seat=seat))
    game.mafia_ids.update({10, 11, 12})
    return game


def _mozakere_12p(gm: GameManager, *, night: int = 2) -> object:
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_night_count = night
    gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
    gm.add_player(game, _p(11, "Neg", Role.MAFIA_NEGOTIATOR, seat=2))
    gm.add_player(game, _p(12, "M1", Role.MAFIA_SIMPLE, seat=3))
    gm.add_player(game, _p(13, "M2", Role.MAFIA_SIMPLE_2, seat=4))
    gm.add_player(game, _p(20, "Cit", Role.CITIZEN, seat=5))
    gm.add_player(game, _p(30, "Jr", Role.JOURNALIST, seat=6))
    game.mafia_ids.update({10, 11, 12, 13})
    return game


class MozakereMafiaActionAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_shot_only_when_negotiation_not_allowed(self) -> None:
        game = _mozakere_12p(self.gm)
        actions = _mozakere_available_mafia_actions(game)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])
        self.assertNotIn(MAFIA_ACTION_NEGOTIATE, actions)

    def test_shot_and_negotiate_when_allowed(self) -> None:
        game = _mozakere_12p(self.gm)
        game.players[12].is_alive = False
        game.players[13].is_alive = False
        actions = _mozakere_available_mafia_actions(game)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT, MAFIA_ACTION_NEGOTIATE])
        self.assertTrue(negotiation_allowed(game))

    def test_bazpors_actions_unchanged(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS))
        self.gm.add_player(game, _p(20, "Cit", Role.CITIZEN))
        actions = _available_mafia_actions(game, self.gm)
        self.assertIn(MAFIA_ACTION_SHOT, actions)
        self.assertNotIn(MAFIA_ACTION_NEGOTIATE, actions)


class MozakereMafiaPanelHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_shot_only_panel_html(self) -> None:
        game = _mozakere_12p(self.gm, night=1)
        html_msg = build_no_host_mafia_shot_pick_html(game)
        self.assertIn("شب اول", html_msg)
        self.assertIn("ثبت هدف شات", html_msg)
        self.assertIn("حداقل و حداکثر یک نفر", html_msg)

    def test_operation_menu_html(self) -> None:
        game = _mozakere_12p(self.gm, night=3)
        game.players[12].is_alive = False
        game.players[13].is_alive = False
        html_msg = build_mozakere_mafia_operation_menu_html(game)
        self.assertIn("شب سوم", html_msg)
        self.assertIn("انتخاب عملیات تیم مافیا", html_msg)
        self.assertIn("شات کردن", html_msg)
        self.assertIn("مذاکره کردن", html_msg)

    def test_menu_html_uses_mozakere_operation_text(self) -> None:
        game = _mozakere_12p(self.gm)
        game.players[12].is_alive = False
        game.players[13].is_alive = False
        self.assertIn(
            "انتخاب عملیات تیم مافیا",
            build_no_host_mafia_night1_menu_html(game),
        )

    def test_negotiator_pick_html(self) -> None:
        self.assertIn("مذاکره", build_no_host_negotiator_pick_html())
        self.assertIn("چه بازیکنی", build_no_host_negotiator_pick_html())

    def test_broadcast_html(self) -> None:
        self.assertEqual(
            build_mozakere_negotiation_broadcast_html(),
            "تیم مافیا در حال مذاکره",
        )


class MozakereNegotiationFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_negotiate_choice_blocks_shot(self) -> None:
        from bot.no_host_mafia_night1 import _finalize_mozakere_negotiate_action

        game = _mozakere_12p(self.gm)
        game.players[12].is_alive = False
        game.players[13].is_alive = False
        game.no_host_mafia_night1_flow_active = True
        game.no_host_mafia_night1_panel_uids = [10]

        with patch(
            "bot.no_host_mafia_night1._edit_mafia_prompt",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mozakere_negotiation.broadcast_mozakere_negotiation_started",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mozakere_negotiation.start_no_host_mozakere_negotiator_flow",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            await _finalize_mozakere_negotiate_action(
                AsyncMock(), game, self.gm, mafia_uid=10, actor_uid=10
            )

        self.assertTrue(game.mozakere_negotiation_tonight)
        self.assertFalse(mafia_shot_allowed(game))
        self.assertEqual(game.no_host_mafia_night1_chosen_action, MAFIA_ACTION_NEGOTIATE)

    async def test_negotiator_commit_activates_journalist_panel(self) -> None:
        from bot.no_host_mozakere_negotiation import dispatch_no_host_mozakere_negotiator

        game = _mozakere_12p(self.gm)
        game.players[12].is_alive = False
        game.players[13].is_alive = False
        game.no_host_negotiator_flow_active = True
        game.no_host_journalist_idle_confirmed = True
        game.mozakere_negotiation_tonight = True

        callback = MagicMock()
        callback.answer = AsyncMock()

        with patch(
            "bot.no_host_mozakere_negotiation._sync_panel",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_journalist_night.activate_journalist_after_mozakere_negotiation",
            new_callable=AsyncMock,
        ) as activate_jr, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new_callable=AsyncMock,
        ):
            game.no_host_negotiator_pending_tid = 20
            await dispatch_no_host_mozakere_negotiator(
                callback,
                AsyncMock(),
                game,
                self.gm,
                neg_uid=11,
                actor_uid=11,
                act="negc",
                tid=20,
            )

        self.assertTrue(game.no_host_negotiator_pick_confirmed)
        self.assertTrue(game.mozakere_negotiation_used)
        activate_jr.assert_awaited_once()

    def test_journalist_pick_html_after_negotiation(self) -> None:
        game = _mozakere_12p(self.gm)
        game.mozakere_negotiation_used = True
        self.assertTrue(mozakere_journalist_active(game))
        html_msg = build_no_host_journalist_pick_html(game)
        self.assertIn("مذاکره به پایان رسید", html_msg)
        self.assertIn("استعلام", html_msg)


class MozakereMafiaNightAfterDay1VoteTests(unittest.IsolatedAsyncioTestCase):
    """پس از حذف مافیا در رأی روز معارفه — پنل شب بعدی رئیس مافیا."""

    def setUp(self) -> None:
        self.gm = GameManager()

    def test_day1_vote_mafia_elim_counts_toward_negotiation_threshold(self) -> None:
        game = _mozakere_10p(self.gm)
        game.players[12].is_alive = False
        self.assertEqual(eliminated_mafia_teammate_count(game), 1)
        self.assertTrue(negotiation_allowed(game))

    def test_recruit_not_counted_in_eliminated_original_mafia(self) -> None:
        game = _mozakere_10p(self.gm)
        recruit = game.players[20]
        recruit.mozakere_original_role = Role.CITIZEN
        recruit.mozakere_converted_by_negotiation = True
        recruit.role = Role.MAFIA_SIMPLE
        game.mozakere_mafia_recruit_ids.add(20)
        game.mafia_ids.add(20)
        recruit.is_alive = False
        game.players[12].is_alive = False
        self.assertEqual(eliminated_mafia_teammate_count(game), 1)

    def test_enter_night_from_day_end_resets_mafia_night1_for_mozakere(self) -> None:
        game = _mozakere_10p(self.gm)
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_flow_active = True
        _enter_night_from_day_end(game)
        self.assertFalse(game.no_host_mafia_night1_done)
        self.assertFalse(game.no_host_mafia_night1_flow_active)
        self.assertTrue(game.no_host_night_parallel_collect_active)

    async def test_boss_gets_operation_menu_after_day1_mafia_elim(self) -> None:
        game = _mozakere_10p(self.gm, night=0)
        game.players[12].is_alive = False
        _enter_night_from_day_end(game)
        self.assertTrue(negotiation_allowed(game))

        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt",
            new_callable=AsyncMock,
        ) as send_prompt:
            await start_no_host_night1_mafia_flow(AsyncMock(), game, self.gm)

        send_prompt.assert_awaited_once()
        _args = send_prompt.await_args
        assert _args is not None
        text = _args.args[3]
        self.assertIn("انتخاب عملیات تیم مافیا", text)
        self.assertIn("شات کردن", text)
        self.assertIn("مذاکره کردن", text)
        self.assertTrue(game.no_host_mafia_night1_flow_active)

    async def test_boss_gets_direct_shot_when_threshold_not_met(self) -> None:
        game = _mozakere_12p(self.gm, night=0)
        _enter_night_from_day_end(game)
        self.assertFalse(negotiation_allowed(game))

        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt",
            new_callable=AsyncMock,
        ) as send_prompt:
            await start_no_host_night1_mafia_flow(AsyncMock(), game, self.gm)

        send_prompt.assert_awaited_once()
        _args = send_prompt.await_args
        assert _args is not None
        text = _args.args[3]
        self.assertIn("ثبت هدف شات", text)
        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertTrue(game.no_host_mafia_shot_flow_active)
