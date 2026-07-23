"""زنجیرهٔ هانتر — فقط پس از تأیید، نه روی پنل تأیید."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    CONFIRM_DAY_ELIM,
    CONFIRM_INTERROG_VOTE_ELIM,
    Role,
    _hunter_chain_warning_html,
    build_host_message_and_keyboard,
)
from bot.game import GameManager
from bot.main import build_no_host_day1_confirm_elim_html
from bot.models import Game, Player


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


class HunterChainConfirmUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _hunter_mafia_game(self) -> Game:
        game = Game(
            room_code="78",
            host_id=1,
            scenario_name="bazpors",
            players={
                1: _p(1, 1, "هانتر", Role.HUNTER),
                2: _p(2, 2, "ناتو", Role.NATO),
                3: _p(3, 3, "شهروند", Role.CITIZEN),
            },
        )
        game.mafia_ids = {2}
        game.bazpors_hunter_link_uid = 2
        game.bazpors_hunter_report_link_uid = 2
        return game

    def test_warning_helper_still_detects_chain(self) -> None:
        game = self._hunter_mafia_game()
        self.assertIn("زنجیره", _hunter_chain_warning_html(game, self.gm, 1))

    def test_semi_auto_confirm_day_panel_has_no_chain_warning(self) -> None:
        game = self._hunter_mafia_game()
        game.bazpors_narrator_step = CONFIRM_DAY_ELIM
        game.bazpors_narrator_pending_uid = 1
        game.bazpors_day_vote_elim_reason = "majority"
        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertNotIn("زنجیرهٔ هانتر", body)
        assert kb is not None
        self.assertTrue(any("تأیید" in b.text for row in kb.inline_keyboard for b in row))

    def test_semi_auto_confirm_interrog_panel_has_no_chain_warning(self) -> None:
        game = self._hunter_mafia_game()
        game.bazpors_narrator_step = CONFIRM_INTERROG_VOTE_ELIM
        game.bazpors_narrator_pending_uid = 1
        game.bazpors_interrog_first_uid = 1
        game.bazpors_interrog_second_uid = 3
        body, _kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("تأیید خروج", body)
        self.assertNotIn("زنجیرهٔ هانتر", body)

    def test_no_host_confirm_elim_panel_has_no_chain_warning(self) -> None:
        game = self._hunter_mafia_game()
        game.bazpors_host_mode = "no_host"
        html_body = build_no_host_day1_confirm_elim_html(game, 1)
        self.assertIn("تأیید حذف", html_body)
        self.assertNotIn("زنجیره", html_body)


if __name__ == "__main__":
    unittest.main()
