"""تست پزشک در سناریوی مذاکره."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.mozakere_role_descriptions import mozakere_role_description_fa
from bot.roles import doctor as dr
from bot.roles import mozakere_doctor as mz_dr
from bot.roles.night_state import doctor_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_game(gm: GameManager, *, n: int = 12, night: int = 1) -> Game:
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_night_count = night
    return game


def _seed_alive_players(game, alive: int) -> None:
    game.players.clear()
    for i in range(alive):
        game.players[100 + i] = _p(100 + i, f"P{i}", Role.CITIZEN)

class MozakereDoctorCapacityTests(unittest.TestCase):
    def test_save_capacity_by_alive_count(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=12)
        cases = [
            (7, 1),
            (8, 2),
            (9, 2),
            (11, 2),
            (12, 3),
            (15, 3),
            (16, 4),
            (18, 4),
        ]
        for alive, expected in cases:
            with self.subTest(alive=alive, expected=expected):
                _seed_alive_players(game, alive)
                self.assertEqual(mz_dr.mozakere_doctor_save_capacity(game), expected)
                self.assertEqual(dr.doctor_save_capacity(game), expected)

    def test_capacity_uses_alive_not_room_size(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=12)
        cases = [
            (18, 18, 4),
            (18, 16, 4),
            (18, 15, 3),
            (18, 14, 3),
            (12, 11, 2),
            (12, 8, 2),
            (12, 7, 1),
        ]
        for room, alive, expected in cases:
            with self.subTest(room=room, alive=alive, expected=expected):
                game.max_players = room
                _seed_alive_players(game, alive)
                self.assertEqual(mz_dr.mozakere_doctor_save_capacity(game), expected)

    def test_two_saves_when_eight_alive(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        for i in range(7):
            gm.add_player(game, _p(20 + i, f"P{i}", Role.CITIZEN))
        self.assertEqual(mz_dr.mozakere_doctor_save_capacity(game), 2)
        dr.commit_pick(game, 20)
        dr.commit_pick(game, 21)
        self.assertEqual(dr.save_uid_set_raw(game), {20, 21})
        self.assertFalse(dr.can_add_doctor_save(game))

    def test_one_save_when_seven_alive(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, n=12, night=4)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        for i in range(6):
            gm.add_player(game, _p(20 + i, f"P{i}", Role.CITIZEN))
        self.assertEqual(mz_dr.mozakere_doctor_save_capacity(game), 1)
        dr.commit_pick(game, 20)
        self.assertEqual(dr.save_uid_set_raw(game), {20})
        dr.commit_pick(game, 21)
        self.assertEqual(dr.save_uid_set_raw(game), {21})


class MozakereDoctorRoleDescriptionTests(unittest.TestCase):
    def test_doctor_description_contains_alive_based_rules(self) -> None:
        desc = mozakere_role_description_fa(Role.DOCTOR)
        self.assertIn("بر اساس تعداد بازیکنان زنده", desc)
        self.assertIn("۷ نفر یا کمتر زنده باشند ۱ نفر", desc)
        self.assertIn("۸ تا ۱۱ نفر زنده باشند ۲ نفر", desc)
        self.assertIn("۱۲ تا ۱۵ نفر زنده باشند ۳ نفر", desc)
        self.assertIn("۱۶ نفر یا بیشتر زنده باشند ۴ نفر", desc)
        self.assertIn("فقط دو بار اجازه نجات خودش را دارد", desc)
        self.assertNotIn("شب‌های اول تا سوم", desc)


class MozakereDoctorSelfSaveTests(unittest.TestCase):
    def test_self_save_first_and_second_allowed(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=1)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        self.assertTrue(mz_dr.can_mozakere_doctor_self_save(game))
        dr.commit_pick(game, 10)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)
        dr.commit_pending_self_save(game)
        self.assertEqual(game.mozakere_doctor_self_save_count, 1)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

        dr.commit_pick(game, 10)
        dr.commit_pending_self_save(game)
        self.assertEqual(game.mozakere_doctor_self_save_count, 2)
        self.assertTrue(dr.self_save_limit_reached(game))

    def test_self_save_third_not_allowed(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=2)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(20, "C", Role.CITIZEN))
        game.mozakere_doctor_self_save_count = 2
        self.assertFalse(mz_dr.can_mozakere_doctor_self_save(game))
        pool_ids = {p.user_id for p in dr.save_pool(game)}
        self.assertNotIn(10, pool_ids)
        dr.commit_pick(game, 10)
        self.assertEqual(dr.save_uid_set_raw(game), set())

    def test_mozakere_self_save_does_not_touch_bazpors_counter(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        game.bazpors_doctor_self_save_count = 99
        dr.commit_pick(game, 10)
        dr.commit_pending_self_save(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 99)
        self.assertEqual(game.mozakere_doctor_self_save_count, 1)

    def test_dual_pick_self_first_other_second_preserves_self_pending(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=1)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(20, "A", Role.CITIZEN))
        gm.add_player(game, _p(30, "B", Role.CITIZEN))
        for i in range(6):
            gm.add_player(game, _p(40 + i, f"F{i}", Role.CITIZEN))
        dr.commit_pick(game, 10)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)
        dr.commit_pick(game, 20)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(dr.save_uid_set_raw(game), {10, 20})
        dr.commit_pending_self_save(game)
        self.assertEqual(game.mozakere_doctor_self_save_count, 1)

    def test_dual_pick_self_second_pick(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=2)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(20, "A", Role.CITIZEN))
        for i in range(7):
            gm.add_player(game, _p(30 + i, f"F{i}", Role.CITIZEN))
        dr.commit_pick(game, 20)
        dr.commit_pick(game, 10)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)
        dr.commit_pending_self_save(game)
        self.assertEqual(game.mozakere_doctor_self_save_count, 1)

    def test_dual_pick_self_first_only_then_night_commit(self) -> None:
        gm = GameManager()
        game = _mozakere_game(gm, night=1)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        dr.commit_pick(game, 10)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)
        dr.commit_pending_self_save(game)
        self.assertEqual(game.mozakere_doctor_self_save_count, 1)


class BazporsDoctorUnchangedTests(unittest.TestCase):
    def test_bazpors_capacity_stays_one(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        for i in range(12):
            gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
        self.assertEqual(dr.doctor_save_capacity(game), 1)

    def test_bazpors_self_save_uses_bazpors_counter(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        dr.commit_pick(game, 10)
        dr.commit_pending_self_save(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 1)
        self.assertEqual(game.mozakere_doctor_self_save_count, 0)
        self.assertEqual(doctor_night_state(game).self_save_count, 1)


if __name__ == "__main__":
    unittest.main()
