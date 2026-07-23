"""شب ۱ — یاکوزایی no_host."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import _yaku_negotiation_succeeds, _yaku_sacrifice_pool
from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_NATO,
    MAFIA_ACTION_SHOT,
    MAFIA_ACTION_YAKU,
    _available_mafia_actions,
    _yaku_option_visible,
    resolve_mafia_night1_panel_recipients,
)
from bot.no_host_mafia_yaku import (
    _apply_yaku_outcome,
    build_no_host_yaku_converted_player_html,
    build_no_host_yaku_denied_html,
    mafia_yaku_act_active,
    no_host_yaku_boss_actor_may_act,
    resolve_no_host_yaku_boss_uid,
    start_no_host_mafia_yaku_flow,
)
class NoHostMafiaYakuTest(unittest.TestCase):
    def test_denied_html(self) -> None:
        self.assertIn("مقدور نمی", build_no_host_yaku_denied_html())

    def test_successful_yaku_sets_mafia_basic_role(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        gm.add_player(
            game,
            Player(user_id=30, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        ok = _apply_yaku_outcome(game, gm, sac_uid=20, civ_uid=30)
        self.assertTrue(ok)
        self.assertEqual(game.players[30].role, Role.MAFIA_BASIC)
        self.assertEqual(game.players[30].bazpors_original_role, Role.CITIZEN)

    def test_yaku_acts(self) -> None:
        self.assertTrue(mafia_yaku_act_active(None, "ysp"))
        self.assertFalse(mafia_yaku_act_active(None, "nms"))

    def test_sac_pool_excludes_boss_when_multiple_mafia(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=13,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        pool = _yaku_sacrifice_pool(game)
        self.assertEqual([p.user_id for p in pool], [20])

    def test_sac_pool_boss_only_when_sole_mafia(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game,
            Player(user_id=50, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        pool = _yaku_sacrifice_pool(game)
        self.assertEqual([p.user_id for p in pool], [10])

    def test_yaku_visible_requires_boss(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS, is_alive=False),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        self.assertFalse(_yaku_option_visible(game, gm))

    def test_13p_ruintan_negotiation_fails(self) -> None:
        from tests.test_yaku_ruintan_13 import make_13p_game

        game = make_13p_game()
        ruintan = next(p for p in game.players.values() if p.role == Role.RUINTAN)
        self.assertFalse(_yaku_negotiation_succeeds(game, ruintan))

    def test_night2_menu_includes_yaku_when_allowed(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Maf", username=None, role=Role.MAFIA_BASIC),
        )
        gm.add_player(
            game,
            Player(user_id=30, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        gm.add_player(
            game,
            Player(user_id=40, full_name="Cit2", username=None, role=Role.CITIZEN),
        )
        gm.add_player(
            game,
            Player(user_id=50, full_name="Cit3", username=None, role=Role.CITIZEN),
        )
        game.bazpors_narrator_night_count = 2
        actions = _available_mafia_actions(game, gm)
        self.assertIn(MAFIA_ACTION_SHOT, actions)
        self.assertIn(MAFIA_ACTION_YAKU, actions)
        self.assertNotIn(MAFIA_ACTION_NATO, actions)

    def test_boss_gets_panel_alone(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=13,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [10])

    def test_converted_message_shows_sacrifice_and_roles(self) -> None:
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
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game,
            Player(user_id=20, full_name="Nato", username=None, role=Role.NATO),
        )
        gm.add_player(
            game,
            Player(user_id=30, full_name="Cit", username=None, role=Role.CITIZEN),
        )
        game.bazpors_yaku_sac_elim_uid = 20
        game.bazpors_mafia_recruit_ids.add(30)
        game.players[30].bazpors_converted_by_yakuza = True

        body = build_no_host_yaku_converted_player_html(game, gm, 30)
        self.assertIn("فدای یاکوزایی", body)
        self.assertIn("Nato", body)
        self.assertIn("ناتو", body)
        self.assertIn("رییس مافیا", body)
        self.assertIn("Boss", body)

    def test_boss_actor_may_act_yaku_not_other_mafia(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=13,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=10, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game, Player(user_id=20, full_name="Nato", username=None, role=Role.NATO)
        )
        self.assertEqual(resolve_no_host_yaku_boss_uid(game), 10)
        self.assertTrue(no_host_yaku_boss_actor_may_act(game, 10, 10))
        self.assertFalse(no_host_yaku_boss_actor_may_act(game, 20, 10))


class NoHostMafiaYakuFlowStartTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_yaku_flow_after_menu_confirm(self) -> None:
        from unittest.mock import AsyncMock, patch

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
            Player(user_id=-920003, full_name="Boss", username=None, role=Role.MAFIA_BOSS),
        )
        gm.add_player(
            game,
            Player(user_id=-920002, full_name="Basic", username=None, role=Role.MAFIA_BASIC),
        )
        for uid in (-920001, -920004, -920005):
            gm.add_player(
                game,
                Player(user_id=uid, full_name=f"C{uid}", username=None, role=Role.CITIZEN),
            )
        game.bazpors_narrator_night_count = 1
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_YAKU
        game.no_host_mafia_night1_panel_uids = [-920003]
        game.observer_user_id = 999
        game.observer_prompt_status = "registered"

        bot = AsyncMock()
        with patch(
            "bot.no_host_mafia_yaku._broadcast_yaku_wait_to_non_mafia",
            new_callable=AsyncMock,
        ) as wait_non_mafia, patch(
            "bot.no_host_detective_night.apply_no_host_detective_yaku_started_reselect_panel",
            new_callable=AsyncMock,
        ) as det_reselect, patch(
            "bot.no_host_mafia_yaku._notify_non_boss_mafia_yaku_observe",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_yaku._edit_mafia_prompt",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_yaku.sync_mafia_mirror_panel",
            new_callable=AsyncMock,
        ):
            await start_no_host_mafia_yaku_flow(bot, game, gm)
            wait_non_mafia.assert_awaited_once()
            det_reselect.assert_awaited_once_with(bot, game, gm)

        self.assertTrue(game.no_host_mafia_yaku_flow_active)
        self.assertEqual(game.no_host_mafia_yaku_phase, "sac")


if __name__ == "__main__":
    unittest.main()
