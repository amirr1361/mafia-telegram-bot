"""کارآگاه — شب no_host."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.bazpors_narrator import NS_DET, detective_inquiry_alert_text
from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_detective_night import (
    build_no_host_detective_pick_html,
    build_no_host_detective_result_html,
    build_no_host_detective_yaku_reselect_html,
    apply_no_host_detective_yaku_reselect_panel,
    _void_no_host_detective_night_pick,
)


class NoHostDetectiveNightTest(unittest.TestCase):
    def test_pick_html_all_nights(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        body = build_no_host_detective_pick_html(game)
        self.assertIn("شب اول", body)
        self.assertIn("ثبت انتخاب کاراگاه", body)
        self.assertIn("پایان فاز امشب", body)

        game.bazpors_narrator_night_count = 3
        body3 = build_no_host_detective_pick_html(game)
        self.assertIn("شب سوم", body3)

    def test_result_html_positive_on_shiad_target(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Det", username=None, role=Role.DETECTIVE),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Bobak", username=None, role=Role.SHIAD),
        )
        game.bazpors_narrator_night_count = 1
        game.bazpors_alive_at_night_start = {10: True, 20: True}
        game.actions.detective_check = 20
        game.bazpors_det_ack_positive = True
        body = build_no_host_detective_result_html(game, gm)
        assert body is not None
        self.assertIn("مثبت", body)
        self.assertIn("Bobak", body)

    def test_result_html_positive(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Det", username=None, role=Role.DETECTIVE),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        game.bazpors_narrator_night_count = 1
        game.bazpors_alive_at_night_start = {10: True, 20: True}
        game.actions.detective_check = 20
        game.bazpors_det_ack_positive = False
        body = build_no_host_detective_result_html(game, gm)
        assert body is not None
        self.assertIn("منفی", body)
        self.assertIn("Boss", body)

    def test_no_popup_in_no_host(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 99
        game.bazpors_narrator_step = "night_actions"
        game.bazpors_night_substep = NS_DET
        game.bazpors_det_ack_positive = True
        self.assertIsNone(detective_inquiry_alert_text(game))

    def test_yaku_reselect_html(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 2
        body = build_no_host_detective_yaku_reselect_html(game)
        self.assertIn("یاکوزایی انجام شده", body)
        self.assertIn("مجدداً بازیکن مورد نظر برای استعلام", body)
        self.assertIn("ثبت انتخاب کاراگاه", body)

    def test_void_detective_pick_clears_commit(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.actions.detective_check = 20
        game.bazpors_det_ack_positive = True
        game.bazpors_detective_last_answer = "مثبت / مافیایی"
        _void_no_host_detective_night_pick(game)
        self.assertIsNone(game.actions.detective_check)
        self.assertFalse(game.bazpors_det_ack_positive)
        self.assertIsNone(game.bazpors_detective_last_answer)


class NoHostDetectiveYakuReselectTest(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_detective_not_confirmed(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 99
        gm.add_player(
            game,
            Player(
                user_id=10,
                full_name="Det",
                username=None,
                role=Role.DETECTIVE,
                is_alive=True,
            ),
        )
        game.no_host_detective_pick_confirmed = False
        bot = AsyncMock()
        with patch(
            "bot.no_host_detective_night.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as publish:
            await apply_no_host_detective_yaku_reselect_panel(bot, game, gm)
            publish.assert_not_awaited()

    async def test_reopens_panel_when_detective_already_confirmed(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 99
        game.bazpors_narrator_night_count = 2
        gm.add_player(
            game,
            Player(
                user_id=10,
                full_name="Det",
                username=None,
                role=Role.DETECTIVE,
                is_alive=True,
            ),
        )
        gm.add_player(
            game,
            Player(
                user_id=20,
                full_name="Cit",
                username=None,
                role=Role.CITIZEN,
                is_alive=True,
            ),
        )
        game.no_host_detective_pick_confirmed = True
        game.actions.detective_check = 20
        bot = AsyncMock()
        with patch(
            "bot.no_host_detective_night.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as publish:
            await apply_no_host_detective_yaku_reselect_panel(bot, game, gm)
            publish.assert_awaited_once()
            self.assertFalse(game.no_host_detective_pick_confirmed)
            self.assertTrue(game.no_host_detective_flow_active)
            self.assertIsNone(game.actions.detective_check)
            text = publish.await_args.args[4]
            self.assertIn("یاکوزایی انجام شده", text)


if __name__ == "__main__":
    unittest.main()
