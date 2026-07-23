"""رأی پایان روز — گردانندگی نیمه‌خودکار."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    DAY_VOTE_ELIM_ASK,
    CONFIRM_DAY_ELIM,
    build_host_message_and_keyboard,
    process_narrator_callback,
    set_day_vote_defender_uids,
)
from bot.game import GameManager
from bot.models import Game, Player, Role


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


class DayVoteSingleDefenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = Game(
            room_code="88",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "علی", Role.CITIZEN),
                -2: _p(-2, 2, "رضا", Role.CITIZEN),
            },
        )
        self.game.bazpors_host_mode = "semi_auto"
        self.game.bazpors_narrator_step = DAY_VOTE_ELIM_ASK
        set_day_vote_defender_uids(self.game, {-1})

    def test_single_defender_panel_has_two_buttons_only(self) -> None:
        body, kb = build_host_message_and_keyboard(self.game, self.gm)
        self.assertIn("فقط یک نفر", body)
        self.assertNotIn("رأی‌ها مساوی بود", body)
        self.assertNotIn("بیشترین رأی را آورد", body)
        assert kb is not None
        labels = " ".join(
            btn.text for row in kb.inline_keyboard for btn in row
        )
        self.assertIn("علی", labels)
        self.assertIn("خارج شد", labels)
        self.assertIn("کسی خارج نشد", labels)
        self.assertEqual(len(kb.inline_keyboard), 2)

    def test_single_elim_goes_to_confirm(self) -> None:
        err = process_narrator_callback(
            self.game, self.gm, "dv_single_elim", -1, ""
        )
        self.assertIsNone(err)
        self.assertEqual(self.game.bazpors_narrator_step, CONFIRM_DAY_ELIM)
        self.assertEqual(self.game.bazpors_narrator_pending_uid, -1)


class DayVoteMultiDefenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = Game(
            room_code="89",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 8, "صندلی ۸", Role.CITIZEN),
                -2: _p(-2, 7, "صندلی ۷", Role.CITIZEN),
            },
        )
        self.game.bazpors_host_mode = "semi_auto"
        self.game.bazpors_narrator_step = DAY_VOTE_ELIM_ASK
        set_day_vote_defender_uids(self.game, {-1, -2})

    def test_multi_defender_panel_per_player_buttons(self) -> None:
        body, kb = build_host_message_and_keyboard(self.game, self.gm)
        self.assertNotIn("رأی‌ها مساوی بود", body)
        self.assertNotIn("بیشترین رأی را آورد", body)
        self.assertNotIn("قانون تعیین خروج", body)
        assert kb is not None
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(len(labels), 4)
        self.assertTrue(any("صندلی ۸" in lab and "خارج شد" in lab for lab in labels))
        self.assertTrue(any("صندلی ۷" in lab and "خارج شد" in lab for lab in labels))
        self.assertIn("⭕ کسی خارج نشد", labels)
        self.assertIn("↩️ ویرایش انتخاب‌ها", labels)

    def test_defender_out_goes_to_confirm(self) -> None:
        err = process_narrator_callback(
            self.game, self.gm, "dv_defender_out", -2, ""
        )
        self.assertIsNone(err)
        self.assertEqual(self.game.bazpors_narrator_step, CONFIRM_DAY_ELIM)
        self.assertEqual(self.game.bazpors_narrator_pending_uid, -2)


if __name__ == "__main__":
    unittest.main()
