"""تست منطق مشترک اسنایپر — bot/roles/sniper.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_SNIPER,
    NIGHT_ACTIONS,
    _apply_sniper_night_resolution,
    _bazpors_sniper_nights_enabled,
    _sniper_can_shoot,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_night_resolve import _apply_no_host_night_resolution
from bot.roles import sniper as sn_mod


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def make_12p_game() -> Game:
    players = {
        -1: _p(-1, 1, "رییس مافیا", Role.MAFIA_BOSS),
        -2: _p(-2, 2, "ناتو", Role.NATO),
        -3: _p(-3, 3, "شیاد", Role.SHIAD),
        -4: _p(-4, 4, "مافیا ساده", Role.MAFIA_BASIC),
        -5: _p(-5, 5, "هانتر", Role.HUNTER),
        -6: _p(-6, 6, "بازپرس", Role.INTERROGATOR),
        -7: _p(-7, 7, "کارآگاه", Role.DETECTIVE),
        -8: _p(-8, 8, "پزشک", Role.DOCTOR),
        -9: _p(-9, 9, "رویین تن", Role.RUINTAN),
        -10: _p(-10, 10, "تک‌تیرانداز", Role.SNIPER),
        -11: _p(-11, 11, "شهروند ۱", Role.CITIZEN),
        -12: _p(-12, 12, "شهروند ۲", Role.CITIZEN),
    }
    game = Game(
        room_code="sn",
        host_id=1,
        scenario_name="bazpors_salamat_test",
        players=players,
        max_players=12,
    )
    game.mafia_ids = {-1, -2, -3, -4}
    return game


class SniperModuleCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_find_alive_sniper(self) -> None:
        game = make_12p_game()
        sn = sn_mod.find_alive_sniper(game)
        self.assertIsNotNone(sn)
        self.assertEqual(sn.user_id, -10)

    def test_no_living_sniper(self) -> None:
        game = make_12p_game()
        game.players[-10].is_alive = False
        self.assertIsNone(sn_mod.find_alive_sniper(game))

    def test_nights_enabled_12_player(self) -> None:
        game = make_12p_game()
        self.assertTrue(sn_mod.nights_enabled(game))
        self.assertTrue(_bazpors_sniper_nights_enabled(game))

    def test_can_shoot_when_bullet_unused(self) -> None:
        game = make_12p_game()
        self.assertTrue(sn_mod.can_shoot(game))
        self.assertTrue(_sniper_can_shoot(game))

    def test_cannot_shoot_after_bullet_used(self) -> None:
        game = make_12p_game()
        sn_mod.mark_bullet_used(game)
        self.assertFalse(sn_mod.can_shoot(game))

    def test_shot_pool_excludes_sniper(self) -> None:
        game = make_12p_game()
        pool = sn_mod.shot_pool(game)
        self.assertNotIn(-10, {p.user_id for p in pool})
        self.assertIn(-11, {p.user_id for p in pool})

    def test_target_valid_rejects_self(self) -> None:
        game = make_12p_game()
        self.assertFalse(sn_mod.target_valid(game, -10))
        self.assertTrue(sn_mod.target_valid(game, -11))

    def test_commit_and_read_pick(self) -> None:
        game = make_12p_game()
        sn_mod.commit_pick(game, -2)
        self.assertEqual(sn_mod.night_target_uid(game), -2)
        sn_mod.clear_pick(game)
        self.assertIsNone(sn_mod.night_target_uid(game))

    def test_shoots_town_eliminates_sniper_only(self) -> None:
        game = make_12p_game()
        sn_mod.commit_pick(game, -11)
        sn_mod.apply_night_resolution(game, self.gm)
        self.assertTrue(sn_mod.bullet_used(game))
        self.assertFalse(game.players[-10].is_alive)
        self.assertTrue(game.players[-11].is_alive)

    def test_boss_shot_eliminates_nobody(self) -> None:
        game = make_12p_game()
        sn_mod.commit_pick(game, -1)
        sn_mod.apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-1].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_mafia_shot_without_doctor_eliminates_target(self) -> None:
        game = make_12p_game()
        sn_mod.commit_pick(game, -2)
        sn_mod.apply_night_resolution(game, self.gm)
        self.assertFalse(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)
        self.assertIn(-2, game.bazpors_sniper_eliminated_uids)

    def test_mafia_shot_with_doctor_save_spares_both(self) -> None:
        game = make_12p_game()
        sn_mod.commit_pick(game, -2)
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        sn_mod.apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_shim_apply_sniper_night_resolution(self) -> None:
        game = make_12p_game()
        sn_mod.commit_pick(game, -2)
        _apply_sniper_night_resolution(game, self.gm)
        self.assertFalse(game.players[-2].is_alive)


class SniperSemiAutoPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_sn_pick_advances_to_discipline(self) -> None:
        game = make_12p_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_SNIPER
        err = process_narrator_callback(game, self.gm, "sn_pick", -2, "")
        self.assertIsNone(err)
        self.assertEqual(sn_mod.night_target_uid(game), -2)
        self.assertEqual(game.bazpors_night_substep, "ns_discipline_ask")


class SniperNoHostPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_no_host_mafia_spared_when_doctor_saved(self) -> None:
        game = make_12p_game()
        game.bazpors_host_mode = "no_host"
        sn_mod.commit_pick(game, -2)
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4
        _apply_no_host_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_commit_shim(self) -> None:
        from bot.no_host_sniper_night import _commit_sniper_pick

        game = make_12p_game()
        _commit_sniper_pick(game, -2)
        self.assertEqual(sn_mod.night_target_uid(game), -2)


if __name__ == "__main__":
    unittest.main()
