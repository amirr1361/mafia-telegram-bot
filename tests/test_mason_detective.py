"""تست کارآگاه — سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Phase, Player, Role
from bot.roles import detective as det
from bot.roles import mason_detective as ms_det


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(*, room_code: str = "MS01") -> Game:
    g = Game(
        room_code=room_code,
        host_id=1,
        scenario_name="masoon",
        phase=Phase.NIGHT,
        players={},
    )
    g.bazpors_host_mode = "no_host"
    g.no_host_assistant_narrator_active = True
    g.bot_assistant_user_id = 999
    g.bazpors_narrator_step = "night_actions"
    g.bazpors_night_substep = "ns_det"
    g.bazpors_narrator_night_count = 1
    return g


def _bazpors_game(*, room_code: str = "BZ01") -> Game:
    g = Game(
        room_code=room_code,
        host_id=2,
        scenario_name="bazpors",
        phase=Phase.NIGHT,
        players={},
    )
    g.bazpors_host_mode = "no_host"
    g.no_host_assistant_narrator_active = True
    return g


class MasonDetectivePanelTests(unittest.TestCase):
    def test_panel_excludes_detective(self) -> None:
        game = _mason_game()
        det_player = _p(10, "Det", Role.DETECTIVE)
        other = _p(20, "Hasan", Role.TOWN_SIMPLE)
        game.players = {10: det_player, 20: other}
        names = ms_det.mason_detective_panel_button_names(game)
        self.assertEqual(names, ["Hasan"])
        self.assertNotIn("Det", names)

    def test_panel_includes_all_other_alive(self) -> None:
        game = _mason_game()
        det_player = _p(10, "Det", Role.DETECTIVE)
        a = _p(20, "A", Role.DOCTOR)
        b = _p(30, "B", Role.SABOTEUR)
        game.players = {10: det_player, 20: a, 30: b}
        names = set(ms_det.mason_detective_panel_button_names(game))
        self.assertEqual(names, {"A", "B"})


class MasonDetectivePickTests(unittest.TestCase):
    def test_can_select_and_confirm_target(self) -> None:
        game = _mason_game()
        det_player = _p(10, "Det", Role.DETECTIVE)
        target = _p(20, "Hasan", Role.TOWN_SIMPLE)
        game.players = {10: det_player, 20: target}
        result = det.commit_pick(game, 20)
        self.assertFalse(result.is_positive)
        self.assertEqual(game.actions.detective_check, 20)
        self.assertTrue(game.no_host_detective_pick_confirmed is False)
        self.assertEqual(det.committed_target_uid(game), 20)


class MasonDetectiveResultTests(unittest.TestCase):
    def _game_with_target(self, role: Role) -> tuple[Game, int]:
        game = _mason_game()
        game.players[10] = _p(10, "Det", Role.DETECTIVE)
        uid = 20
        game.players[uid] = _p(uid, "T", role)
        return game, uid

    def test_positive_saboteur(self) -> None:
        game, uid = self._game_with_target(Role.SABOTEUR)
        self.assertTrue(det.evaluate_inquiry(game, uid).is_positive)

    def test_positive_spy(self) -> None:
        game, uid = self._game_with_target(Role.SPY)
        self.assertTrue(det.evaluate_inquiry(game, uid).is_positive)

    def test_positive_apache(self) -> None:
        game, uid = self._game_with_target(Role.APACHE)
        self.assertTrue(det.evaluate_inquiry(game, uid).is_positive)

    def test_positive_nato(self) -> None:
        game, uid = self._game_with_target(Role.NATO)
        self.assertTrue(det.evaluate_inquiry(game, uid).is_positive)

    def test_positive_natasha(self) -> None:
        game, uid = self._game_with_target(Role.NATASHA)
        self.assertTrue(det.evaluate_inquiry(game, uid).is_positive)

    def test_positive_simple_mafia(self) -> None:
        game, uid = self._game_with_target(Role.MAFIA_BASIC)
        self.assertTrue(det.evaluate_inquiry(game, uid).is_positive)

    def test_negative_godfather(self) -> None:
        game, uid = self._game_with_target(Role.GODFATHER)
        result = det.evaluate_inquiry(game, uid)
        self.assertFalse(result.is_positive)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)

    def test_negative_town_roles(self) -> None:
        for role in (Role.DOCTOR, Role.TOWN_SIMPLE, Role.MASON, Role.PRIEST):
            with self.subTest(role=role):
                game, uid = self._game_with_target(role)
                result = det.evaluate_inquiry(game, uid)
                self.assertFalse(result.is_positive)
                self.assertEqual(
                    result.kind, det.DetectiveInquiryKind.NEGATIVE_TOWN
                )


class MasonDetectiveIsolationTests(unittest.TestCase):
    def test_state_isolated_by_room(self) -> None:
        mason = _mason_game(room_code="M1")
        mason.players[10] = _p(10, "Det", Role.DETECTIVE)
        mason.players[20] = _p(20, "Maf", Role.SABOTEUR)
        mason.players[30] = _p(30, "Town", Role.TOWN_SIMPLE)

        baz = _bazpors_game(room_code="B1")
        baz.players[10] = _p(10, "Det", Role.DETECTIVE)
        baz.players[20] = _p(20, "Boss", Role.MAFIA_BOSS)
        baz.players[30] = _p(30, "Cit", Role.CITIZEN)

        det.commit_pick(mason, 20)
        det.commit_pick(baz, 30)

        self.assertEqual(mason.actions.detective_check, 20)
        self.assertTrue(det.committed_positive(mason))
        self.assertEqual(baz.actions.detective_check, 30)
        self.assertFalse(det.committed_positive(baz))

    def test_concurrent_rooms_do_not_overwrite(self) -> None:
        mason = _mason_game(room_code="M2")
        mason.players[10] = _p(10, "Det", Role.DETECTIVE)
        mason.players[40] = _p(40, "GF", Role.GODFATHER)

        moz = Game(
            room_code="Z1",
            host_id=3,
            scenario_name="mozakere",
            phase=Phase.NIGHT,
            players={
                10: _p(10, "Det", Role.DETECTIVE),
                50: _p(50, "Neg", Role.MAFIA_NEGOTIATOR),
            },
        )
        moz.bazpors_host_mode = "no_host"

        det.commit_pick(mason, 40)
        det.commit_pick(moz, 50)

        self.assertFalse(det.committed_positive(mason))
        self.assertTrue(det.committed_positive(moz))


class BazporsMozakereRegressionTests(unittest.TestCase):
    def test_bazpors_pool_still_includes_detective(self) -> None:
        game = _bazpors_game()
        game.players[10] = _p(10, "Det", Role.DETECTIVE)
        game.players[20] = _p(20, "Cit", Role.CITIZEN)
        pool_ids = {p.user_id for p in det.investigation_pool(game)}
        self.assertEqual(pool_ids, {10, 20})

    def test_bazpors_boss_still_negative(self) -> None:
        game = _bazpors_game()
        game.players[20] = _p(20, "Boss", Role.MAFIA_BOSS)
        result = det.evaluate_inquiry(game, 20)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)

    def test_mozakere_mafia_still_positive(self) -> None:
        game = Game(
            room_code="MZ1",
            host_id=1,
            scenario_name="mozakere",
            players={
                10: _p(10, "Det", Role.DETECTIVE),
                21: _p(21, "Neg", Role.MAFIA_NEGOTIATOR),
            },
        )
        result = det.evaluate_inquiry(game, 21)
        self.assertTrue(result.is_positive)

    def test_mozakere_boss_still_negative(self) -> None:
        game = Game(
            room_code="MZ2",
            host_id=1,
            scenario_name="mozakere",
            players={20: _p(20, "Boss", Role.MAFIA_BOSS)},
        )
        result = det.evaluate_inquiry(game, 20)
        self.assertEqual(result.kind, det.DetectiveInquiryKind.NEGATIVE_BOSS)
