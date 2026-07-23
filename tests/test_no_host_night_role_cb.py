"""مجوز callback نقش‌ها در no_host و تطابق زیرمرحلهٔ شب."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_DOC,
    narrator_callback_user_may_act,
    no_host_night_role_player_may_act_bazpors_cb,
)
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


def _no_host_night_game_with_doctor(doctor_uid: int) -> Game:
    players = {
        900: _p(900, 1, "دستیار", Role.CITIZEN),
        doctor_uid: _p(doctor_uid, 2, "پزشک", Role.DOCTOR),
    }
    game = Game(
        room_code="nh1",
        host_id=100,
        scenario_name="bazpors",
        players=players,
        max_players=13,
    )
    game.bazpors_host_mode = "no_host"
    game.bot_assistant_user_id = 900
    game.no_host_assistant_narrator_active = True
    game.no_host_observer_only_narrator_mirror = False
    game.bazpors_narrator_step = NIGHT_ACTIONS
    game.bazpors_night_substep = NS_DOC
    return game


class NoHostNightRoleCallbackTests(unittest.TestCase):
    def test_doctor_uses_private_mirror_not_bazpors_cb(self) -> None:
        game = _no_host_night_game_with_doctor(501)
        self.assertFalse(no_host_night_role_player_may_act_bazpors_cb(game, 501))
        self.assertFalse(narrator_callback_user_may_act(game, 501))

    def test_other_uid_cannot_act_as_doctor(self) -> None:
        game = _no_host_night_game_with_doctor(501)
        self.assertFalse(no_host_night_role_player_may_act_bazpors_cb(game, 999))

    def test_semi_auto_doctor_not_allowed_via_no_host_helper(self) -> None:
        game = _no_host_night_game_with_doctor(501)
        game.bazpors_host_mode = "semi_auto"
        self.assertFalse(no_host_night_role_player_may_act_bazpors_cb(game, 501))


if __name__ == "__main__":
    unittest.main()
