"""یاکوزایی با رویین‌تن — در ۱۳ نفره ناموفق؛ در ۱۲ نفره موفق."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_YAKU_CIV,
    NIGHT_ACTIONS,
    _apply_night_resolution,
    _yaku_civilian_pool,
    _yaku_negotiation_succeeds,
    _yaku_target_allowed,
    build_host_message_and_keyboard,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role


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
        room_code="12",
        host_id=1,
        scenario_name="bazpors_salamat_test",
        players=players,
        max_players=12,
    )
    game.mafia_ids = {-1, -2, -3, -4}
    return game


def make_13p_game() -> Game:
    game = make_12p_game()
    game.room_code = "13"
    game.max_players = 13
    game.players[-13] = _p(-13, 13, "شهروند ۳", Role.CITIZEN)
    return game


class YakuRuintanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_13p_ruintan_in_yaku_pool_but_negotiation_fails(self) -> None:
        game = make_13p_game()
        pool = _yaku_civilian_pool(game)
        ruintan = game.players[-9]
        self.assertIn(ruintan, pool)
        self.assertTrue(_yaku_target_allowed(game, ruintan))
        self.assertFalse(_yaku_negotiation_succeeds(game, ruintan))

    def test_13p_yaku_ui_shows_ruintan_in_list(self) -> None:
        game = make_13p_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_YAKU_CIV
        game.bazpors_narrator_night_count = 1
        game.bazpors_yaku_sac_uid = -4

        body, kb = build_host_message_and_keyboard(game, self.gm)

        self.assertIn("رویین‌تن", body)
        self.assertIn("ناموفق", body)
        self.assertIsNotNone(kb)
        assert kb is not None
        labels = " ".join(btn.text for row in kb.inline_keyboard for btn in row)
        self.assertIn("رویین", labels)

    def test_13p_yc_ruintan_fails_without_mafia_conversion(self) -> None:
        game = make_13p_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_YAKU_CIV
        game.bazpors_yaku_sac_uid = -4
        ruintan_uid = -9

        err = process_narrator_callback(game, self.gm, "yc", ruintan_uid, "")
        self.assertIsNone(err)
        self.assertFalse(game.players[ruintan_uid].bazpors_converted_by_yakuza)
        self.assertNotIn(ruintan_uid, game.bazpors_mafia_recruit_ids)
        self.assertTrue(game.players[-4].is_alive)
        self.assertEqual(game.bazpors_yaku_sac_elim_uid, -4)
        self.assertTrue(game.players[ruintan_uid].is_alive)

    def test_yaku_sac_eliminated_at_night_resolve_not_on_yc(self) -> None:
        game = make_13p_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_YAKU_CIV
        game.bazpors_yaku_sac_uid = -4
        ruintan_uid = -9

        err = process_narrator_callback(game, self.gm, "yc", ruintan_uid, "")
        self.assertIsNone(err)
        self.assertTrue(game.players[-4].is_alive)
        self.assertEqual(game.bazpors_yaku_sac_elim_uid, -4)

        _apply_night_resolution(game, self.gm)
        self.assertFalse(game.players[-4].is_alive)

    def test_12p_yaku_negotiation_succeeds_on_ruintan(self) -> None:
        game = make_12p_game()
        ruintan = game.players[-9]
        self.assertTrue(_yaku_negotiation_succeeds(game, ruintan))


if __name__ == "__main__":
    unittest.main()
