"""تست کارآگاه و شهروند ساده در سناریوی مذاکره."""

from __future__ import annotations

import unittest

from bot.models import Game, Phase, Player, Role
from bot.roles import detective as det
from bot.no_host_citizen_night import (
    _should_send_no_host_citizen_night,
    build_no_host_citizen_night_html,
)
from bot.no_host_detective_night import (
    _should_run_no_host_detective_flow,
    build_no_host_detective_pick_html,
)


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
        room_code="MDC1",
        host_id=1,
        scenario_name=scenario,
        phase=Phase.NIGHT,
        players={},
    )
    g.bazpors_host_mode = "no_host"
    g.no_host_assistant_narrator_active = True
    g.bot_assistant_user_id = 999
    g.no_host_night_parallel_collect_active = True
    g.bazpors_narrator_step = "night_actions"
    g.bazpors_night_substep = "ns_det"
    g.bazpors_narrator_night_count = 1
    return g


class MozakereDetectiveTests(unittest.TestCase):
    def test_boss_inquiry_is_negative(self) -> None:
        game = _game("mozakere")
        game.players[10] = _p(10, Role.DETECTIVE)
        game.players[20] = _p(20, Role.MAFIA_BOSS)
        result = det.evaluate_inquiry(game, 20)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)

    def test_non_boss_mafia_inquiry_is_positive(self) -> None:
        game = _game("mozakere")
        game.players[10] = _p(10, Role.DETECTIVE)
        game.players[21] = _p(21, Role.MAFIA_NEGOTIATOR)
        result = det.evaluate_inquiry(game, 21)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.POSITIVE)

    def test_shiad_block_ignored_in_mozakere(self) -> None:
        game = _game("mozakere")
        game.players[10] = _p(10, Role.DETECTIVE)
        game.players[22] = _p(22, Role.CITIZEN)
        self.assertFalse(det.scenario_has_shiad(game))
        det.block_inquiry_by_shiad(game)
        self.assertFalse(game.bazpors_detective_blocked)
        result = det.evaluate_inquiry(game, 22)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_TOWN)

    def test_detective_no_host_panel_gate_enabled_for_mozakere(self) -> None:
        game = _game("mozakere")
        self.assertTrue(_should_run_no_host_detective_flow(game))

    def test_detective_pick_panel_text_reused_between_scenarios(self) -> None:
        moz = _game("mozakere")
        baz = _game("bazpors")
        self.assertEqual(
            build_no_host_detective_pick_html(moz),
            build_no_host_detective_pick_html(baz),
        )


class MozakereCitizenTests(unittest.TestCase):
    def test_citizen_no_host_panel_gate_enabled_for_mozakere(self) -> None:
        game = _game("mozakere")
        game.bazpors_narrator_step = "night_start"
        self.assertTrue(_should_send_no_host_citizen_night(game))

    def test_citizen_panel_text_reused_between_scenarios(self) -> None:
        self.assertEqual(
            build_no_host_citizen_night_html(confirmed=False),
            build_no_host_citizen_night_html(confirmed=False),
        )


class BazporsRegressionTests(unittest.TestCase):
    def test_shiad_block_still_applies_in_bazpors(self) -> None:
        game = _game("bazpors")
        game.players[10] = _p(10, Role.DETECTIVE)
        game.players[22] = _p(22, Role.CITIZEN)
        self.assertTrue(det.scenario_has_shiad(game))
        det.block_inquiry_by_shiad(game)
        self.assertTrue(game.bazpors_detective_blocked)
        result = det.evaluate_inquiry(game, 22)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_SHIAD)


if __name__ == "__main__":
    unittest.main()

