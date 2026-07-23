"""قالب گزارش خلاصهٔ شب بازپرس."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    _NIGHT_REPORT_HDR,
    _compose_full_night_report,
    _enter_night_from_day_end,
)
from bot.no_host_night_resolve import build_no_host_night_results_broadcast_html
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


class NightReportFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_report_concise_lines_only_registered_actions(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_hunter_report_link_uid = -2
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -11
        game.bazpors_shiad_target_uid = -7
        game.actions.detective_check = -2
        game.bazpors_det_ack_positive = True
        game.actions.doctor_save = -9
        game.bazpors_interrog_night_finished = True
        game.bazpors_interrog_first_uid = -9
        game.bazpors_interrog_second_uid = -10
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_alive_at_day_start = dict(alive_before)
        game.players[-11].is_alive = False
        alive_before[-11] = False
        game.players[-12].is_alive = False
        game.players[-5].is_alive = False
        alive_before[-5] = False

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("شات مافیا:", report)
        self.assertIn("استعلام کارآگاه:", report)
        self.assertIn("نجات پزشک:", report)
        self.assertIn("بازپرس:", report)
        self.assertNotIn("انتخاب نکرد", report)
        self.assertNotIn("از بازی خارج شده بود", report)
        self.assertNotIn("اخراج انضباطی", report)
        self.assertNotIn("قبلاً یک‌بار", report)
        self.assertNotIn("انتخاب هانتر ⮜", report)

    def test_synthetic_short_name_in_report(self) -> None:
        game = Game(
            room_code="58",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "هاکان-مافیا ساده", Role.MAFIA_BASIC),
                -2: _p(-2, 2, "رهنما-اسنایپر", Role.SNIPER, alive=False),
            },
            max_players=12,
            bazpors_narrator_night_count=2,
        )
        game.mafia_ids = {-1}
        alive_before = {uid: True for uid in game.players}
        game.bazpors_yakuzai_used = True
        game.bazpors_yaku_sac_elim_uid = -1
        game.bazpors_yaku_night_civilian_uid = -2
        game.bazpors_yaku_night_success = False
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -2

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("شات مافیا: رهنما-اسنایپر", report)
        self.assertIn("یاکوزایی ناموفق", report)
        self.assertIn("رهنما-اسنایپر", report)
        self.assertIn("مافیای فدا شده: هاکان-مافیا ساده", report)
        self.assertNotIn("فدای یاکوزا:", report)

    def test_nato_failed_in_full_night_report(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_nato_action_registered = True
        game.bazpors_nato_used = True
        game.bazpors_nato_success = False
        game.bazpors_nato_guess_role = Role.DETECTIVE.value
        game.bazpors_nato_guess_target_uid = -7

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("ناتویی ناموفق", report)
        self.assertIn("کارآگاه", report)

    def test_nato_failed_minimal_line_when_no_details(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_nato_action_registered = True
        game.bazpors_nato_success = False

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("⚪ ناتویی ناموفق", report)

    def test_yaku_success_in_full_night_report(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_yakuzai_used = True
        game.bazpors_yaku_sac_elim_uid = -1
        game.bazpors_yaku_night_civilian_uid = -3
        game.bazpors_yaku_night_success = True

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("یاکوزایی موفق", report)
        self.assertIn("مافیای فدا شده:", report)

    def test_hunter_only_when_link_registered(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_hunter_report_link_uid = -2

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("🏹 هانتر: ناتو", report)
        self.assertNotIn("گزارش هانتر", report)
        self.assertNotIn("زنجیرهٔ هانتر", report)

    def test_discipline_in_outcome_not_in_full_report(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_alive_at_day_start = dict(alive_before)
        game.bazpors_night_discipline_kick_uid = -1
        game.players[-1].is_alive = False
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -10
        game.players[-10].is_alive = False

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("نتیجه نهایی", report)
        self.assertIn("در شبی که گذشت، با", report)
        self.assertIn("تک‌تیرانداز", report)
        self.assertIn("اخراج انضباطی:", report)
        self.assertIn("رییس مافیا", report)
        hdr_idx = report.index(_NIGHT_REPORT_HDR)
        self.assertNotIn("🚪", report[hdr_idx:])
        self.assertNotIn("اخراج انضباطی", report[hdr_idx:])

    def test_day_farewell_without_day_start_snapshot(self) -> None:
        """no_host روز اول: خروج قبل از شب بدون اسنپ‌شات روز."""
        game = make_12p_game()
        game.bazpors_alive_at_day_start = None
        alive_before = {uid: True for uid in game.players}
        game.players[-11].is_alive = False
        alive_before[-11] = False

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("در روز قبل که با", report)
        self.assertIn("شهروند ۱", report)
        self.assertNotIn("در روز قبل که با کسی خداحافظی نکردیم", report)

    def test_day_vs_night_farewell_uses_night_start_snapshot(self) -> None:
        """اتاق ۳۰: یک نفر روز، دو نفر شب — نه همه در بند روز."""
        game = make_12p_game()
        game.bazpors_host_mode = "no_host"
        game.bazpors_alive_at_day_start = {uid: True for uid in game.players}
        game.players[-11].is_alive = False
        game.bazpors_alive_at_night_start = {
            uid: p.is_alive for uid, p in game.players.items()
        }
        game.players[-10].is_alive = False
        game.players[-5].is_alive = False
        game.bazpors_interrog_ready_for_day = True
        game.bazpors_interrog_first_uid = -1
        game.bazpors_interrog_second_uid = -6

        report = build_no_host_night_results_broadcast_html(game, self.gm)

        self.assertIn("در روز قبل که با", report)
        self.assertIn("شهروند ۱", report)
        self.assertNotIn("تک‌تیرانداز", report.split("در روز قبل")[1].split("در شبی")[0])
        self.assertIn("در شبی که گذشت", report)
        self.assertIn("تک‌تیرانداز", report)
        self.assertIn("هانتر", report)

    def test_enter_night_from_day_end_arms_night_start_for_no_host(self) -> None:
        game = make_12p_game()
        game.scenario_name = "bazpors"
        game.bazpors_host_mode = "no_host"
        game.bazpors_narrator_night_count = 0
        game.players[-11].is_alive = False

        _enter_night_from_day_end(game)

        self.assertIsNotNone(game.bazpors_alive_at_night_start)
        self.assertFalse(game.bazpors_alive_at_night_start[-11])
        self.assertTrue(game.bazpors_alive_at_night_start[-10])

    def test_hunter_chain_line_in_night_report(self) -> None:
        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_hunter_report_link_uid = -2
        game.players[-5].is_alive = False
        game.players[-2].is_alive = False

        report = _compose_full_night_report(game, self.gm, alive_before)

        self.assertIn("🏹 هانتر - ناتو (به همراه هانتر کشته شد)", report)
        self.assertNotIn("گزارش هانتر", report)
        self.assertNotIn("زنجیرهٔ هانتر", report)


if __name__ == "__main__":
    unittest.main()
