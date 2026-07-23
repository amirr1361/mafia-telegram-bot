"""تست نقش ماسون و جاسوس — سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Player, Role
from bot.roles import mason_fraternity as ms_mf
from bot.roles import mason_spy as ms_sp
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
    )
    assert game is not None
    return game


def _setup_mason_team(game, gm) -> tuple[Player, Player]:
    mason = _p(10, "Amir", Role.MASON)
    town = _p(20, "Hasan", Role.TOWN_SIMPLE)
    gm.add_player(game, mason)
    gm.add_player(game, town)
    ms_mf.initialize_mason_team_for_new_game(game)
    return mason, town


class MasonRecruitPoolTests(unittest.TestCase):
    def test_cannot_recruit_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, _ = _setup_mason_team(game, gm)
        self.assertFalse(ms_mf.mason_can_recruit_target(game, mason, mason))

    def test_cannot_recruit_existing_member(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        self.assertFalse(ms_mf.mason_can_recruit_target(game, mason, hasan))
        self.assertNotIn(hasan, ms_mf.mason_recruit_target_pool(game, mason))

    def test_no_recruit_allowed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, _ = _setup_mason_team(game, gm)
        msg = ms_mf.commit_mason_recruit(game, mason, None)
        self.assertIsNone(msg)
        self.assertTrue(game.mason_mason_night_no_recruit)
        self.assertIsNone(game.mason_pending_recruit_uid)


class MasonRecruitMessageTests(unittest.TestCase):
    def test_first_recruit_message_names_holder(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        msg = ms_mf.commit_mason_recruit(game, mason, hasan)
        assert msg is not None
        self.assertIn("شما عضو تیم ماسون شدید", msg)
        self.assertIn("نقش ماسون متعلق به", msg)
        self.assertIn("Amir", msg)

    def test_second_recruit_lists_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        nader = _p(30, "Nader", Role.TOWN_SIMPLE)
        gm.add_player(game, nader)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        ms_mf.clear_mason_recruit_night_state(game)
        msg = ms_mf.commit_mason_recruit(game, mason, nader)
        assert msg is not None
        self.assertIn("اعضای تیم ماسون", msg)
        self.assertIn("Amir - ماسون", msg)
        self.assertIn("Hasan", msg)
        self.assertIn("Nader", msg)


class MasonTeamMembershipTests(unittest.TestCase):
    def test_pending_recruit_stored(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        self.assertEqual(game.mason_pending_recruit_uid, 20)
        self.assertTrue(ms_mf.is_mason_team_member(game, hasan))

    def test_dead_members_removed_from_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        hasan.is_alive = False
        ms_mf.remove_dead_from_mason_team(game)
        self.assertFalse(ms_mf.is_mason_team_member(game, hasan))
        self.assertNotIn(20, game.mason_team_member_ids)


class MasonSpyTests(unittest.TestCase):
    def test_spy_is_mafia(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        spy = _p(40, "Spy", Role.SPY)
        gm.add_player(game, spy)
        self.assertTrue(ms_sp.is_mason_spy(game, spy))
        self.assertTrue(ms_sp.mason_spy_is_mafia(game, spy))
        self.assertTrue(is_mafia_team(spy.role))

    def test_recruiting_spy_no_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, _ = _setup_mason_team(game, gm)
        spy = _p(40, "Nader", Role.SPY)
        gm.add_player(game, spy)
        ms_mf.commit_mason_recruit(game, mason, spy)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)
        self.assertTrue(result.spy_recruit_safe)
        self.assertEqual(result.eliminated_uids, ())
        self.assertTrue(ms_mf.is_mason_team_member(game, spy))


class MasonCollapseTests(unittest.TestCase):
    def test_recruiting_normal_mafia_collapses_town_members(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        ms_mf.clear_mason_recruit_night_state(game)
        mafia = _p(30, "Nader", Role.GODFATHER)
        gm.add_player(game, mafia)
        ms_mf.commit_mason_recruit(game, mason, mafia)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertTrue(result.collapsed)
        self.assertEqual(set(result.eliminated_uids), {10, 20})
        self.assertNotIn(30, result.eliminated_uids)

    def test_mafia_recruit_survives_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, _ = _setup_mason_team(game, gm)
        mafia = _p(30, "Nader", Role.GODFATHER)
        gm.add_player(game, mafia)
        ms_mf.commit_mason_recruit(game, mason, mafia)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertTrue(ms_mf.is_mason_team_member(game, mafia))

    def test_existing_spy_survives_later_mafia_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        spy = _p(40, "Spy", Role.SPY)
        gm.add_player(game, spy)
        ms_mf.commit_mason_recruit(game, mason, spy)
        ms_mf.resolve_mason_recruitment_result(game)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        ms_mf.clear_mason_recruit_night_state(game)
        mafia = _p(50, "Boss", Role.GODFATHER)
        gm.add_player(game, mafia)
        ms_mf.commit_mason_recruit(game, mason, mafia)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertTrue(result.collapsed)
        self.assertEqual(set(result.eliminated_uids), {10, 20})
        self.assertNotIn(40, result.eliminated_uids)
        self.assertNotIn(50, result.eliminated_uids)

    def test_town_recruit_no_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, hasan = _setup_mason_team(game, gm)
        ms_mf.commit_mason_recruit(game, mason, hasan)
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)
        self.assertEqual(result.eliminated_uids, ())

    def test_dead_recruit_before_resolve_no_collapse(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason, _ = _setup_mason_team(game, gm)
        mafia = _p(30, "Nader", Role.GODFATHER)
        gm.add_player(game, mafia)
        ms_mf.commit_mason_recruit(game, mason, mafia)
        mafia.is_alive = False
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)


class MasonFraternityRegistryTests(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertTrue(is_registered_role(Role.MASON))
        self.assertTrue(is_registered_role(Role.SPY))
        self.assertIs(get_role_module(Role.MASON), ms_mf)
        self.assertIs(get_role_module(Role.SPY), ms_sp)

    def test_no_recruit_label_constant(self) -> None:
        self.assertEqual(ms_mf.MASON_NO_RECRUIT_LABEL, "❌ انتخابی ندارم")


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_helpers_inert_outside_mason(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        mason = _p(10, "M", Role.MASON)
        gm.add_player(game, mason)
        self.assertFalse(ms_mf.is_mason_role_holder(game, mason))
        result = ms_mf.resolve_mason_recruitment_result(game)
        self.assertFalse(result.collapsed)

    def test_mozakere_unaffected(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        spy = _p(40, "Spy", Role.SPY)
        gm.add_player(game, spy)
        self.assertFalse(ms_sp.is_mason_spy(game, spy))
