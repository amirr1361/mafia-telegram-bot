"""رأی پایان روز — no_host."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.bazpors_narrator import DAY_DISCUSS
from bot.no_host_day_vote import (
    build_no_host_day_vote_prompt_html,
    no_host_day_ordinal_fa,
    no_host_end_day_vote_cb_allowed,
    reset_no_host_day_vote_prompt_state,
)


class NoHostDayVoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game(self, host_day: int) -> Game:
        game = Game(
            room_code="dv",
            host_id=1,
            scenario_name="bazpors",
            players={
                10: Player(10, "کمک", None, Role.CITIZEN, seat=1),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.bazpors_narrator_host_day = host_day
        game.no_host_intro_night_started = True
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 10
        game.bazpors_narrator_step = DAY_DISCUSS
        game.no_host_intro_night_started = True
        return game

    def test_day1_prompt_includes_intro_night(self) -> None:
        game = self._game(1)
        html = build_no_host_day_vote_prompt_html(game)
        self.assertIn("شب معارفه", html)
        self.assertIn("روز اول", html)

    def test_day2_prompt_sun_line_only(self) -> None:
        game = self._game(2)
        html = build_no_host_day_vote_prompt_html(game)
        self.assertNotIn("شب معارفه", html)
        self.assertIn("روز دوم", html)
        self.assertIn("رأی‌گیری روز دوم", html)

    def test_reset_allows_new_prompt(self) -> None:
        game = self._game(2)
        game.no_host_day1_vote_prompt_sent = True
        game.no_host_day1_vote_resolved = True
        reset_no_host_day_vote_prompt_state(game)
        self.assertFalse(game.no_host_day1_vote_prompt_sent)
        self.assertFalse(game.no_host_day1_vote_resolved)

    def test_day_ordinal(self) -> None:
        self.assertEqual(no_host_day_ordinal_fa(3), "سوم")

    def test_day2_discuss_allows_vote_buttons(self) -> None:
        game = self._game(2)
        self.assertTrue(no_host_end_day_vote_cb_allowed(game))
        game.no_host_day1_vote_resolved = True
        self.assertFalse(no_host_end_day_vote_cb_allowed(game))

    def test_day_vote_prompt_starts_defense_pick_directly(self) -> None:
        from bot.main import (
            build_no_host_day1_defense_pick_html,
            day1_defense_pick_keyboard_for,
        )

        game = self._game(2)
        kb = day1_defense_pick_keyboard_for(game, 10)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertTrue(any("برو به مرحله بعد" in t for t in labels))
        self.assertTrue(any("دفاعیه نداریم" in t for t in labels))
        text = build_no_host_day1_defense_pick_html(game)
        self.assertIn("🌅 روز شروع شد", text)

    def test_clear_mirror_prompts_removes_vote_and_defense_keys(self) -> None:
        from bot.no_host_day_vote import (
            clear_no_host_day_mirror_prompts,
            no_host_day_vote_choice_ui_key,
        )
        from bot.observer_delivery import mirror_ui_claim_key

        game = self._game(2)
        vote_key = no_host_day_vote_choice_ui_key(game, 10)
        pick_key = mirror_ui_claim_key(game.room_code, "day_defense_pick_2", 10)
        game.mirror_prompt_messages[vote_key] = {"text": "x"}
        game.mirror_prompt_messages[pick_key] = {"text": "y"}
        game.mirror_action_claims[vote_key] = 10
        game.mirror_action_claims[pick_key] = 10
        clear_no_host_day_mirror_prompts(game)
        self.assertNotIn(vote_key, game.mirror_prompt_messages)
        self.assertNotIn(pick_key, game.mirror_prompt_messages)
        self.assertNotIn(vote_key, game.mirror_action_claims)
        self.assertNotIn(pick_key, game.mirror_action_claims)
