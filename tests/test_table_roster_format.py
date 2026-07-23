"""قالب وضعیت صندلی — گرداننده."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import _players_roster_html
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


class TableRosterFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_compact_eliminated_counts_only(self) -> None:
        game = Game(
            room_code="58",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 11, "احسان-رییس مافیا", Role.MAFIA_BOSS),
                -2: _p(-2, 10, "خسروی-ناتو", Role.NATO),
                -3: _p(-3, 6, "بابک-پزشک", Role.DOCTOR),
                -4: _p(-4, 4, "رضا-بازپرس", Role.INTERROGATOR),
                -5: _p(-5, 9, "بهنام-رویین تن", Role.RUINTAN),
                -6: _p(-6, 7, "حسن-کارآگاه", Role.DETECTIVE),
            },
            max_players=12,
        )
        game.mafia_ids = {-1, -2}
        html_msg = _players_roster_html(game, self.gm)

        self.assertEqual(
            html_msg,
            "👥 <b>وضعیت صندلی:</b> ۰ نفر خارج: 🔴 ۰ مافیا + 🟢 ۰ شهروند",
        )
        self.assertNotIn("باقی مانده", html_msg)
        self.assertNotIn("بازیکنان خارج‌شده", html_msg)
        self.assertNotIn("احسان-رییس مافیا", html_msg)

    def test_dead_faction_breakdown(self) -> None:
        game = Game(
            room_code="85",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 8, "امیر-رییس مافیا", Role.MAFIA_BOSS, alive=False),
                -2: _p(-2, 3, "بابک-ناتو", Role.NATO, alive=False),
                -3: _p(-3, 4, "بهنام-پزشک", Role.DOCTOR, alive=False),
                -4: _p(-4, 6, "فراهانی-کاراگاه", Role.DETECTIVE, alive=False),
                -5: _p(-5, 5, "خسروی-بازپرس", Role.INTERROGATOR, alive=False),
                -6: _p(-6, 1, "احسان-هانتر", Role.HUNTER, alive=False),
                -7: _p(-7, 12, "حسن-شیاد", Role.SHIAD, alive=True),
                -8: _p(-8, 9, "کاوه-شهروند", Role.CITIZEN, alive=True),
                -9: _p(-9, 7, "رایان-شهروند", Role.CITIZEN, alive=True),
            },
            max_players=12,
        )
        game.mafia_ids = {-1, -2, -7}
        html_msg = _players_roster_html(game, self.gm)

        self.assertEqual(
            html_msg,
            "👥 <b>وضعیت صندلی:</b> ۶ نفر خارج: 🔴 ۲ مافیا + 🟢 ۴ شهروند",
        )
        self.assertNotIn("کاوه-شهروند", html_msg)


if __name__ == "__main__":
    unittest.main()
