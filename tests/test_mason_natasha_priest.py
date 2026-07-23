"""تست ناتاشا و کشیش — سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Player, Role
from bot.roles import mason_natasha as ms_nt
from bot.roles import mason_priest as ms_pr
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


class MasonNatashaTeamTests(unittest.TestCase):
    def test_natasha_is_mafia_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        natasha = _p(50, "Nt", Role.NATASHA)
        gm.add_player(game, natasha)
        self.assertTrue(ms_nt.is_mason_natasha(game, natasha))
        self.assertTrue(ms_nt.mason_natasha_is_mafia(game, natasha))
        self.assertTrue(is_mafia_team(natasha.role))


class MasonPriestTeamTests(unittest.TestCase):
    def test_priest_is_town(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        priest = _p(60, "Pr", Role.PRIEST)
        gm.add_player(game, priest)
        self.assertTrue(ms_pr.is_mason_priest(game, priest))
        self.assertTrue(ms_pr.mason_priest_is_town(game, priest))
        self.assertFalse(is_mafia_team(priest.role))


class MasonNatashaNightPickTests(unittest.TestCase):
    def test_can_choose_one_alive_player_other_than_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        natasha = _p(50, "Nt", Role.NATASHA)
        target = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, natasha)
        gm.add_player(game, target)
        self.assertTrue(ms_nt.mason_natasha_can_target(game, natasha, target))
        self.assertTrue(
            ms_nt.commit_mason_natasha_target(game, natasha, target, confirmed=True)
        )
        self.assertEqual(game.mason_natasha_target_uid, 20)
        self.assertTrue(game.mason_natasha_pick_confirmed)

    def test_can_target_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        natasha = _p(50, "Nt", Role.NATASHA)
        gm.add_player(game, natasha)
        self.assertIn(natasha, ms_nt.mason_natasha_night_target_pool(game))
        self.assertTrue(ms_nt.mason_natasha_can_target(game, natasha, natasha))
        self.assertTrue(
            ms_nt.commit_mason_natasha_target(game, natasha, natasha, confirmed=True)
        )
        self.assertEqual(game.mason_natasha_target_uid, 50)

    def test_cannot_target_dead_player(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        natasha = _p(50, "Nt", Role.NATASHA)
        dead = _p(20, "Dead", Role.TOWN_SIMPLE, alive=False)
        gm.add_player(game, natasha)
        gm.add_player(game, dead)
        self.assertNotIn(dead, ms_nt.mason_natasha_night_target_pool(game))
        self.assertFalse(ms_nt.mason_natasha_can_target(game, natasha, dead))


class MasonPriestNightPickTests(unittest.TestCase):
    def test_can_store_one_target_including_self(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        priest = _p(60, "Pr", Role.PRIEST)
        target = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, priest)
        gm.add_player(game, target)
        self.assertTrue(ms_pr.mason_priest_can_target(game, priest, target))
        self.assertTrue(
            ms_pr.commit_mason_priest_target(game, priest, target, confirmed=True)
        )
        self.assertEqual(game.mason_priest_target_uid, 20)
        self.assertTrue(ms_pr.mason_priest_can_target(game, priest, priest))
        self.assertTrue(
            ms_pr.commit_mason_priest_target(game, priest, priest, confirmed=True)
        )
        self.assertEqual(game.mason_priest_target_uid, 60)


class MasonNatashaPriestDayEffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _mason_game(self.gm)
        self.natasha = _p(50, "Nt", Role.NATASHA)
        self.priest = _p(60, "Pr", Role.PRIEST)
        self.target = _p(20, "Hasan", Role.TOWN_SIMPLE)
        self.gm.add_player(self.game, self.natasha)
        self.gm.add_player(self.game, self.priest)
        self.gm.add_player(self.game, self.target)

    def test_priest_block_cancels_silence_and_public_message(self) -> None:
        ms_nt.commit_mason_natasha_target(
            self.game, self.natasha, self.target, confirmed=True
        )
        ms_pr.commit_mason_priest_target(
            self.game, self.priest, self.target, confirmed=True
        )
        self.assertTrue(ms_pr.mason_priest_blocks_natasha(self.game))
        msg = ms_nt.resolve_mason_natasha_day_effect(self.game)
        self.assertIsNone(msg)
        self.assertIsNone(self.game.mason_silenced_uid_for_day)
        self.assertFalse(ms_nt.mason_player_silenced_today(self.game, self.target))

    def test_different_priest_target_silences_natasha_target(self) -> None:
        other = _p(30, "Ali", Role.TOWN_SIMPLE)
        self.gm.add_player(self.game, other)
        ms_nt.commit_mason_natasha_target(
            self.game, self.natasha, self.target, confirmed=True
        )
        ms_pr.commit_mason_priest_target(
            self.game, self.priest, other, confirmed=True
        )
        self.assertFalse(ms_pr.mason_priest_blocks_natasha(self.game))
        msg = ms_nt.resolve_mason_natasha_day_effect(self.game)
        self.assertEqual(
            msg,
            "Hasan امروز حق صحبت کردن ندارد و فقط در انتهای روز می‌تواند رای بدهد.",
        )
        self.assertEqual(self.game.mason_silenced_uid_for_day, 20)
        self.assertTrue(ms_nt.mason_player_silenced_today(self.game, self.target))

    def test_no_priest_pick_still_silences(self) -> None:
        ms_nt.commit_mason_natasha_target(
            self.game, self.natasha, self.target, confirmed=True
        )
        msg = ms_nt.resolve_mason_natasha_day_effect(self.game)
        self.assertEqual(
            msg,
            "Hasan امروز حق صحبت کردن ندارد و فقط در انتهای روز می‌تواند رای بدهد.",
        )
        self.assertTrue(ms_nt.mason_player_silenced_today(self.game, self.target))

    def test_no_result_messages_for_natasha_or_priest(self) -> None:
        other = _p(30, "Ali", Role.TOWN_SIMPLE)
        self.gm.add_player(self.game, other)
        ms_nt.commit_mason_natasha_target(
            self.game, self.natasha, self.target, confirmed=True
        )
        ms_pr.commit_mason_priest_target(
            self.game, self.priest, self.target, confirmed=True
        )
        blocked_msg = ms_nt.resolve_mason_natasha_day_effect(self.game)
        self.assertIsNone(blocked_msg)

        ms_nt.clear_mason_natasha_night_state(self.game)
        ms_pr.clear_mason_priest_night_state(self.game)
        ms_nt.clear_mason_silenced_for_day(self.game)
        ms_nt.commit_mason_natasha_target(
            self.game, self.natasha, self.target, confirmed=True
        )
        ms_pr.commit_mason_priest_target(
            self.game, self.priest, other, confirmed=True
        )
        public_msg = ms_nt.resolve_mason_natasha_day_effect(self.game)
        self.assertIsNotNone(public_msg)
        self.assertNotIn("ناتاشا", public_msg or "")
        self.assertNotIn("کشیش", public_msg or "")
        self.assertNotIn("Nt", public_msg or "")
        self.assertNotIn("Pr", public_msg or "")


class MasonNatashaPriestRegistryTests(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertTrue(is_registered_role(Role.NATASHA))
        self.assertTrue(is_registered_role(Role.PRIEST))
        self.assertIs(get_role_module(Role.NATASHA), ms_nt)
        self.assertIs(get_role_module(Role.PRIEST), ms_pr)


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_bazpors_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        natasha = _p(50, "Nt", Role.NATASHA)
        priest = _p(60, "Pr", Role.PRIEST)
        target = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, natasha)
        gm.add_player(game, priest)
        gm.add_player(game, target)
        self.assertFalse(ms_nt.is_mason_natasha(game, natasha))
        self.assertFalse(ms_pr.is_mason_priest(game, priest))
        self.assertFalse(
            ms_nt.commit_mason_natasha_target(game, natasha, target, confirmed=True)
        )
        self.assertFalse(
            ms_pr.commit_mason_priest_target(game, priest, target, confirmed=True)
        )
        self.assertIsNone(ms_nt.resolve_mason_natasha_day_effect(game))

    def test_mozakere_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        natasha = _p(50, "Nt", Role.NATASHA)
        priest = _p(60, "Pr", Role.PRIEST)
        target = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, natasha)
        gm.add_player(game, priest)
        gm.add_player(game, target)
        self.assertFalse(ms_nt.is_mason_natasha(game, natasha))
        self.assertFalse(ms_pr.is_mason_priest(game, priest))
        self.assertIsNone(ms_nt.resolve_mason_natasha_day_effect(game))
