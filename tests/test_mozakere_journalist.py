"""تست خبرنگار در سناریوی مذاکره."""

from __future__ import annotations

import unittest

from bot.models import Game, Phase, Player, Role
from bot.no_host_journalist_night import (
    _should_run_no_host_journalist_flow,
    build_no_host_journalist_idle_html,
    build_no_host_journalist_pick_html,
    no_host_journalist_act_active,
)
from bot.no_host_night_ready import _journalist_ready
from bot.roles import mozakere_journalist as jr_mod
from bot.roles.mozakere_journalist import (
    MozakereJournalistCheckKind,
    commit_check,
    evaluate_check,
    mozakere_journalist_active,
)
from bot.roles.mozakere_negotiator import (
    MozakereNegotiationOutcome,
    commit_mozakere_negotiation,
)
from bot.roles.registry import is_registered_role


def _p(uid: int, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=f"p{uid}",
        username=None,
        role=role,
        is_alive=alive,
    )


def _game(scenario: str) -> Game:
    g = Game(
        room_code="MJ1",
        host_id=1,
        scenario_name=scenario,
        phase=Phase.NIGHT,
        players={},
    )
    g.bazpors_host_mode = "no_host"
    g.no_host_assistant_narrator_active = True
    g.bot_assistant_user_id = 999
    g.no_host_night_parallel_collect_active = True
    g.bazpors_narrator_step = "night_start"
    g.bazpors_narrator_night_count = 1
    return g


def _mozakere_night_game() -> Game:
    g = _game("mozakere")
    g.bazpors_narrator_night_count = 2
    return g


class MozakereJournalistLogicTests(unittest.TestCase):
    def test_journalist_registered_only_as_role_module(self) -> None:
        self.assertTrue(is_registered_role(Role.JOURNALIST))

    def test_inactive_before_negotiation(self) -> None:
        game = _mozakere_night_game()
        game.players[50] = _p(50, Role.JOURNALIST)
        self.assertFalse(mozakere_journalist_active(game))

    def test_active_after_negotiation_used(self) -> None:
        game = _mozakere_night_game()
        game.players[50] = _p(50, Role.JOURNALIST)
        game.mozakere_negotiation_used = True
        self.assertTrue(mozakere_journalist_active(game))

    def test_positive_for_recruited_target(self) -> None:
        game = _mozakere_night_game()
        game.players[30] = _p(30, Role.CITIZEN)
        game.mozakere_mafia_recruit_ids.add(30)
        result = evaluate_check(game, 30)
        self.assertEqual(result.kind, MozakereJournalistCheckKind.POSITIVE)

    def test_negative_for_non_recruited_citizen(self) -> None:
        game = _mozakere_night_game()
        game.players[30] = _p(30, Role.CITIZEN)
        result = evaluate_check(game, 30)
        self.assertEqual(result.kind, MozakereJournalistCheckKind.NEGATIVE)

    def test_negative_for_original_mafia_not_recruited(self) -> None:
        game = _mozakere_night_game()
        game.players[20] = _p(20, Role.MAFIA_BOSS)
        result = evaluate_check(game, 20)
        self.assertEqual(result.kind, MozakereJournalistCheckKind.NEGATIVE)

    def test_negative_after_failed_negotiation_target(self) -> None:
        game = _mozakere_night_game()
        game.players[10] = _p(10, Role.MAFIA_NEGOTIATOR)
        game.players[20] = _p(20, Role.MAFIA_BOSS, alive=False)
        game.players[30] = _p(30, Role.DOCTOR)
        game.mafia_ids.update({10, 20})
        outcome = commit_mozakere_negotiation(game, game.players[10], game.players[30])
        self.assertEqual(outcome.outcome, MozakereNegotiationOutcome.INVALID_TARGET)
        self.assertNotIn(30, game.mozakere_mafia_recruit_ids)
        result = evaluate_check(game, 30)
        self.assertEqual(result.kind, MozakereJournalistCheckKind.NEGATIVE)

    def test_positive_after_successful_recruit(self) -> None:
        game = _mozakere_night_game()
        game.players[10] = _p(10, Role.MAFIA_NEGOTIATOR)
        game.players[20] = _p(20, Role.MAFIA_BOSS, alive=False)
        game.players[30] = _p(30, Role.CITIZEN)
        game.mafia_ids.update({10, 20})
        commit_mozakere_negotiation(game, game.players[10], game.players[30])
        result = evaluate_check(game, 30)
        self.assertEqual(result.kind, MozakereJournalistCheckKind.POSITIVE)

    def test_commit_check_stores_state(self) -> None:
        game = _mozakere_night_game()
        game.players[30] = _p(30, Role.CITIZEN)
        game.mozakere_mafia_recruit_ids.add(30)
        commit_check(game, 30)
        self.assertEqual(game.mozakere_journalist_target_uid, 30)
        self.assertTrue(game.mozakere_journalist_ack_positive)

    def test_bazpors_journalist_logic_inert(self) -> None:
        game = _game("bazpors")
        game.players[50] = _p(50, Role.JOURNALIST)
        game.mozakere_mafia_recruit_ids.add(50)
        self.assertFalse(mozakere_journalist_active(game))
        self.assertFalse(jr_mod.target_joined_mafia_by_negotiation(game, game.players[50]))


class MozakereJournalistPanelTests(unittest.TestCase):
    def test_no_host_flow_only_mozakere(self) -> None:
        moz = _mozakere_night_game()
        moz.players[50] = _p(50, Role.JOURNALIST)
        baz = _game("bazpors")
        baz.players[50] = _p(50, Role.JOURNALIST)
        self.assertTrue(_should_run_no_host_journalist_flow(moz))
        self.assertFalse(_should_run_no_host_journalist_flow(baz))

    def test_idle_panel_text(self) -> None:
        text = build_no_host_journalist_idle_html()
        self.assertIn("مذاکره هنوز انجام نشده است", text)

    def test_pick_panel_text(self) -> None:
        game = _mozakere_night_game()
        text = build_no_host_journalist_pick_html(game)
        self.assertIn("با مذاکره به تیم مافیا", text)

    def test_act_active_only_mozakere(self) -> None:
        self.assertTrue(no_host_journalist_act_active(_mozakere_night_game(), "jic"))
        self.assertFalse(no_host_journalist_act_active(_game("bazpors"), "jic"))

    def test_ready_idle_before_negotiation(self) -> None:
        game = _mozakere_night_game()
        game.players[50] = _p(50, Role.JOURNALIST)
        self.assertFalse(_journalist_ready(game))
        game.no_host_journalist_idle_confirmed = True
        self.assertTrue(_journalist_ready(game))

    def test_ready_pick_after_negotiation(self) -> None:
        game = _mozakere_night_game()
        game.players[50] = _p(50, Role.JOURNALIST)
        game.mozakere_negotiation_used = True
        self.assertFalse(_journalist_ready(game))
        game.no_host_journalist_pick_confirmed = True
        self.assertTrue(_journalist_ready(game))

    def test_bazpors_journalist_ready_always_true(self) -> None:
        game = _game("bazpors")
        game.players[50] = _p(50, Role.JOURNALIST)
        self.assertTrue(_journalist_ready(game))


if __name__ == "__main__":
    unittest.main()
