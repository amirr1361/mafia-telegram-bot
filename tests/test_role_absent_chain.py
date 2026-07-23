"""زنجیرهٔ «نقش از بازی خارج بود» — رگرسیون باگ گیر کردن روی role_absent_ok."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NIGHT_STEP_NEXT_BTN,
    NS_INTERROG_SKIP,
    NS_MAFIA_MENU,
    NS_ROLE_ABSENT,
    NIGHT_ACTIONS,
    _advance_after_role_absent,
    _advance_after_shiad,
    _begin_night_actions,
    build_host_message_and_keyboard,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role


def _player(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def make_night2_post_shiad_game() -> Game:
    """
    وضعیت شبیه اتاق ۸۱ بعد از sg در شب ۲:
    هانتر، کارآگاه، پزشک، رئیس مافیا، ناتو مرده؛ شیاد و بازپرس زنده.
    """
    players = {
        -910001: _player(-910001, 1, "شهروند ۱", Role.CITIZEN),
        -910002: _player(-910002, 2, "شهروند ۲", Role.CITIZEN),
        -910003: _player(-910003, 3, "شیاد", Role.SHIAD),
        -910004: _player(-910004, 4, "هانتر", Role.HUNTER, alive=False),
        -910005: _player(-910005, 5, "کاراگاه", Role.DETECTIVE, alive=False),
        -910006: _player(-910006, 6, "بازپرس", Role.INTERROGATOR),
        -910007: _player(-910007, 7, "رییس مافیا", Role.MAFIA_BOSS, alive=False),
        -910008: _player(-910008, 8, "پزشک", Role.DOCTOR, alive=False),
        -910009: _player(-910009, 9, "رویین تن", Role.RUINTAN),
        -910010: _player(-910010, 10, "ناتو", Role.NATO, alive=False),
    }
    game = Game(
        room_code="81",
        host_id=108214166,
        scenario_name="bazpors_salamat_test",
        players=players,
    )
    game.bazpors_narrator_step = NIGHT_ACTIONS
    game.bazpors_narrator_night_count = 2
    game.bazpors_narrator_host_day = 2
    game.bazpors_interrog_once_done = True
    game.bazpors_mafia_shot_registered = True
    game.bazpors_mafia_target = -910002
    game.bazpors_shiad_target_uid = -910002
    game.bazpors_alive_at_night_start = {
        uid: p.is_alive for uid, p in players.items()
    }
    game.bazpors_night_step_history = ["ns_hunter", "ns_mafia_menu", "ns_shiad"]
    return game


class RoleAbsentChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_advance_after_shiad_enters_detective_absent(self) -> None:
        game = make_night2_post_shiad_game()
        game.bazpors_night_substep = "ns_shiad"

        _advance_after_shiad(game)

        self.assertEqual(game.bazpors_night_substep, NS_ROLE_ABSENT)
        self.assertEqual(game.bazpors_absent_night_role, Role.DETECTIVE.value)

    def test_advance_after_detective_absent_schedules_doctor(self) -> None:
        game = make_night2_post_shiad_game()
        game.bazpors_night_substep = NS_ROLE_ABSENT
        game.bazpors_absent_night_role = Role.DETECTIVE.value

        _advance_after_role_absent(game)

        self.assertEqual(game.bazpors_night_substep, NS_ROLE_ABSENT)
        self.assertEqual(game.bazpors_absent_night_role, Role.DOCTOR.value)

    def test_role_absent_ok_chain_leaves_absent_step(self) -> None:
        game = make_night2_post_shiad_game()
        game.bazpors_night_substep = NS_ROLE_ABSENT
        game.bazpors_absent_night_role = Role.DETECTIVE.value

        err = process_narrator_callback(game, self.gm, "role_absent_ok", 0, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_absent_night_role, Role.DOCTOR.value)
        self.assertEqual(game.bazpors_night_substep, NS_ROLE_ABSENT)

        err = process_narrator_callback(game, self.gm, "role_absent_ok", 0, "")
        self.assertIsNone(err)
        self.assertNotEqual(game.bazpors_night_substep, NS_ROLE_ABSENT)
        self.assertEqual(game.bazpors_night_substep, NS_INTERROG_SKIP)

    def test_begin_night_hunter_absent_then_mafia_menu(self) -> None:
        """شروع شب ۲: هانتر قبلاً مرده → تأیید غایب → منوی مافیا (بدون گیر)."""
        game = make_night2_post_shiad_game()
        game.bazpors_narrator_step = "night_start"
        game.bazpors_night_substep = None
        game.bazpors_absent_night_role = None

        _begin_night_actions(game)

        self.assertEqual(game.bazpors_absent_night_role, Role.HUNTER.value)
        self.assertEqual(game.bazpors_night_substep, NS_ROLE_ABSENT)

        err = process_narrator_callback(game, self.gm, "role_absent_ok", 0, "")
        self.assertIsNone(err)
        self.assertEqual(game.bazpors_night_substep, NS_MAFIA_MENU)
        self.assertIsNone(game.bazpors_absent_night_role)

    def test_role_absent_host_message_no_player_list(self) -> None:
        game = make_night2_post_shiad_game()
        game.bazpors_night_substep = NS_ROLE_ABSENT
        game.bazpors_absent_night_role = Role.HUNTER.value

        body, kb = build_host_message_and_keyboard(game, self.gm)

        self.assertIn("ثبت انتخاب هانتر", body)
        self.assertIn("هانتر در بازی حضور ندارد", body)
        self.assertIn(NIGHT_STEP_NEXT_BTN, body)
        self.assertIsNotNone(kb)
        assert kb is not None
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(len(labels), 1)
        self.assertIn(NIGHT_STEP_NEXT_BTN, labels[0])
        self.assertNotIn("↩️", labels[0])


if __name__ == "__main__":
    unittest.main()
