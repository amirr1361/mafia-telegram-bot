"""فاز آشوب (۳ نفره) در مسیر no_host."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    DAY_DISCUSS,
    _sync_ki_as_today,
    bazpors_chaos_phase_enabled,
    ki_as_hand_resolve_day_active,
)
from bot.game import GameManager, apply_bazpors_yakuzai_recruit
from bot.models import Game, Player, Role
from bot.no_host_day_vote import no_host_end_day_vote_cb_allowed
from bot.no_host_night_resolve import build_no_host_day_started_broadcast_html


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def make_no_host_room84_day6() -> Game:
    """وضعیت ابتدای روز ۶ اتاق ۸۴ — ۱ مافیا (یاکوزایی‌شده) + ۲ شهروند."""
    game = Game(
        room_code="84",
        host_id=108214166,
        scenario_name="bazpors",
        players={
            -920009: _p(-920009, 3, "خسروی", Role.MAFIA_BASIC),
            -920001: _p(-920001, 7, "فریدونی", Role.CITIZEN),
            -920003: _p(-920003, 9, "کاوه", Role.HUNTER),
        },
        max_players=12,
    )
    game.bazpors_host_mode = "no_host"
    game.bot_assistant_user_id = 108214166
    game.no_host_assistant_narrator_active = True
    game.no_host_intro_night_started = True
    game.bazpors_narrator_step = DAY_DISCUSS
    game.bazpors_narrator_host_day = 6
    game.bazpors_narrator_night_count = 5
    game.bazpors_yakuzai_used = True
    apply_bazpors_yakuzai_recruit(game, game.players[-920009])
    return game


class NoHostKiAsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_chaos_enabled_for_no_host(self) -> None:
        game = make_no_host_room84_day6()
        self.assertTrue(bazpors_chaos_phase_enabled(game))

    def test_sync_ki_as_for_room84_day6(self) -> None:
        game = make_no_host_room84_day6()
        _sync_ki_as_today(game, self.gm)
        self.assertTrue(game.bazpors_ki_as_today)

    def test_ki_as_hand_resolve_active_no_host(self) -> None:
        game = make_no_host_room84_day6()
        _sync_ki_as_today(game, self.gm)
        self.assertTrue(ki_as_hand_resolve_day_active(game, self.gm))

    def test_day_broadcast_mentions_chaos(self) -> None:
        game = make_no_host_room84_day6()
        _sync_ki_as_today(game, self.gm)
        body = build_no_host_day_started_broadcast_html(game, self.gm)
        self.assertIn("فاز آشوب", body)

    def test_day_vote_blocked_on_chaos_day(self) -> None:
        game = make_no_host_room84_day6()
        game.bazpors_ki_as_today = True
        game.no_host_day1_vote_prompt_sent = True
        self.assertFalse(no_host_end_day_vote_cb_allowed(game))


if __name__ == "__main__":
    unittest.main()
