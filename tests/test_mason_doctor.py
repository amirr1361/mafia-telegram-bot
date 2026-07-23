"""تست پزشک — سناریوی ماسون (منطق ایزوله)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Player, Role
from bot.roles import mason_doctor as ms_dr


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


def _seed_alive_players(game, alive: int) -> None:
    game.players.clear()
    for i in range(alive):
        game.players[100 + i] = _p(100 + i, f"P{i}", Role.TOWN_SIMPLE)


def _set_alive_in_full_room(game, gm: GameManager, alive: int, *, room: int) -> None:
    game.max_players = room
    game.players.clear()
    for i in range(room):
        gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
    for i in range(room - alive):
        game.players[100 + i].is_alive = False


class MasonDoctorCapacityTests(unittest.TestCase):
    def test_save_capacity_by_alive_count(self) -> None:
        gm = GameManager()
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
                game = _mason_game(gm, n=max(alive, 18))
                _seed_alive_players(game, alive)
                self.assertEqual(ms_dr.mason_doctor_save_capacity(game), expected)

    def test_capacity_uses_alive_not_room_size(self) -> None:
        gm = GameManager()
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
                game = _mason_game(gm, n=room)
                _set_alive_in_full_room(game, gm, alive, room=room)
                self.assertEqual(ms_dr.mason_doctor_save_capacity(game), expected)

    def test_multiple_saves_same_night(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        for i in range(8):
            gm.add_player(game, _p(20 + i, f"P{i}", Role.TOWN_SIMPLE))
        self.assertEqual(ms_dr.mason_doctor_save_capacity(game), 2)
        self.assertTrue(ms_dr.commit_mason_doctor_save(game, 20))
        self.assertTrue(ms_dr.commit_mason_doctor_save(game, 21))
        self.assertEqual(set(ms_dr.mason_doctor_night_save_uids(game)), {20, 21})
        self.assertFalse(ms_dr.can_add_mason_doctor_save(game))

    def test_single_save_when_few_alive(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        for i in range(6):
            gm.add_player(game, _p(20 + i, f"P{i}", Role.TOWN_SIMPLE))
        self.assertEqual(ms_dr.mason_doctor_save_capacity(game), 1)
        self.assertTrue(ms_dr.commit_mason_doctor_save(game, 20))
        self.assertFalse(ms_dr.commit_mason_doctor_save(game, 21))


class MasonDoctorSelfSaveTests(unittest.TestCase):
    def test_self_save_usage_line_zero(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        line = ms_dr.build_mason_doctor_self_save_usage_line(game)
        self.assertEqual(
            line,
            "🛡️ تعداد دفعات استفاده از نجات خود: ۰ از ۲",
        )

    def test_self_save_usage_line_after_one_save(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        game.mason_doctor_self_save_count = 1
        line = ms_dr.build_mason_doctor_self_save_usage_line(game)
        self.assertIn("۱ از", line)

    def test_pool_excludes_doctor_at_self_save_limit(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        doc = _p(10, "Doc", Role.DOCTOR)
        gm.add_player(game, doc)
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        game.mason_doctor_self_save_count = ms_dr.MASON_MAX_SELF_SAVES
        pool_ids = {p.user_id for p in ms_dr.mason_doctor_save_pool(game)}
        self.assertNotIn(doc.user_id, pool_ids)
        self.assertIn(20, pool_ids)

    def test_two_self_saves_per_game(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        self.assertTrue(ms_dr.can_mason_doctor_self_save(game))
        self.assertTrue(ms_dr.commit_mason_doctor_save(game, 10))
        ms_dr.commit_mason_doctor_pending_self_save(game)
        self.assertEqual(game.mason_doctor_self_save_count, 1)
        ms_dr.clear_mason_doctor_night_saves(game)
        self.assertTrue(ms_dr.commit_mason_doctor_save(game, 10))
        ms_dr.commit_mason_doctor_pending_self_save(game)
        self.assertEqual(game.mason_doctor_self_save_count, 2)
        self.assertFalse(ms_dr.can_mason_doctor_self_save(game))

    def test_third_self_save_rejected(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        game.mason_doctor_self_save_count = 2
        self.assertFalse(ms_dr.commit_mason_doctor_save(game, 10))
        self.assertEqual(ms_dr.mason_doctor_night_save_uids(game), [])


class MasonDoctorProtectionTests(unittest.TestCase):
    def test_blocks_mafia_shot_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_dr.commit_mason_doctor_save(game, 20)
        self.assertTrue(ms_dr.mason_mafia_shot_blocked_by_doctor_save(game, 20))

    def test_sniper_overrides_doctor_save(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(10, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Sn", Role.SNIPER))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        ms_dr.commit_mason_doctor_save(game, 20)
        from bot.roles import mason_sniper as ms_sn
        from bot.roles import mason_commander as ms_cmd

        ms_sn.commit_mason_sniper_night_selection(game, [20])
        ms_cmd.commit_mason_commander_approval(game, [20])
        self.assertTrue(ms_dr.mason_doctor_does_not_block_sniper(game, 20))


class BazporsDoctorUnchangedTests(unittest.TestCase):
    def test_bazpors_capacity_stays_one(self) -> None:
        from bot.roles import doctor as dr

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertEqual(dr.doctor_save_capacity(game), 1)


class MozakereDoctorUnchangedTests(unittest.TestCase):
    def test_mozakere_uses_alive_count_not_mason_module(self) -> None:
        from bot.roles import mozakere_doctor as mz_dr

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        for i in range(11):
            gm.add_player(game, _p(100 + i, f"P{i}", Role.CITIZEN))
        self.assertEqual(mz_dr.mozakere_doctor_save_capacity(game), 2)
