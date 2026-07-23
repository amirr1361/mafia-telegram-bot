"""اعلام بازیکنان دفاعیه — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    begin_no_host_day1_defense_pick,
    record_day_vote_participants,
    set_day_vote_defender_uids,
)
from bot.game import GameManager
from bot.main import build_no_host_day1_defense_outcome_html
from bot.mason_day_defense import build_mason_defense_candidates_announcement_html
from bot.models import Player, Role


def _p(uid: int, name: str, role: Role | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role or Role.TOWN_SIMPLE,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 10
    return game


def _bazpors_game(gm: GameManager):
    game = gm.create_game(
        host_id=1,
        scenario_name="bazpors",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 10
    return game


class MasonDefenseAnnouncementTests(unittest.TestCase):
    def test_first_time_defense_candidate(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "امیر"))
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("🗳️ بازیکنان انتخاب‌شده برای دفاعیه:", html)
        self.assertIn("1. امیر | سابقه رأی‌گیری: ۰ بار", html)

    def test_repeated_defense_candidate(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "حسن"))
        game.bazpors_day_vote_participations[20] = 1
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("1. حسن | سابقه رأی‌گیری: ۱ بار", html)

    def test_multiple_candidates_numbered(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "امیر"))
        gm.add_player(game, _p(30, "حسن"))
        gm.add_player(game, _p(40, "رضا"))
        game.bazpors_day_vote_participations[30] = 1
        game.bazpors_day_vote_participations[40] = 2
        set_day_vote_defender_uids(game, {20, 30, 40})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("1. امیر | سابقه رأی‌گیری: ۰ بار", html)
        self.assertIn("2. حسن | سابقه رأی‌گیری: ۱ بار", html)
        self.assertIn("3. رضا | سابقه رأی‌گیری: ۲ بار", html)

    def test_history_before_increment_on_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "امیر"))
        game.bazpors_day_vote_participations[20] = 1
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("۱ بار", html)
        record_day_vote_participants(game, {20})
        self.assertEqual(game.bazpors_day_vote_participations[20], 2)

    def test_main_builder_uses_mason_format(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "امیر"))
        set_day_vote_defender_uids(game, {20})
        html = build_no_host_day1_defense_outcome_html(game)
        self.assertIn("بازیکنان انتخاب‌شده برای دفاعیه", html)
        self.assertNotIn("سابقه حضور در رأی‌گیری‌های قبلی", html)

    def test_four_candidates(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        for uid, name in ((20, "A"), (30, "B"), (40, "C"), (50, "D")):
            gm.add_player(game, _p(uid, name))
        set_day_vote_defender_uids(game, {20, 30, 40, 50})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("4. D | سابقه رأی‌گیری: ۰ بار", html)


class MasonDefenseHistoryIncrementTests(unittest.TestCase):
    def test_day1_no_exit_increments_history_once(self) -> None:
        from bot.bazpors_narrator import (
            day_vote_participation_count,
            no_host_day1_no_exit_enter_night,
        )

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "Erfan"))
        set_day_vote_defender_uids(game, {20})
        no_host_day1_no_exit_enter_night(game)
        self.assertEqual(day_vote_participation_count(game, 20), 1)

    def test_day2_defense_announcement_shows_prior_count_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "Erfan"))
        game.bazpors_narrator_host_day = 2
        game.bazpors_day_vote_participations[20] = 1
        set_day_vote_defender_uids(game, {20})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("1. Erfan | سابقه رأی‌گیری: ۱ بار", html)
        self.assertNotIn("۲ بار", html)

    def test_room22_day2_after_day1_no_exit_cycle(self) -> None:
        from bot.bazpors_narrator import (
            day_vote_participation_count,
            no_host_day1_no_exit_enter_night,
        )

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "Erfan"))
        gm.add_player(game, _p(30, "Farahani"))
        set_day_vote_defender_uids(game, {20, 30})
        no_host_day1_no_exit_enter_night(game)
        self.assertEqual(day_vote_participation_count(game, 20), 1)
        self.assertEqual(day_vote_participation_count(game, 30), 1)

        game.bazpors_narrator_host_day = 2
        set_day_vote_defender_uids(game, {20, 30})
        html = build_mason_defense_candidates_announcement_html(game)
        self.assertIn("1. Erfan | سابقه رأی‌گیری: ۱ بار", html)
        self.assertIn("2. Farahani | سابقه رأی‌گیری: ۱ بار", html)
        self.assertNotIn("سابقه رأی‌گیری: ۲ بار", html)


class BazporsMozakereDefenseFormatRegressionTests(unittest.TestCase):
    def test_bazpors_keeps_legacy_outcome_format(self) -> None:
        gm = GameManager()
        game = _bazpors_game(gm)
        gm.add_player(game, _p(20, "B"))
        gm.add_player(game, _p(30, "C"))
        begin_no_host_day1_defense_pick(game)
        set_day_vote_defender_uids(game, {20, 30})
        game.bazpors_day_vote_participations[20] = 1
        html = build_no_host_day1_defense_outcome_html(game)
        self.assertIn("بازیکن(های) زیر برای دفاعیه انتخاب شده‌اند", html)
        self.assertIn("سابقه حضور در رأی‌گیری‌های قبلی: ۱", html)
        self.assertNotIn("بازیکنان انتخاب‌شده برای دفاعیه:", html)

    def test_mozakere_keeps_legacy_outcome_format(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(20, "B"))
        set_day_vote_defender_uids(game, {20})
        html = build_no_host_day1_defense_outcome_html(game)
        self.assertIn("بازیکن(های) زیر برای دفاعیه انتخاب شده‌اند", html)
        self.assertNotIn("بازیکنان انتخاب‌شده برای دفاعیه:", html)
