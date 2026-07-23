"""تست منطق مشترک پزشک — bot/roles/doctor.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_DOC,
    NIGHT_ACTIONS,
    _apply_night_resolution,
    _commit_night_pending_state,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_doctor_night import _commit_doctor_pick
from bot.no_host_night_resolve import _apply_no_host_night_resolution
from bot.roles import doctor as dr
from tests.test_semi_auto_yaku_doctor_skip import make_semi_auto_game


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def _no_host_game(*, with_doctor: bool = True) -> Game:
    players: dict[int, Player] = {
        -1: _p(-1, 1, "مافیا", Role.MAFIA),
        -2: _p(-2, 2, "شهروند", Role.CITIZEN),
    }
    if with_doctor:
        players[-3] = _p(-3, 3, "پزشک", Role.DOCTOR)
    game = Game(
        room_code="DR1",
        host_id=1,
        scenario_name="bazpors",
        players=players,
    )
    game.bazpors_host_mode = "no_host"
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_night_count = 1
    game.bazpors_alive_at_night_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }
    return game


class DoctorModuleCoreTests(unittest.TestCase):
    def test_save_pool_all_alive_when_self_save_allowed(self) -> None:
        game = _no_host_game()
        pool_ids = {p.user_id for p in dr.save_pool(game)}
        self.assertEqual(pool_ids, {-1, -2, -3})

    def test_save_pool_excludes_doctor_at_self_save_limit(self) -> None:
        game = _no_host_game()
        game.bazpors_doctor_self_save_count = dr.MAX_SELF_SAVES
        pool_ids = {p.user_id for p in dr.save_pool(game)}
        self.assertNotIn(-3, pool_ids)
        self.assertEqual(pool_ids, {-1, -2})

    def test_save_pool_excludes_doctor_when_pending_self_save(self) -> None:
        game = _no_host_game()
        game.bazpors_night_pending_doctor_self_save = True
        pool_ids = {p.user_id for p in dr.save_pool(game)}
        self.assertNotIn(-3, pool_ids)

    def test_commit_pick_other_player(self) -> None:
        game = _no_host_game()
        dr.commit_pick(game, -2)
        self.assertEqual(game.bazpors_doctor_save_uids, [-2])
        self.assertEqual(game.actions.doctor_save, -2)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)
        self.assertEqual(dr.save_uid_set(game), {-2})

    def test_commit_pick_self_sets_pending(self) -> None:
        game = _no_host_game()
        dr.commit_pick(game, -3)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)

    def test_clear_pick(self) -> None:
        game = _no_host_game()
        dr.commit_pick(game, -2)
        dr.clear_pick(game)
        self.assertEqual(dr.save_uid_set_raw(game), set())
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)

    def test_save_uid_set_empty_when_nato_blocked(self) -> None:
        game = make_semi_auto_game()
        dr.commit_pick(game, -3)
        game.bazpors_nato_action_registered = True
        self.assertEqual(dr.save_uid_set(game), set())
        self.assertEqual(dr.save_uid_set_raw(game), {-3})

    def test_void_night_pick_clears_save_and_reverts_self_count(self) -> None:
        game = make_semi_auto_game()
        doc = game.players[-2]
        dr.commit_pick(game, doc.user_id)
        game.bazpors_doctor_self_save_count = 1
        game.bazpors_night_baseline_doctor_self_saves = 0
        game.bazpors_nato_action_registered = True
        dr.void_night_pick(game)
        self.assertEqual(dr.save_uid_set(game), set())
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_blocked_and_skip_after_yaku(self) -> None:
        game = make_semi_auto_game()
        self.assertFalse(dr.blocked_this_night(game))
        game.bazpors_yaku_night_civilian_uid = -3
        self.assertTrue(dr.blocked_this_night(game))
        self.assertTrue(dr.skip_after_yaku_this_night(game))

    def test_commit_pending_self_save(self) -> None:
        game = _no_host_game()
        game.bazpors_night_pending_doctor_self_save = True
        dr.commit_pending_self_save(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 1)
        self.assertFalse(game.bazpors_night_pending_doctor_self_save)

    def test_commit_pending_self_save_skipped_after_nato(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_night_pending_doctor_self_save = True
        game.bazpors_nato_action_registered = True
        dr.commit_pending_self_save(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 0)

    def test_find_alive_doctor_none_when_dead(self) -> None:
        game = _no_host_game()
        game.players[-3].is_alive = False
        self.assertIsNone(dr.find_alive_doctor(game))

    def test_no_living_doctor_empty_pool_still_alive_players(self) -> None:
        game = _no_host_game(with_doctor=False)
        pool = dr.save_pool(game)
        self.assertEqual({p.user_id for p in pool}, {-1, -2})

    def test_mafia_kill_blocked_by_doctor_save(self) -> None:
        game = make_semi_auto_game()
        game.players[-5] = _p(-5, 5, "مافیا", Role.MAFIA)
        dr.commit_pick(game, -5)
        self.assertTrue(dr.mafia_kill_blocked_by_doctor_save(game, -5))
        self.assertFalse(dr.mafia_kill_blocked_by_doctor_save(game, -1))
        self.assertFalse(dr.mafia_kill_blocked_by_doctor_save(game, -3))


class DoctorSemiAutoPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_semi_auto_dr_saves_other_player(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        err = process_narrator_callback(game, self.gm, "dr", -3, "")
        self.assertIsNone(err)
        self.assertEqual(dr.save_uid_set(game), {-3})

    def test_semi_auto_self_save_limit(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        game.bazpors_doctor_self_save_count = dr.MAX_SELF_SAVES
        err = process_narrator_callback(game, self.gm, "dr", -2, "")
        self.assertIn("دو بار", err or "")

    def test_semi_auto_dxd_clears_pick(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        dr.commit_pick(game, -3)
        err = process_narrator_callback(game, self.gm, "dxd", 0, "")
        self.assertIsNone(err)
        self.assertEqual(dr.save_uid_set_raw(game), set())

    def test_semi_auto_nato_blocks_new_pick(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        game.bazpors_nato_action_registered = True
        err = process_narrator_callback(game, self.gm, "dr", -3, "")
        self.assertIn("ناتویی", err or "")

    def test_semi_auto_night_resolve_doctor_saves_mafia_target(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4
        dr.commit_pick(game, -4)
        _apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-4].is_alive)

    def test_semi_auto_night_resolve_different_mafia_target_dies(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4
        dr.commit_pick(game, -3)
        _apply_night_resolution(game, self.gm)
        self.assertFalse(game.players[-4].is_alive)


class DoctorNoHostPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_no_host_commit_pick_via_shared_module(self) -> None:
        game = _no_host_game()
        _commit_doctor_pick(game, -2)
        self.assertEqual(dr.save_uid_set(game), {-2})

    def test_no_host_self_save_pending(self) -> None:
        game = _no_host_game()
        _commit_doctor_pick(game, -3)
        self.assertTrue(game.bazpors_night_pending_doctor_self_save)

    def test_no_host_night_resolve_doctor_saves_mafia_target(self) -> None:
        game = _no_host_game()
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -2
        _commit_doctor_pick(game, -2)
        _apply_no_host_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)

    def test_no_host_night_resolve_without_doctor_pick(self) -> None:
        game = _no_host_game()
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -2
        _apply_no_host_night_resolution(game, self.gm)
        self.assertFalse(game.players[-2].is_alive)

    def test_no_host_finalize_commits_self_save(self) -> None:
        game = _no_host_game()
        game.bazpors_night_pending_doctor_self_save = True
        _commit_night_pending_state(game)
        self.assertEqual(game.bazpors_doctor_self_save_count, 1)


class DoctorNightSimulationTests(unittest.TestCase):
    """شبیه‌سازی کوتاه شب با پزشک — هر دو مسیر."""

    def setUp(self) -> None:
        self.gm = GameManager()

    def test_semi_auto_full_night_doctor_path_executed(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -3
        process_narrator_callback(game, self.gm, "dr", -3, "")
        self.assertEqual(dr.save_uid_set(game), {-3})
        _commit_night_pending_state(game)
        _apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-3].is_alive)

    def test_no_host_full_night_doctor_path_executed(self) -> None:
        game = _no_host_game()
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -2
        _commit_doctor_pick(game, -2)
        _commit_night_pending_state(game)
        _apply_no_host_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)
        self.assertEqual(dr.save_uid_set_raw(game), {-2})


if __name__ == "__main__":
    unittest.main()
