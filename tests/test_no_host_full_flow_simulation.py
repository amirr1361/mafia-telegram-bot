"""شبیه‌سازی مسیرهای no_host از لابی تا پایان بازی — همه دکمه‌های روز اول."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_mafia_team
from bot.main import (
    NoHostDay1DefenseCb,
    _dispatch_no_host_day1_defense_act,
    _no_host_day1_defense_outcome_keyboard,
    day1_defense_pick_keyboard_for,
    finalize_no_host_bot_assistant,
)
from bot.models import Phase, Player, Role
from bot.no_host_night_ready import all_no_host_parallel_night_ready
from bot.room_mode import is_bazpors_no_host_room

from tests.no_host_flow_harness import NoHostFlowHarness, _callback


class NoHostFullFlowSimulationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_lobby_deal_and_assistant_ready(self) -> None:
        h = NoHostFlowHarness.build(self.gm)
        self.assertTrue(is_bazpors_no_host_room(h.game))
        self.assertTrue(h.game.roles_dealt)
        self.assertEqual(h.game.bot_assistant_user_id, h.assistant_uid)
        self.assertEqual(len(h.game.players), 10)
        mafia_count = sum(
            1 for p in h.game.players.values() if p.role and is_mafia_team(p.role)
        )
        self.assertGreaterEqual(mafia_count, 2)

    async def test_finalize_bot_assistant_callback_path(self) -> None:
        h = NoHostFlowHarness.build(self.gm)
        h.game.bot_assistant_user_id = None
        with (
            patch("bot.main.send_private_role", new_callable=AsyncMock, return_value=True),
            patch("bot.main.send_to_player", new_callable=AsyncMock),
            patch("bot.main.broadcast_to_players", new_callable=AsyncMock),
        ):
            await finalize_no_host_bot_assistant(
                h.bot, h.game, h.assistant_uid, random_pick=False
            )
        self.assertEqual(h.game.bot_assistant_user_id, h.assistant_uid)

    async def test_all_day1_paths_enter_night1(self) -> None:
        for path in ("no_defense", "no_exit", "elim"):
            with self.subTest(day1_path=path):
                h = NoHostFlowHarness.build(self.gm)
                await h.run_day1_path(path)
                self.assertFalse(h.game.no_host_day1_defense_active)

    async def test_full_paths_to_civilian_win(self) -> None:
        for path in ("no_defense", "no_exit", "elim"):
            with self.subTest(day1_path=path, winner="citizen"):
                h = NoHostFlowHarness.build(self.gm)
                await h.run_full_path_to_game_end(path, winner="citizen")

    async def test_full_paths_to_mafia_win(self) -> None:
        for path in ("no_defense", "no_exit"):
            with self.subTest(day1_path=path, winner="mafia"):
                h = NoHostFlowHarness.build(self.gm)
                await h.run_full_path_to_game_end(path, winner="mafia")

    async def test_night1_resolve_advances_to_day2(self) -> None:
        h = NoHostFlowHarness.build(self.gm)
        await h.run_day1_path("no_exit")
        host_day_before = h.game.bazpors_narrator_host_day
        h.arm_night1_parallel_ready()
        self.assertTrue(all_no_host_parallel_night_ready(h.game))
        await h.resolve_night1()
        self.assertGreaterEqual(h.game.bazpors_narrator_host_day, host_day_before)
        self.assertTrue(h.game.bazpors_night_report_html)

    async def test_defense_elim_back_then_no_exit(self) -> None:
        """خروج → بازگشت → خروجی نداشتیم."""
        h = NoHostFlowHarness.build(self.gm)
        await h.run_intro_night()
        target = h._citizen_uid()
        await h.day1_defense_pick_and_confirm([target])
        await h.dispatch_defense("d1el", tid=target)
        await h.dispatch_defense("elim_no")
        self.assertEqual(h.game.no_host_day1_defense_phase, "outcome")
        await h.day1_no_exit()
        h.assert_entered_night1()

    async def test_every_day1_keyboard_act_dispatches(self) -> None:
        """هر act روی کیبورد روز اول بدون NameError اجرا شود."""
        h = NoHostFlowHarness.build(self.gm)
        await h.run_intro_night()
        target = h._citizen_uid()

        steps: list[tuple[str, str, int]] = [
            ("tog", "pick", target),
            ("confirm", "pick", 0),
        ]
        for act, phase, tid in steps:
            h.game.no_host_day1_defense_phase = phase
            if act == "tog":
                h.game.no_host_day1_defense_phase = "pick"
            await h.dispatch_defense(act, tid=tid)

        h.game.no_host_day1_defense_phase = "outcome"
        await h.dispatch_defense("no_exit")

        h2 = NoHostFlowHarness.build(self.gm)
        await h2.run_intro_night()
        t2 = h2._citizen_uid()
        await h2.day1_defense_pick_and_confirm([t2])
        await h2.dispatch_defense("d1el", tid=t2)
        h2.game.no_host_day1_defense_phase = "confirm_elim"
        h2.game.no_host_day1_pending_elim_uid = t2
        with patch(
            "bot.main.eliminate_player_from_game",
            return_value="",
        ), patch(
            "bot.main.flush_elimination_notifications",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_win.no_host_maybe_end_on_faction_win",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "bot.main.close_mirror_prompt_keyboards",
            new_callable=AsyncMock,
        ):
            await h2.dispatch_defense("elim_yes")

    def test_day1_keyboard_callback_data_packable(self) -> None:
        h = NoHostFlowHarness.build(self.gm)
        h.game.no_host_day1_defense_active = True
        h.game.no_host_day1_defense_phase = "pick"
        pick_kb = day1_defense_pick_keyboard_for(h.game, h.assistant_uid)
        pick_cbs = [
            btn.callback_data
            for row in pick_kb.inline_keyboard
            for btn in row
        ]
        for raw in pick_cbs:
            unpacked = NoHostDay1DefenseCb.unpack(raw)
            self.assertEqual(unpacked.code, h.game.room_code)

        h.game.no_host_day1_defense_phase = "outcome"
        from bot.bazpors_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(h.game, {h._citizen_uid()})
        out_kb = _no_host_day1_defense_outcome_keyboard(
            h.game, h.assistant_uid, mirror=False
        )
        acts = []
        for row in out_kb.inline_keyboard:
            for btn in row:
                data = NoHostDay1DefenseCb.unpack(btn.callback_data)
                acts.append(data.act)
        self.assertIn("no_exit", acts)
        self.assertIn("d1el", acts)

    async def test_no_exit_never_raises_on_dispatch(self) -> None:
        h = NoHostFlowHarness.build(self.gm)
        await h.run_intro_night()
        target = h._citizen_uid()
        await h.day1_defense_pick_and_confirm([target])
        cb = _callback(h.assistant_uid)
        with patch("bot.main.broadcast_to_alive_players", new_callable=AsyncMock), patch(
            "bot.main.on_no_host_entered_night1", new_callable=AsyncMock
        ):
            await _dispatch_no_host_day1_defense_act(
                cb,
                h.bot,
                h.game,
                h.assistant_uid,
                h.assistant_uid,
                "no_exit",
                source="nhd",
            )
        self.assertIsNone(h.game.no_host_day1_defense_phase)


class NoHostNaturalEndSimulationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    async def test_night1_all_role_buttons_then_day2(self) -> None:
        h = NoHostFlowHarness.build(GameManager())
        await h.run_day1_path("no_defense")
        host_day_before = h.game.bazpors_narrator_host_day
        await h.complete_night1_via_role_buttons()
        self.assertGreaterEqual(h.game.bazpors_narrator_host_day, host_day_before)

    async def test_full_game_ends_naturally_from_no_defense(self) -> None:
        h = NoHostFlowHarness.build(GameManager())
        winner = await h.run_until_natural_game_end("no_defense", max_steps=100)
        self.assertIn(winner, ("mafia", "citizen"))

    async def test_full_game_ends_naturally_from_no_exit(self) -> None:
        h = NoHostFlowHarness.build(GameManager())
        winner = await h.run_until_natural_game_end("no_exit", max_steps=100)
        self.assertIn(winner, ("mafia", "citizen"))


class NoHostDealPipelineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deal_pipeline_then_harness_intro(self) -> None:
        from bot.main import deal_roles_full_pipeline

        gm = GameManager()
        creator = 8001
        game = gm.create_game(
            host_id=creator,
            host_full_name="C",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, Player(creator, "C", None))
        gm.fill_bazpors_no_host_synthetic_lobby(game)
        game.seats_finalized = True
        bot = MagicMock()
        with (
            patch("bot.main.send_private_role", new_callable=AsyncMock, return_value=True),
            patch("bot.main.notify_players_after_roles_dealt", new_callable=AsyncMock),
            patch("bot.main.send_no_host_observer_prompt", new_callable=AsyncMock),
        ):
            err = await deal_roles_full_pipeline(bot, game)
        self.assertIsNone(err)
        self.assertTrue(game.roles_dealt)
        game.bot_assistant_user_id = creator
        game.no_host_assistant_narrator_active = True
        game.observer_prompt_status = "skipped"
        h = NoHostFlowHarness(gm, game, creator_uid=creator, assistant_uid=creator)
        await h.run_intro_night()
        self.assertEqual(game.phase, Phase.MANUAL)
        await h.day1_no_defense()
        self.assertGreaterEqual(game.bazpors_narrator_night_count, 1)


if __name__ == "__main__":
    unittest.main()
