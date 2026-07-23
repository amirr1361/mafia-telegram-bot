"""محاسبه و اعلان پایان شب — مسیر بدون گرداننده."""

from __future__ import annotations

import unittest

from bot.bazpors_detective_inquiry import detective_inquiry_committed_positive
from bot.bazpors_narrator import (
    Role,
    _apply_interrog_cancel_if_nominee_died,
)
from bot.game import GameManager
from bot.models import Game, Player
from bot.no_host_night_resolve import (
    _apply_no_host_night_resolution,
    build_no_host_day_started_broadcast_html,
    build_no_host_night_results_broadcast_html,
    uids_eliminated_during_this_night,
)


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


class NoHostNightResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _base_game(self) -> Game:
        game = Game(
            room_code="99",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "کارآگاه", Role.DETECTIVE),
                -2: _p(-2, 2, "مافیا", Role.MAFIA),
                -3: _p(-3, 3, "شهروند", Role.CITIZEN),
                -4: _p(-4, 4, "اسنایپر", Role.SNIPER),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.no_host_assistant_narrator_active = True
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        return game

    def test_detective_negative_when_shiad_blocked(self) -> None:
        game = self._base_game()
        game.bazpors_detective_blocked = True
        game.actions.detective_check = -3
        game.bazpors_det_ack_positive = True
        self.assertFalse(detective_inquiry_committed_positive(game))

    def test_detective_positive_on_mafia_member(self) -> None:
        game = self._base_game()
        game.mafia_ids = {-2}
        game.actions.detective_check = -2
        game.bazpors_det_ack_positive = True
        self.assertTrue(detective_inquiry_committed_positive(game))

    def test_detective_dm_uses_committed_not_recomputed_after_sniper_mark(self) -> None:
        """نتیجهٔ ثبت‌شدهٔ مثبت بعد از mark اسنایپر نباید منفی شود."""
        game = self._base_game()
        self.gm.add_player(
            game,
            _p(-5, 5, "بابک-شیاد", Role.SHIAD),
        )
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.actions.detective_check = -5
        game.bazpors_det_ack_positive = True
        game.bazpors_sniper_eliminated_uids.add(-5)
        self.assertTrue(detective_inquiry_committed_positive(game))

    def test_results_broadcast_lists_deaths_and_interrog(self) -> None:
        game = self._base_game()
        game.bazpors_alive_at_day_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.players[-3].full_name = "علی-شهروند ساده"
        game.players[-3].is_alive = False
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_interrog_first_uid = -1
        game.bazpors_interrog_second_uid = -2
        html = build_no_host_night_results_broadcast_html(game, self.gm)
        self.assertIn("🕯️", html)
        self.assertIn("نتیجه نهایی شب و روز گذشته", html)
        self.assertIn("در شبی که گذشت", html)
        self.assertIn("علی", html)
        self.assertIn("خداحافظی کردیم", html)
        self.assertIn("امروز بازپرسی داریم", html)
        self.assertIn("کارآگاه", html)
        self.assertIn("مافیا", html)
        self.assertIn(" و ", html)
        self.assertNotIn("در برابر", html)
        self.assertNotIn("میز", html)

    def test_day_started_broadcast_uses_host_day(self) -> None:
        game = self._base_game()
        game.bazpors_narrator_host_day = 2
        self.assertEqual(
            build_no_host_day_started_broadcast_html(game), "<b>روز دوم آغاز شد</b>"
        )

    def test_yaku_convert_before_shot_kill(self) -> None:
        game = self._base_game()
        game.bazpors_yaku_night_success = True
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -3
        snap = dict(game.bazpors_alive_at_night_start)
        _apply_no_host_night_resolution(game, self.gm)
        civ = game.players[-3]
        self.assertTrue(civ.bazpors_converted_by_yakuza)
        self.assertIn(-3, game.bazpors_mafia_recruit_ids)
        self.assertEqual(civ.role, Role.MAFIA_BASIC)
        self.assertEqual(civ.bazpors_original_role, Role.CITIZEN)
        self.assertFalse(civ.is_alive)

    def test_interrog_cancel_when_nominee_died_in_resolution(self) -> None:
        game = self._base_game()
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -2
        game.bazpors_interrog_second_uid = -3
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -3
        snap = dict(game.bazpors_alive_at_night_start)
        _apply_no_host_night_resolution(game, self.gm)
        _apply_interrog_cancel_if_nominee_died(game, snap)
        self.assertTrue(game.bazpors_interrog_cancel_next_day)
        self.assertFalse(game.bazpors_interrog_ready_for_day)

    def test_no_host_mafia_shot_kills_hunter_linked_to_boss_only(self) -> None:
        game = Game(
            room_code="57",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "هانتر", Role.HUNTER),
                -2: _p(-2, 2, "رییس", Role.MAFIA_BOSS),
                -3: _p(-3, 3, "شهروند", Role.CITIZEN),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.no_host_assistant_narrator_active = True
        game.bazpors_hunter_link_uid = -2
        game.bazpors_hunter_report_link_uid = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -1
        _apply_no_host_night_resolution(game, self.gm)
        self.assertFalse(game.players[-1].is_alive)
        self.assertTrue(game.players[-2].is_alive)

    def test_sniper_does_not_die_when_target_converted_by_yaku_this_night(self) -> None:
        game = self._base_game()
        game.bazpors_yaku_night_success = True
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_sniper_night_target_uid = -3
        _apply_no_host_night_resolution(game, self.gm)
        self.assertTrue(game.players[-3].bazpors_converted_by_yakuza)
        self.assertFalse(game.players[-3].is_alive)
        self.assertTrue(game.players[-4].is_alive)

    def test_uids_eliminated_during_this_night_from_snap(self) -> None:
        game = self._base_game()
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.players[-3].is_alive = False
        game.players[-1].is_alive = False
        self.assertEqual(uids_eliminated_during_this_night(game), [-3, -1])

    def test_sniper_hero_line_in_no_host_night_results(self) -> None:
        from tests.test_sniper_night import make_12p_game

        game = make_12p_game()
        game.bazpors_host_mode = "no_host"
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_alive_at_day_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_interrog_first_uid = -6
        game.bazpors_interrog_second_uid = -7
        game.bazpors_sniper_night_target_uid = -2
        _apply_no_host_night_resolution(game, self.gm)
        html = build_no_host_night_results_broadcast_html(game, self.gm)
        self.assertIn("تبریک به این شهر", html)
        self.assertIn("تک‌تیرانداز قهرمان", html)
        self.assertIn("امروز بازپرسی داریم", html)
        hero_pos = html.index("تبریک به این شهر")
        interrog_pos = html.index("امروز بازپرسی داریم")
        self.assertLess(hero_pos, interrog_pos)

    def test_sniper_hero_line_absent_when_doctor_saved_mafia(self) -> None:
        from tests.test_sniper_night import make_12p_game

        game = make_12p_game()
        game.bazpors_host_mode = "no_host"
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_sniper_night_target_uid = -2
        game.bazpors_doctor_save_uids = [-2]
        game.actions.doctor_save = -2
        _apply_no_host_night_resolution(game, self.gm)
        html = build_no_host_night_results_broadcast_html(game, self.gm)
        self.assertNotIn("تبریک به این شهر", html)

    def test_sniper_hero_line_in_semi_auto_night_report(self) -> None:
        from bot.bazpors_narrator import _compose_full_night_report
        from tests.test_sniper_night import make_12p_game

        game = make_12p_game()
        game.bazpors_host_mode = "semi_auto"
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_alive_at_day_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_interrog_first_uid = -6
        game.bazpors_interrog_second_uid = -7
        game.bazpors_sniper_night_target_uid = -2
        _apply_no_host_night_resolution(game, self.gm)
        snap = dict(game.bazpors_alive_at_night_start)
        report = _compose_full_night_report(game, self.gm, snap)
        self.assertIn("پایان شب", report)
        self.assertIn("تبریک به این شهر", report)
        self.assertIn("تک‌تیرانداز قهرمان", report)
        self.assertIn("امروز بازپرسی داریم", report)
        hero_pos = report.index("تبریک به این شهر")
        interrog_pos = report.index("امروز بازپرسی داریم")
        self.assertLess(hero_pos, interrog_pos)


if __name__ == "__main__":
    unittest.main()
