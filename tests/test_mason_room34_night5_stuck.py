"""Room 34 — Night 5 readiness deadlock regression (Mason only).

Root cause: dead role holders still blocked on mason_night_*_confirmed flags.
"""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_ready import (
    all_mason_parallel_night_ready,
    explain_mason_night_stuck,
    format_mason_night_readiness_report,
)
from bot.models import Player, Role


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _room34_night5_game(gm: GameManager):
    """Five alive players after Night 5 mafia shot — matches Room 34 end state."""
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=18,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 5
    game.no_host_night_parallel_collect_active = True
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = 900
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True

    dead_roles = (
        (-920015, "امیر - پزشک", Role.DOCTOR, 6),
        (-920012, "امین - اسنایپر", Role.SNIPER, 3),
        (-920011, "حسن - فرمانده", Role.COMMANDER, 13),
        (-920010, "بابک - ناتاشا", Role.NATASHA, 2),
        (-920009, "فراهانی - کشیش", Role.PRIEST, 8),
        (-920008, "هاکان - محافظ", Role.BODYGUARD, 9),
        (-920007, "خسروی - ماسون", Role.MASON, 12),
        (-920006, "رضا - ناتو", Role.NATO, 18),
    )
    alive_roles = (
        (-920016, "قاسم - کاراگاه", Role.DETECTIVE, 1),
        (-920001, "رامین - گادفادر", Role.GODFATHER, 5),
        (-920014, "رایان - شهر ساده", Role.TOWN_SIMPLE, 7),
        (-920013, "علیرضا - خرابکار", Role.SABOTEUR, 11),
        (-920004, "بهنام - تفنگدار", Role.GUNMAN, 15),
    )
    for uid, name, role, seat in dead_roles:
        gm.add_player(game, _p(uid, name, role, alive=False, seat=seat))
    for uid, name, role, seat in alive_roles:
        gm.add_player(game, _p(uid, name, role, seat=seat))
    return game


def _old_sniper_ready(game) -> bool:
    from bot.roles.registry import find_alive_role_holder

    sn = find_alive_role_holder(game, Role.SNIPER)
    if sn is None:
        return game.mason_night_sniper_confirmed
    return True


def _old_all_ready(game) -> bool:
    checks = (
        game.no_host_mafia_shot_done,
        game.mason_night_saboteur_confirmed,
        game.mason_night_doctor_confirmed,
        _old_sniper_ready(game),
        game.mason_night_commander_confirmed,
        game.mason_night_gunner_confirmed,
        game.mason_night_guardian_confirmed,
        game.mason_night_mason_confirmed,
        game.mason_night_detective_confirmed,
        game.mason_night_natasha_confirmed,
        game.mason_night_priest_confirmed,
    )
    return all(checks)


class Room34Night5StuckTests(unittest.TestCase):
    def test_old_logic_stuck_when_alive_players_finished_dead_flags_false(self) -> None:
        gm = GameManager()
        game = _room34_night5_game(gm)
        game.mason_night_saboteur_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_wait_ok_uids = [-920014]

        self.assertFalse(_old_all_ready(game))
        self.assertFalse(game.mason_night_doctor_confirmed)
        self.assertFalse(game.mason_night_sniper_confirmed)
        self.assertFalse(game.mason_night_natasha_confirmed)

    def test_fixed_readiness_when_alive_players_finished(self) -> None:
        gm = GameManager()
        game = _room34_night5_game(gm)
        game.mason_night_saboteur_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_wait_ok_uids = [-920014]

        self.assertTrue(all_mason_parallel_night_ready(game))

    def test_diagnostic_identifies_unconfirmed_alive_roles(self) -> None:
        gm = GameManager()
        game = _room34_night5_game(gm)
        game.mason_night_saboteur_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_detective_confirmed = False
        report = explain_mason_night_stuck(game, gm)
        self.assertIn("Detective", report)
        self.assertIn("mason_night_detective_confirmed = False", report)

    def test_readiness_report_complete_after_alive_actions(self) -> None:
        gm = GameManager()
        game = _room34_night5_game(gm)
        game.mason_night_saboteur_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_wait_ok_uids = [-920014]
        report = format_mason_night_readiness_report(game, gm)
        self.assertIn("Final readiness = True", report)


if __name__ == "__main__":
    unittest.main()
