"""گزارش پایان شب ماسون — ناظر / Room-94 style."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import _compose_full_night_report
from bot.game import GameManager
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_mf
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_guardian as ms_gd
from bot.roles import mason_nato as ms_nato
from bot.roles import mason_saboteur as ms_sb
from bot.roles import mason_sniper as ms_sn
from bot.roles.night_state import mafia_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _room94_style_game(gm: GameManager):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=14,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    gm.add_player(game, _p(1, "Erfan", Role.GODFATHER))
    gm.add_player(game, _p(2, "Sab", Role.SABOTEUR))
    gm.add_player(game, _p(3, "Spy", Role.SPY))
    gm.add_player(game, _p(4, "Apache", Role.APACHE))
    gm.add_player(game, _p(5, "Doc", Role.DOCTOR))
    gm.add_player(game, _p(6, "Ruintan", Role.RUINTAN))
    gm.add_player(game, _p(7, "Cowboy", Role.COWBOY))
    gm.add_player(game, _p(8, "Sniper", Role.SNIPER))
    gm.add_player(game, _p(9, "Cmd", Role.COMMANDER))
    gm.add_player(game, _p(10, "Gun", Role.GUNMAN))
    gm.add_player(game, _p(11, "Guard", Role.BODYGUARD))
    gm.add_player(game, _p(12, "Mason", Role.MASON))
    gm.add_player(game, _p(13, "Qasem", Role.DETECTIVE))
    gm.add_player(game, _p(14, "Hasan", Role.TOWN_SIMPLE))
    return game


class MasonNightReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _report_after_night1(self, game) -> str:
        alive_before = {uid: True for uid in game.players}
        game.bazpors_narrator_night_count = 1
        game.bazpors_mafia_shot_registered = True
        apply_mason_night_resolution(game, self.gm)
        return _compose_full_night_report(game, self.gm, alive_before)

    def test_room94_style_includes_all_mason_role_actions(self) -> None:
        game = _room94_style_game(self.gm)
        mafia_night_state(game).commit_shot(6)
        ms_doc.commit_mason_doctor_save(game, 6)
        ms_sn.commit_mason_sniper_night_selection(game, [14])
        ms_cmd.commit_mason_commander_approval(game, [14])
        ms_gn.commit_mason_gunner_target(game, game.players[10], game.players[14])
        ms_gd.commit_mason_guardian_night_pick(game, 5)
        ms_mf.commit_mason_recruit(game, game.players[12], game.players[14])
        game.actions.detective_check = 3
        game.bazpors_det_ack_positive = True
        ms_sb.commit_mason_saboteur_target(game, game.players[2], game.players[14])

        report = self._report_after_night1(game)

        self.assertIn("شات مافیا:", report)
        self.assertIn("Ruintan", report)
        self.assertIn("نجات پزشک:", report)
        self.assertIn("اسنایپر:", report)
        self.assertIn("فرمانده:", report)
        self.assertIn("تفنگدار:", report)
        self.assertIn("محافظ:", report)
        self.assertIn("ماسون:", report)
        self.assertIn("استعلام کارآگاه:", report)
        self.assertIn("Spy", report)
        self.assertIn("خرابکار:", report)
        self.assertNotIn("بازپرس:", report)
        self.assertNotIn("هانتر:", report)

    def test_snapshot_survives_doctor_clear(self) -> None:
        game = _room94_style_game(self.gm)
        ms_doc.commit_mason_doctor_save(game, 6)
        mafia_night_state(game).commit_shot(14)
        apply_mason_night_resolution(game, self.gm)
        self.assertEqual(game.mason_doctor_night_save_uids, [])
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, self.gm, alive_before)
        self.assertIn("نجات پزشک:", report)
        self.assertIn("Ruintan", report)

    def test_nato_line_when_used(self) -> None:
        game = _room94_style_game(self.gm)
        game.mason_nato_tonight = True
        ms_nato.commit_mason_nato_guess(game, Role.SPY, 3)
        alive_before = {uid: True for uid in game.players}
        from bot.mason_night_report import freeze_mason_night_report_snapshot

        freeze_mason_night_report_snapshot(game)
        report = _compose_full_night_report(game, self.gm, alive_before)
        self.assertIn("ناتو:", report)
        self.assertIn("Spy", report)

    def test_natasha_line_when_present(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(1, "Nat", Role.NATASHA))
        gm.add_player(game, _p(2, "Hasan", Role.TOWN_SIMPLE))
        from bot.roles import mason_natasha as ms_nat

        ms_nat.commit_mason_natasha_target(game, game.players[1], game.players[2], confirmed=True)
        from bot.mason_night_report import freeze_mason_night_report_snapshot

        freeze_mason_night_report_snapshot(game)
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertIn("ناتاشا:", report)
        self.assertIn("Hasan", report)

    def test_natasha_line_uses_name_role_format(self) -> None:
        from bot.game import scenario_role_label_fa
        from bot.mason_synthetic_names import MASON_SYNTHETIC_NAME_SEP

        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(1, "Nat", Role.NATASHA))
        target = _p(2, "Qasem", Role.COMMANDER)
        target.full_name = (
            f"قاسم{MASON_SYNTHETIC_NAME_SEP}{scenario_role_label_fa(game, Role.COMMANDER)}"
        )
        gm.add_player(game, target)
        from bot.roles import mason_natasha as ms_nat

        ms_nat.commit_mason_natasha_target(game, game.players[1], target, confirmed=True)
        from bot.mason_night_report import freeze_mason_night_report_snapshot

        freeze_mason_night_report_snapshot(game)
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertIn("ناتاشا:", report)
        self.assertIn("قاسم - فرمانده", report)

    def test_doctor_saves_on_one_line_with_fa_comma(self) -> None:
        from bot.game import scenario_role_label_fa
        from bot.mason_synthetic_names import MASON_SYNTHETIC_NAME_SEP

        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(5, "Doc", Role.DOCTOR))
        p1 = _p(10, "Qasem", Role.COMMANDER)
        p1.full_name = (
            f"قاسم{MASON_SYNTHETIC_NAME_SEP}{scenario_role_label_fa(game, Role.COMMANDER)}"
        )
        p2 = _p(11, "Amir", Role.SPY)
        p2.full_name = (
            f"امیر{MASON_SYNTHETIC_NAME_SEP}{scenario_role_label_fa(game, Role.SPY)}"
        )
        p3 = _p(12, "Erfan", Role.GODFATHER)
        p3.full_name = (
            f"عرفان{MASON_SYNTHETIC_NAME_SEP}{scenario_role_label_fa(game, Role.GODFATHER)}"
        )
        gm.add_player(game, p1)
        gm.add_player(game, p2)
        gm.add_player(game, p3)
        for i in range(8):
            gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
        ms_doc.commit_mason_doctor_save(game, 10)
        ms_doc.commit_mason_doctor_save(game, 11)
        ms_doc.commit_mason_doctor_save(game, 12)
        from bot.mason_night_report import freeze_mason_night_report_snapshot

        freeze_mason_night_report_snapshot(game)
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertIn(
            "💉 نجات پزشک: قاسم - فرمانده، امیر - جاسوس، عرفان - گادفادر",
            report,
        )
        self.assertNotIn("نجات پزشک:\n-", report)

    def test_doctor_no_saves_shows_none_line(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(5, "Doc", Role.DOCTOR))
        from bot.mason_night_report import freeze_mason_night_report_snapshot

        freeze_mason_night_report_snapshot(game)
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertIn("💉 نجات پزشک: انتخابی نداشت", report)

    def test_priest_line_when_present(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(1, "Pr", Role.PRIEST))
        gm.add_player(game, _p(2, "Hasan", Role.TOWN_SIMPLE))
        from bot.roles import mason_priest as ms_pr

        ms_pr.commit_mason_priest_target(game, game.players[1], game.players[2], confirmed=True)
        from bot.mason_night_report import freeze_mason_night_report_snapshot

        freeze_mason_night_report_snapshot(game)
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertIn("⛪ کشیش:", report)
        self.assertIn("Hasan", report)

    def test_natasha_silence_outcome_when_not_blocked(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(1, "Nat", Role.NATASHA))
        gm.add_player(game, _p(2, "Hasan", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(8, "Sniper", Role.SNIPER))
        from bot.roles import mason_natasha as ms_nat

        ms_nat.commit_mason_natasha_target(game, game.players[1], game.players[2], confirmed=True)
        game.players[8].is_alive = False
        alive_before = {uid: True for uid in game.players}
        alive_before[8] = True
        apply_mason_night_resolution(game, gm)
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertIn("در شبی که گذشت، با", report)
        self.assertIn("Sniper", report)
        self.assertIn("به دستور ناتاشا، Hasan باید سکوت کند", report)

    def test_natasha_silence_outcome_hidden_when_priest_blocks(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=18,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm = self.gm
        gm.add_player(game, _p(1, "Nat", Role.NATASHA))
        gm.add_player(game, _p(2, "Pr", Role.PRIEST))
        gm.add_player(game, _p(3, "Hasan", Role.TOWN_SIMPLE))
        from bot.roles import mason_natasha as ms_nat
        from bot.roles import mason_priest as ms_pr

        ms_nat.commit_mason_natasha_target(game, game.players[1], game.players[3], confirmed=True)
        ms_pr.commit_mason_priest_target(game, game.players[2], game.players[3], confirmed=True)
        alive_before = {uid: True for uid in game.players}
        apply_mason_night_resolution(game, gm)
        report = _compose_full_night_report(game, gm, alive_before)
        self.assertNotIn("به دستور ناتاشا", report)
        self.assertIn("ناتاشا:", report)
        self.assertIn("Hasan", report)
        self.assertIn("⛪ کشیش:", report)

    def test_mozakere_report_has_no_mason_natasha_silence_line(self) -> None:
        from tests.test_mozakere_doctor_night_ui import _mozakere_no_host

        game = _mozakere_no_host(self.gm, night=1)
        self.gm.add_player(game, _p(1, "Nat", Role.NATASHA))
        self.gm.add_player(game, _p(2, "Hasan", Role.CITIZEN))
        alive_before = {uid: True for uid in game.players}
        report = _compose_full_night_report(game, self.gm, alive_before)
        self.assertNotIn("به دستور ناتاشا", report)

    def test_bazpors_report_unchanged(self) -> None:
        from tests.test_night_report_format import make_12p_game

        game = make_12p_game()
        alive_before = {uid: True for uid in game.players}
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -11
        report = _compose_full_night_report(game, self.gm, alive_before)
        self.assertIn("شات مافیا:", report)
        self.assertNotIn("تفنگدار:", report)
