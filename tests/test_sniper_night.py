"""مرحلهٔ تک‌تیرانداز — ترکیب ۱۲/۱۳ نفرهٔ بازپرس."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_SNIPER,
    NIGHT_ACTIONS,
    _apply_night_resolution,
    _apply_sniper_night_resolution,
    _bazpors_sniper_nights_enabled,
    _doctor_save_uid_set,
    build_host_message_and_keyboard,
    process_narrator_callback,
)
from bot.no_host_night_resolve import _apply_no_host_night_resolution
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


class SniperNightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_sniper_enabled_for_12_player_bazpors_test(self) -> None:
        game = make_12p_game()
        self.assertTrue(_bazpors_sniper_nights_enabled(game))

    def test_sniper_step_shows_alive_player_list(self) -> None:
        game = make_12p_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_SNIPER
        game.bazpors_narrator_night_count = 1

        body, kb = build_host_message_and_keyboard(game, self.gm)

        self.assertIn("ثبت انتخاب تک‌تیرانداز", body)
        self.assertIn("قوانین", body)
        self.assertIn("شلیک نکرد", body)
        self.assertIsNotNone(kb)
        assert kb is not None
        labels = " ".join(btn.text for row in kb.inline_keyboard for btn in row)
        self.assertIn("ناتو", labels)
        self.assertIn("شهروند", labels)

    def test_sniper_shoots_town_without_doctor_save(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -11
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(game.players[-10].is_alive)
        self.assertTrue(game.players[-11].is_alive)

    def test_sniper_shoots_town_with_doctor_save(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -11
        game.bazpors_doctor_save_uids = [-11]
        game.actions.doctor_save = -11
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(game.players[-10].is_alive)
        self.assertTrue(game.players[-11].is_alive)

    def test_boss_shot_eliminates_nobody(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -1
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertTrue(game.players[-1].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_mafia_shot_without_doctor_save_eliminates_target(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -2
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)
        self.assertIn(-2, game.bazpors_sniper_eliminated_uids)

    def test_mafia_shot_with_doctor_save_spares_target_and_sniper(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertTrue(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_shot_is_consumed_even_if_target_already_dead(self) -> None:
        game = make_12p_game()
        game.players[-2].is_alive = False
        game.bazpors_sniper_night_target_uid = -2
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)

    def test_wrong_shot_on_dead_civilian_eliminates_sniper(self) -> None:
        game = make_12p_game()
        game.players[-11].is_alive = False
        game.bazpors_sniper_night_target_uid = -11
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(game.players[-10].is_alive)
        self.assertFalse(game.players[-11].is_alive)

    def test_converted_target_counts_as_mafia_for_sniper_resolution(self) -> None:
        game = make_12p_game()
        game.players[-11].bazpors_converted_by_yakuza = True
        game.bazpors_mafia_recruit_ids.add(-11)
        game.bazpors_sniper_night_target_uid = -11
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(game.players[-11].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_converted_mafia_spared_when_doctor_saved(self) -> None:
        game = make_12p_game()
        game.players[-11].bazpors_converted_by_yakuza = True
        game.bazpors_mafia_recruit_ids.add(-11)
        game.bazpors_sniper_night_target_uid = -11
        game.bazpors_doctor_save_uids = [-11]
        game.actions.doctor_save = -11
        _apply_sniper_night_resolution(game, self.gm)
        self.assertTrue(game.players[-11].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_sniper_killed_mafia_excluded_from_win_after_yaku_recruit(self) -> None:
        from bot.bazpors_narrator import _alive_faction_counts, mafia_faction_wins
        from bot.game import (
            apply_bazpors_yakuzai_recruit,
            bazpors_counts_as_alive_mafia_for_win,
            mark_bazpors_eliminated_by_sniper,
        )

        game = make_12p_game()
        shiad_uid = -3
        game.players[shiad_uid].is_alive = False
        mark_bazpors_eliminated_by_sniper(game, shiad_uid)
        apply_bazpors_yakuzai_recruit(game, game.players[-11])
        self.assertFalse(
            bazpors_counts_as_alive_mafia_for_win(game, game.players[shiad_uid])
        )
        self.assertTrue(
            bazpors_counts_as_alive_mafia_for_win(game, game.players[-11])
        )
        self.assertNotIn(shiad_uid, game.mafia_ids)
        self.assertNotIn(shiad_uid, game.bazpors_mafia_recruit_ids)
        _, mafia_n, citizen_n = _alive_faction_counts(game, self.gm)
        self.assertEqual(mafia_n, 4)
        self.assertFalse(mafia_faction_wins(game, self.gm))

    def test_sn_pick_advances_to_discipline(self) -> None:
        game = make_12p_game()
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_SNIPER

        err = process_narrator_callback(game, self.gm, "sn_pick", -2, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_sniper_night_target_uid, -2)
        self.assertEqual(game.bazpors_night_substep, "ns_discipline_ask")

    def test_sniper_shot_applies_when_mafia_shot_targets_sniper(self) -> None:
        """اتاق ۱۰ — اول شات مافیا روی اسنایپر، بعد شلیک درست روی ناتو."""
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -10
        _apply_night_resolution(game, self.gm)
        self.assertTrue(game.bazpors_sniper_shot_used)
        self.assertFalse(game.players[-2].is_alive)
        self.assertFalse(game.players[-10].is_alive)

    def test_full_night_mafia_spared_when_doctor_saved_sniper_target(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4
        _apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)

    def test_doctor_save_still_applies_for_sniper_mafia_target(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        self.assertEqual(_doctor_save_uid_set(game), {-2})

    def test_mafia_shot_blocked_when_doctor_saved_sniper_target(self) -> None:
        game = make_12p_game()
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -2
        _apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)

    def test_no_host_mafia_spared_when_doctor_saved(self) -> None:
        game = make_12p_game()
        game.bazpors_host_mode = "no_host"
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -4
        _apply_no_host_night_resolution(game, self.gm)
        self.assertTrue(game.players[-2].is_alive)
        self.assertTrue(game.players[-10].is_alive)


if __name__ == "__main__":
    unittest.main()
