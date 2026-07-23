"""تست منطق مشترک کارآگاه — bot/roles/detective.py (فاز A)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_DET,
    NIGHT_ACTIONS,
    process_narrator_callback,
)
from bot.game import GameManager, apply_bazpors_yakuzai_recruit
from bot.models import Game, Player, Role
from bot.no_host_detective_night import _commit_detective_pick, _void_no_host_detective_night_pick
from bot.roles import detective as det
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


def _no_host_game(*, with_detective: bool = True) -> Game:
    players: dict[int, Player] = {
        -1: _p(-1, 1, "مافیا", Role.MAFIA),
        -2: _p(-2, 2, "شهروند", Role.CITIZEN),
    }
    if with_detective:
        players[-3] = _p(-3, 3, "کارآگاه", Role.DETECTIVE)
    game = Game(
        room_code="DET1",
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


class DetectiveModuleCoreTests(unittest.TestCase):
    def test_investigation_pool_all_alive(self) -> None:
        game = _no_host_game()
        pool_ids = {p.user_id for p in det.investigation_pool(game)}
        self.assertEqual(pool_ids, {-1, -2, -3})

    def test_evaluate_boss_negative(self) -> None:
        game = make_semi_auto_game()
        game.players[-1].role = Role.MAFIA_BOSS
        result = det.evaluate_inquiry(game, -1)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)
        self.assertFalse(result.is_positive)

    def test_evaluate_mafia_positive(self) -> None:
        game = make_semi_auto_game()
        game.players[-4].role = Role.MAFIA_BASIC
        result = det.evaluate_inquiry(game, -4)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.POSITIVE)
        self.assertTrue(result.is_positive)

    def test_evaluate_citizen_negative(self) -> None:
        game = make_semi_auto_game()
        result = det.evaluate_inquiry(game, -3)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_TOWN)

    def test_evaluate_shiad_blocked_negative(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_detective_blocked = True
        result = det.evaluate_inquiry(game, -3)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_SHIAD)

    def test_evaluate_yaku_recruit_positive(self) -> None:
        game = _no_host_game(with_detective=False)
        game.players[-2] = _p(-2, 2, "تازه", Role.CITIZEN)
        apply_bazpors_yakuzai_recruit(game, game.players[-2])
        result = det.evaluate_inquiry(game, -2)
        self.assertTrue(result.is_positive)

    def test_commit_pick_sets_committed_state(self) -> None:
        game = _no_host_game()
        result = det.commit_pick(game, -1)
        self.assertTrue(result.is_positive)
        self.assertEqual(game.actions.detective_check, -1)
        self.assertTrue(game.bazpors_det_ack_positive)
        self.assertEqual(det.committed_target_uid(game), -1)

    def test_void_pick_clears_state(self) -> None:
        game = _no_host_game()
        det.commit_pick(game, -2)
        det.void_pick(game)
        self.assertIsNone(det.committed_target_uid(game))
        self.assertFalse(game.bazpors_det_ack_positive)

    def test_mark_no_inquiry(self) -> None:
        game = _no_host_game()
        det.mark_no_inquiry(game)
        self.assertTrue(game.bazpors_det_no_inquiry)
        self.assertIsNone(det.load_result(game))

    def test_load_result_uses_committed_not_recomputed(self) -> None:
        game = _no_host_game()
        det.commit_pick(game, -2)
        game.players[-2].role = Role.MAFIA_BASIC
        game.bazpors_mafia_recruit_ids.add(-2)
        loaded = det.load_result(game)
        assert loaded is not None
        self.assertEqual(loaded.kind, det.DetectiveInquiryKind.NEGATIVE_TOWN)
        self.assertFalse(loaded.is_positive)

    def test_sniper_mark_does_not_change_committed_positive(self) -> None:
        game = _no_host_game()
        game.players[-1].role = Role.MAFIA_BASIC
        det.commit_pick(game, -1)
        game.bazpors_sniper_eliminated_uids.add(-1)
        self.assertTrue(det.committed_positive(game))

    def test_find_alive_detective_none_when_dead(self) -> None:
        game = _no_host_game()
        game.players[-3].is_alive = False
        self.assertIsNone(det.find_alive_detective(game))

    def test_block_inquiry_by_shiad(self) -> None:
        game = _no_host_game()
        det.commit_pick(game, -2)
        det.block_inquiry_by_shiad(game)
        self.assertTrue(game.bazpors_detective_blocked)
        self.assertFalse(game.bazpors_det_ack_positive)


class DetectiveSemiAutoPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_semi_auto_dp_commits_inquiry(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DET
        err = process_narrator_callback(game, self.gm, "dp", -4, "")
        self.assertIsNone(err)
        self.assertEqual(game.actions.detective_check, -4)
        self.assertFalse(game.bazpors_det_ack_positive)

    def test_semi_auto_dx_marks_no_inquiry(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DET
        err = process_narrator_callback(game, self.gm, "dx", 0, "")
        self.assertIsNone(err)
        self.assertTrue(game.bazpors_det_no_inquiry)

    def test_semi_auto_dp_mafia_positive(self) -> None:
        game = make_semi_auto_game()
        game.players[-4].role = Role.MAFIA_BASIC
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DET
        process_narrator_callback(game, self.gm, "dp", -4, "")
        self.assertTrue(game.bazpors_det_ack_positive)


class DetectiveNoHostPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_no_host_commit_via_shared_module(self) -> None:
        game = _no_host_game()
        _commit_detective_pick(game, self.gm, -1)
        self.assertEqual(det.committed_target_uid(game), -1)
        self.assertTrue(det.committed_positive(game))

    def test_no_host_void_clears_pick(self) -> None:
        game = _no_host_game()
        _commit_detective_pick(game, self.gm, -2)
        _void_no_host_detective_night_pick(game)
        self.assertIsNone(det.committed_target_uid(game))

    def test_no_host_pool_matches_module(self) -> None:
        game = _no_host_game()
        gm = GameManager()
        gm.add_player(
            game,
            Player(user_id=40, full_name="X", username=None, role=Role.CITIZEN),
        )
        pool_ids = {p.user_id for p in det.investigation_pool(game)}
        self.assertIn(40, pool_ids)


class DetectiveNightSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_semi_auto_full_detective_path(self) -> None:
        game = make_semi_auto_game()
        game.players[-4].role = Role.MAFIA_BASIC
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DET
        process_narrator_callback(game, self.gm, "dp", -4, "")
        self.assertTrue(det.committed_positive(game))
        loaded = det.load_result(game)
        assert loaded is not None
        self.assertEqual(loaded.target_uid, -4)

    def test_no_host_full_detective_path(self) -> None:
        game = _no_host_game()
        game.players[-1].role = Role.MAFIA_BOSS
        _commit_detective_pick(game, self.gm, -1)
        loaded = det.load_result(game)
        assert loaded is not None
        self.assertEqual(loaded.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)


if __name__ == "__main__":
    unittest.main()
