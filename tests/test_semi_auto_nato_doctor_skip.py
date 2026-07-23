"""نیمه‌خودکار — پزشک پس از ناتویی همان شب."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NIGHT_ACTIONS,
    NS_DOC_NATO_SKIP,
    _advance_after_det,
    build_host_message_and_keyboard,
    process_narrator_callback,
)
from bot.game import GameManager
from bot.models import Game, Player, Role
from tests.test_semi_auto_yaku_doctor_skip import make_semi_auto_game


class SemiAutoNatoDoctorSkipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_advance_after_det_shows_nato_skip_panel(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_nato_action_registered = True

        _advance_after_det(game)

        self.assertEqual(game.bazpors_night_substep, NS_DOC_NATO_SKIP)

    def test_nato_skip_panel_text_and_confirm(self) -> None:
        game = make_semi_auto_game()
        game.bazpors_nato_action_registered = True
        game.bazpors_interrog_once_done = True
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC_NATO_SKIP

        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("ناتویی", body)
        self.assertIn("نیازی به گرفتن انتخاب پزشک", body)
        self.assertIsNotNone(kb)

        err = process_narrator_callback(
            game, self.gm, "doc_nato_skip_ok", 0, ""
        )
        self.assertIsNone(err)
        from bot.bazpors_narrator import NS_INTERROG_SKIP

        self.assertEqual(game.bazpors_night_substep, NS_INTERROG_SKIP)


if __name__ == "__main__":
    unittest.main()
