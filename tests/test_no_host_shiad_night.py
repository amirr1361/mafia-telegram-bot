"""شیاد — شب no_host."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_shiad_night import (
    NS_SHIAD,
    _commit_shiad_pick,
    _shiad_guess_pool,
    _shiad_panel_already_sent_for_night,
    build_no_host_shiad_pick_html,
    dispatch_no_host_shiad_night_panel,
    start_no_host_shiad_night_flow,
)


class NoHostShiadNightTest(unittest.TestCase):
    def test_pick_html(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bazpors_narrator_night_count = 1
        body = build_no_host_shiad_pick_html(game)
        self.assertIn("شب اول", body)
        self.assertIn("انتخاب شیاد", body)
        self.assertIn("کارآگاه", body)
        self.assertNotIn("منفی", body)

    def test_pool_excludes_self_and_mafia(self) -> None:
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
            Player(user_id=10, full_name="Sh", username=None, role=Role.SHIAD),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        gm.add_player(
            game,
            Player(
                user_id=30,
                full_name="Boss",
                username=None,
                role=Role.MAFIA_BOSS,
            ),
        )
        pool = _shiad_guess_pool(game)
        self.assertEqual([p.user_id for p in pool], [20])

    def test_commit_blocks_detective(self) -> None:
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
            Player(user_id=10, full_name="Sh", username=None, role=Role.SHIAD),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Det", username=None, role=Role.DETECTIVE),
        )
        hit = _commit_shiad_pick(game, 20)
        self.assertTrue(hit)
        self.assertTrue(game.bazpors_detective_blocked)
        self.assertFalse(game.bazpors_det_ack_positive)
        self.assertEqual(game.bazpors_shiad_target_uid, 20)

    def test_shiad_wrong_guess_does_not_clear_detective_result(self) -> None:
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
            Player(user_id=10, full_name="Bobak", username=None, role=Role.SHIAD),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Det", username=None, role=Role.DETECTIVE),
        )
        gm.add_player(
            game,
            Player(user_id=30, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        game.actions.detective_check = 10
        game.bazpors_det_ack_positive = True
        hit = _commit_shiad_pick(game, 30)
        self.assertFalse(hit)
        self.assertFalse(game.bazpors_detective_blocked)
        self.assertTrue(game.bazpors_det_ack_positive)
        self.assertEqual(game.actions.detective_check, 10)


class NoHostShiadPanelDedupTest(unittest.IsolatedAsyncioTestCase):
    def _game(self) -> tuple[GameManager, object, int]:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_step = "night_start"
        game.bazpors_narrator_night_count = 2
        sh_uid = -920002
        gm.add_player(
            game,
            Player(
                user_id=sh_uid,
                full_name="Sh",
                username=None,
                role=Role.SHIAD,
                seat=1,
                is_alive=True,
            ),
        )
        gm.add_player(
            game,
            Player(
                user_id=-920001,
                full_name="Cit",
                username=None,
                role=Role.CITIZEN,
                seat=2,
                is_alive=True,
            ),
        )
        return gm, game, sh_uid

    def test_panel_prefix_dedup_across_entry_and_narrator_sig(self) -> None:
        _, game, _ = self._game()
        game.no_host_shiad_dm_signature = "2:shiad:night_entry"
        self.assertTrue(_shiad_panel_already_sent_for_night(game, 2))

    async def test_second_start_skips_publish(self) -> None:
        gm, game, _ = self._game()
        game.no_host_shiad_dm_signature = "2:shiad:night_entry"
        bot = AsyncMock()
        with patch(
            "bot.no_host_shiad_night.publish_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as publish:
            sent = await start_no_host_shiad_night_flow(
                bot, game, gm, at_night_entry=False
            )
            self.assertFalse(sent)
            publish.assert_not_awaited()

    async def test_dispatch_skips_resend_when_panel_already_sent(self) -> None:
        gm, game, _ = self._game()
        game.no_host_shiad_dm_signature = f"2:shiad:{NS_SHIAD}"
        game.no_host_shiad_flow_active = False
        bot = AsyncMock()
        with patch(
            "bot.no_host_shiad_night.start_no_host_shiad_night_flow",
            new_callable=AsyncMock,
        ) as start_flow:
            await dispatch_no_host_shiad_night_panel(bot, game, gm)
            start_flow.assert_not_awaited()
            self.assertTrue(game.no_host_shiad_flow_active)


if __name__ == "__main__":
    unittest.main()
