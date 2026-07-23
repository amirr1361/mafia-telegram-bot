"""تست منطق مشترک بازپرس — bot/roles/interrogator.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.models import Game, Player, Role
from bot.roles import interrogator as int_mod


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _game_with_interrogator(*, host_mode: str = "semi_auto") -> Game:
    return Game(
        room_code="int",
        host_id=1,
        scenario_name="bazpors",
        players={
            10: _p(10, "Int", Role.INTERROGATOR, seat=1),
            20: _p(20, "A", Role.CITIZEN, seat=2),
            30: _p(30, "B", Role.CITIZEN, seat=3),
            40: _p(40, "M", Role.MAFIA_BASIC, seat=4),
        },
        max_players=8,
        bazpors_host_mode=host_mode,
    )


class InterrogatorModuleCoreTests(unittest.TestCase):
    def test_find_alive_interrogator(self) -> None:
        game = _game_with_interrogator()
        intr = int_mod.find_alive_interrogator(game)
        self.assertIsNotNone(intr)
        self.assertEqual(intr.user_id, 10)

    def test_no_living_interrogator(self) -> None:
        game = _game_with_interrogator()
        game.players[10].is_alive = False
        self.assertIsNone(int_mod.find_alive_interrogator(game))

    def test_ability_unused_at_start(self) -> None:
        game = _game_with_interrogator()
        self.assertFalse(int_mod.ability_used(game))

    def test_mark_ability_used(self) -> None:
        game = _game_with_interrogator()
        int_mod.mark_ability_used(game)
        self.assertTrue(int_mod.ability_used(game))

    def test_int1_pool_excludes_dead(self) -> None:
        game = _game_with_interrogator()
        game.players[30].is_alive = False
        pool = int_mod.int1_pool(game)
        self.assertEqual({p.user_id for p in pool}, {10, 20, 40})

    def test_commit_first_and_second_nominee(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        self.assertEqual(int_mod.first_nominee_uid(game), 20)
        self.assertEqual(int_mod.pending_pick_uid(game), 20)
        self.assertFalse(int_mod.night_finished(game))

        int_mod.commit_second_nominee(game, 30)
        self.assertEqual(int_mod.second_nominee_uid(game), 30)
        self.assertIsNone(int_mod.pending_pick_uid(game))
        self.assertTrue(int_mod.night_finished(game))

    def test_second_target_must_differ_from_first(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        self.assertFalse(int_mod.second_target_valid(game, 20))
        self.assertTrue(int_mod.second_target_valid(game, 30))

    def test_clear_night_pick(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        int_mod.clear_night_pick(game)
        self.assertIsNone(int_mod.first_nominee_uid(game))
        self.assertIsNone(int_mod.second_nominee_uid(game))
        self.assertFalse(int_mod.night_finished(game))

    def test_refresh_ready_for_day_when_nominees_alive(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        int_mod.refresh_ready_for_day(game)
        self.assertTrue(int_mod.ready_for_day(game))
        self.assertFalse(int_mod.cancel_next_day(game))

    def test_cancel_when_both_nominees_die_same_night(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.players[20].is_alive = False
        game.players[30].is_alive = False
        int_mod.refresh_ready_for_day(game)
        self.assertTrue(int_mod.cancel_next_day(game))
        self.assertFalse(int_mod.ready_for_day(game))

    def test_one_nominee_dies_cancels_session(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.players[20].is_alive = False
        int_mod.refresh_ready_for_day(game)
        self.assertTrue(int_mod.cancel_next_day(game))

    def test_interrogator_dies_nominees_alive_session_proceeds(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_alive_at_night_start[10] = True
        game.players[10].is_alive = False
        int_mod.refresh_ready_for_day(game)
        self.assertTrue(int_mod.ready_for_day(game))
        self.assertFalse(int_mod.cancel_next_day(game))

    def test_day_vote_pool_alive_nominees_only(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        game.players[20].is_alive = False
        pool = int_mod.day_vote_pool(game)
        self.assertEqual([p.user_id for p in pool], [30])

    def test_clear_day_targets(self) -> None:
        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        int_mod.clear_day_targets(game)
        self.assertIsNone(int_mod.first_nominee_uid(game))
        self.assertIsNone(int_mod.second_nominee_uid(game))
        self.assertFalse(int_mod.night_finished(game))


class InterrogatorShimTests(unittest.TestCase):
    def test_bazpors_narrator_shims(self) -> None:
        from bot.bazpors_narrator import (
            _interrog_day_vote_pool,
            _interrog_nominees_both_alive,
            _mark_interrog_session_done,
            _refresh_interrog_ready_for_day,
        )

        game = _game_with_interrogator()
        int_mod.commit_first_nominee(game, 20)
        int_mod.commit_second_nominee(game, 30)
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        _refresh_interrog_ready_for_day(game)
        self.assertTrue(_interrog_nominees_both_alive(game))
        self.assertEqual(len(_interrog_day_vote_pool(game)), 2)
        _mark_interrog_session_done(game)
        self.assertTrue(int_mod.ability_used(game))


class InterrogatorSemiAutoCallbackTests(unittest.TestCase):
    def test_i1_i2_commit_via_module(self) -> None:
        from bot.bazpors_narrator import NIGHT_ACTIONS, NS_INT1, NS_INT2

        game = _game_with_interrogator()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_INT1
        int_mod.commit_first_nominee(game, 20)
        game.bazpors_night_substep = NS_INT2
        self.assertTrue(int_mod.second_target_valid(game, 30))
        int_mod.commit_second_nominee(game, 30)
        self.assertTrue(int_mod.night_finished(game))


class InterrogatorNoHostPathTests(unittest.TestCase):
    def test_int_pools_match_no_host_keyboard(self) -> None:
        game = _game_with_interrogator(host_mode="no_host")
        int_mod.commit_first_nominee(game, 20)
        self.assertEqual(len(int_mod.int2_pool(game)), 3)
        self.assertNotIn(20, {p.user_id for p in int_mod.int2_pool(game)})


if __name__ == "__main__":
    unittest.main()
