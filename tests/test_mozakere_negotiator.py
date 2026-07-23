"""تست مذاکره‌کننده و مافیا ساده در سناریوی مذاکره."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import mafia_shot_allowed
from bot.game import GameManager, bazpors_counts_as_mafia_faction, is_mafia_team
from bot.models import Game, Player, Role
from bot.roles import detective as det
from bot.roles import mozakere_negotiator as neg_mod
from bot.roles import simple_mafia as sm_mod
from bot.roles.mozakere_negotiator import (
    MozakereNegotiationOutcome,
    commit_mozakere_negotiation,
)


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_game(gm: GameManager, *, n: int = 12) -> Game:
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    return game


def _assign_mafia_ids(game: Game, *uids: int) -> None:
    game.mafia_ids.update(uids)


class MozakereNegotiatorTests(unittest.TestCase):
    def test_negotiator_is_mafia_team(self) -> None:
        self.assertTrue(is_mafia_team(Role.MAFIA_NEGOTIATOR))

    def test_threshold_10p_requires_one_dead_mafia(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=10)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS))
        gm.add_player(game, _p(30, "M", Role.MAFIA_SIMPLE))
        _assign_mafia_ids(game, 10, 20, 30)
        self.assertEqual(neg_mod.required_eliminated_mafia_count(game), 1)
        self.assertFalse(neg_mod.can_mozakere_negotiate(game, game.players[10]))
        game.players[20].is_alive = False
        self.assertTrue(neg_mod.can_mozakere_negotiate(game, game.players[10]))

    def test_threshold_12p_requires_two_dead_mafia(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=12)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS))
        gm.add_player(game, _p(30, "M1", Role.MAFIA_SIMPLE))
        gm.add_player(game, _p(40, "M2", Role.MAFIA_SIMPLE_2))
        _assign_mafia_ids(game, 10, 20, 30, 40)
        neg = game.players[10]
        game.players[20].is_alive = False
        self.assertFalse(neg_mod.can_mozakere_negotiate(game, neg))
        game.players[30].is_alive = False
        self.assertTrue(neg_mod.can_mozakere_negotiate(game, neg))

    def test_success_on_citizen_and_armored(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=10)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(30, "C", Role.CITIZEN))
        gm.add_player(game, _p(40, "A", Role.ARMORED))
        _assign_mafia_ids(game, 10, 20)
        neg = game.players[10]

        r1 = commit_mozakere_negotiation(game, neg, game.players[30])
        self.assertEqual(r1.outcome, MozakereNegotiationOutcome.SUCCESS)
        self.assertTrue(game.players[30].mozakere_converted_by_negotiation)
        self.assertEqual(game.players[30].role, Role.MAFIA_SIMPLE)
        self.assertIn(30, game.mozakere_mafia_recruit_ids)
        self.assertTrue(bazpors_counts_as_mafia_faction(game, game.players[30]))

        game2 = _mozakere_game(gm, n=10)
        gm.add_player(game2, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game2, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game2, _p(40, "A", Role.ARMORED))
        _assign_mafia_ids(game2, 10, 20)
        r2 = commit_mozakere_negotiation(game2, game2.players[10], game2.players[40])
        self.assertEqual(r2.outcome, MozakereNegotiationOutcome.SUCCESS)

    def test_fail_on_invalid_roles(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=10)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(30, "D", Role.DOCTOR))
        _assign_mafia_ids(game, 10, 20)
        neg = game.players[10]
        result = commit_mozakere_negotiation(game, neg, game.players[30])
        self.assertEqual(result.outcome, MozakereNegotiationOutcome.INVALID_TARGET)
        self.assertEqual(game.players[30].role, Role.DOCTOR)
        self.assertNotIn(30, game.mozakere_mafia_recruit_ids)

    def test_once_per_game(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=10)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(30, "C1", Role.CITIZEN))
        gm.add_player(game, _p(40, "C2", Role.CITIZEN))
        _assign_mafia_ids(game, 10, 20)
        neg = game.players[10]
        commit_mozakere_negotiation(game, neg, game.players[30])
        self.assertFalse(neg_mod.can_mozakere_negotiate(game, neg))
        second = commit_mozakere_negotiation(game, neg, game.players[40])
        self.assertEqual(second.outcome, MozakereNegotiationOutcome.NOT_ALLOWED)

    def test_negotiation_blocks_mafia_shot_same_night(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=10)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(30, "D", Role.DOCTOR))
        _assign_mafia_ids(game, 10, 20)
        self.assertTrue(mafia_shot_allowed(game))
        commit_mozakere_negotiation(game, game.players[10], game.players[30])
        self.assertTrue(neg_mod.mafia_used_negotiation_tonight(game))
        self.assertFalse(mafia_shot_allowed(game))

    def test_detective_reads_recruit_positive(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=10)
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(30, "C", Role.CITIZEN))
        _assign_mafia_ids(game, 10, 20)
        commit_mozakere_negotiation(game, game.players[10], game.players[30])
        result = det.evaluate_inquiry(game, 30)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.POSITIVE)

    def test_bazpors_yakuzai_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "M", Role.MAFIA))
        for uid in (30, 40, 50, 60, 70):
            gm.add_player(game, _p(uid, f"C{uid}", Role.CITIZEN))
        from bot.roles import mafia_boss as boss_mod

        self.assertTrue(boss_mod.yakuzai_allowed(game, gm))


class MozakereNegotiatorPanelPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game_with_citizen_roles(self):
        game = _mozakere_game(self.gm, n=12)
        gm = self.gm
        gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(11, "Boss", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "Det", Role.DETECTIVE))
        gm.add_player(game, _p(22, "Arm", Role.ARMORED))
        gm.add_player(game, _p(23, "Sn", Role.SNIPER))
        gm.add_player(game, _p(24, "Jr", Role.JOURNALIST))
        gm.add_player(game, _p(25, "C1", Role.CITIZEN))
        gm.add_player(game, _p(26, "C2", Role.CITIZEN))
        _assign_mafia_ids(game, 10, 11)
        return game

    def test_panel_pool_includes_all_alive_non_mafia(self) -> None:
        game = self._game_with_citizen_roles()
        panel_ids = {p.user_id for p in neg_mod.negotiation_panel_target_pool(game)}
        self.assertEqual(
            panel_ids,
            {20, 21, 22, 23, 24, 25, 26},
        )
        self.assertNotIn(10, panel_ids)
        self.assertNotIn(11, panel_ids)

    def test_valid_target_pool_still_limited_to_recruitable_roles(self) -> None:
        game = self._game_with_citizen_roles()
        valid_ids = {p.user_id for p in neg_mod.negotiation_target_pool(game)}
        self.assertEqual(valid_ids, {22, 25, 26})
        self.assertNotIn(20, valid_ids)
        self.assertNotIn(21, valid_ids)

    def test_invalid_panel_pick_fails_commit_but_marks_used(self) -> None:
        game = _mozakere_game(self.gm, n=10)
        self.gm.add_player(game, _p(10, "Neg", Role.MAFIA_NEGOTIATOR))
        self.gm.add_player(game, _p(20, "Boss", Role.MAFIA_BOSS, alive=False))
        self.gm.add_player(game, _p(30, "Det", Role.DETECTIVE))
        _assign_mafia_ids(game, 10, 20)
        neg = game.players[10]
        result = commit_mozakere_negotiation(game, neg, game.players[30])
        self.assertEqual(result.outcome, MozakereNegotiationOutcome.INVALID_TARGET)
        self.assertTrue(neg_mod.negotiation_used(game))
        self.assertTrue(neg_mod.mafia_used_negotiation_tonight(game))
        self.assertFalse(mafia_shot_allowed(game))

    def test_pick_keyboard_uses_panel_pool_not_valid_targets_only(self) -> None:
        from bot.no_host_mozakere_negotiation import _pick_keyboard

        game = self._game_with_citizen_roles()
        kb = _pick_keyboard(game, 10)
        button_texts = [
            btn.text
            for row in kb.inline_keyboard
            for btn in row
        ]
        self.assertIn("Doc", button_texts)
        self.assertIn("Det", button_texts)
        self.assertIn("Sn", button_texts)
        self.assertIn("Jr", button_texts)
        self.assertNotIn("Neg", button_texts)
        self.assertNotIn("Boss", button_texts)


class MozakereSimpleMafiaTests(unittest.TestCase):
    def test_simple_roles_alias_and_logic(self) -> None:
        self.assertTrue(sm_mod.is_simple_mafia_role(Role.MAFIA_SIMPLE))
        self.assertTrue(sm_mod.is_simple_mafia_role(Role.MAFIA_SIMPLE_2))
        self.assertTrue(sm_mod.participates_in_mafia_team_night(Role.MAFIA_SIMPLE_2))

    def test_simple_mafia_in_mozakere_roster(self) -> None:
        from bot.game import mozakere_roles_for_count

        roles_12 = mozakere_roles_for_count(12)
        self.assertIn(Role.MAFIA_SIMPLE, roles_12)
        self.assertIn(Role.MAFIA_SIMPLE_2, roles_12)

    def test_registry_maps_simple_variants(self) -> None:
        from bot.roles.registry import resolve_registered_role

        self.assertEqual(resolve_registered_role(Role.MAFIA_SIMPLE), Role.MAFIA_BASIC)
        self.assertEqual(resolve_registered_role(Role.MAFIA_SIMPLE_2), Role.MAFIA_BASIC)


if __name__ == "__main__":
    unittest.main()
