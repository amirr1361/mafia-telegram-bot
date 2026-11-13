"""Phase 3 — Namayande-10 fork: gameplay loop, equivalence, reports.

All flows run against the independent ``bot.nam10`` implementation with
isolated rooms and no real Telegram/DB. The equivalence tests pair each
fork room with a same-seeded Bazpors no-host room and require identical
functional outcomes (winner, round counts, final alive roles).
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot import db, game_audit_log
from bot.game import GameManager
from bot.models import Phase, Role
from bot.nam10.engine import nmnd_counts_as_alive_mafia_for_win
from bot.room_mode import is_namayande10_no_host_room


def setUpModule() -> None:
    db.init_db()


def _mk_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_photo = AsyncMock(return_value=MagicMock(message_id=2))
    bot.edit_message_text = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()
    bot.delete_message = AsyncMock()
    return bot


class Phase3LoopTests(unittest.IsolatedAsyncioTestCase):
    async def _paired_run(self, seed: int, day1_path: str = "no_defense"):
        """Run same-seeded fork and Bazpors no-host games to natural end."""
        from tests.nam10_flow_harness import Nam10FlowHarness, _telegram_patches
        from tests.nam10_game_loop import run_until_natural_end
        from tests.no_host_flow_harness import NoHostFlowHarness, _telegram_patches as bp_pat
        from tests.no_host_game_loop import run_until_natural_end as bp_run_until

        random.seed(seed)
        h_n = Nam10FlowHarness.build(GameManager())
        random.seed(seed)
        h_b = NoHostFlowHarness.build(GameManager())

        async with _telegram_patches(h_n.gm):
            w_n = await run_until_natural_end(h_n)
            alive_n = sorted(p.role.value for p in h_n.game.players.values() if p.is_alive)
            rounds_n = (h_n.game.nmnd_narrator_night_count, h_n.game.nmnd_narrator_host_day)
            ended_n = h_n.gm.get_game(h_n.game.room_code) is None
        async with bp_pat(h_b.gm):
            w_b = await bp_run_until(h_b)
            alive_b = sorted(p.role.value for p in h_b.game.players.values() if p.is_alive)
            rounds_b = (h_b.game.bazpors_narrator_night_count, h_b.game.bazpors_narrator_host_day)
        return w_n, alive_n, rounds_n, ended_n, w_b, alive_b, rounds_b

    async def test_paired_equivalence_natural_end_three_seeds(self):
        for seed in (7, 13, 29):
            (w_n, alive_n, rounds_n, ended_n, w_b, alive_b, rounds_b) = await self._paired_run(seed)
            self.assertEqual(w_n, w_b, f"seed {seed}: winner mismatch")
            self.assertEqual(alive_n, alive_b, f"seed {seed}: alive mismatch")
            self.assertEqual(rounds_n, rounds_b, f"seed {seed}: rounds mismatch")
            self.assertTrue(ended_n, f"seed {seed}: fork room not ended")
            self.assertIn(w_n, ("mafia", "citizen"))

    async def _to_day2(self, h):
        from tests.nam10_flow_harness import _telegram_patches
        from tests.nam10_game_loop import advance_one_phase, game_ended, full_simulation_patches

        async with _telegram_patches(h.gm):
            await h.run_intro_night()
            await h.run_day1_path("no_defense")
        async with full_simulation_patches(h):
            steps = 0
            while (
                steps < 40
                and not game_ended(h)
                and h.game.nmnd_narrator_step != "day_discuss"
            ):
                steps += 1
                await advance_one_phase(h)
        self.assertEqual(h.game.nmnd_narrator_host_day, 2)
        self.assertEqual(h.game.nmnd_narrator_step, "day_discuss")
        return h

    async def test_day2_vote_session_real_acts_and_isolation(self):
        from tests.nam10_flow_harness import Nam10FlowHarness, _telegram_patches

        h = await self._to_day2(Nam10FlowHarness.build(GameManager()))
        g = h.game
        target = min(
            uid for uid, p in g.players.items()
            if p.is_alive and not nmnd_counts_as_alive_mafia_for_win(g, p)
        )
        async with _telegram_patches(h.gm):
            await h.dispatch_defense("tog", tid=target)
            self.assertIn("pick", (g.nam10_day1_defense_phase,))
            await h.dispatch_defense("confirm")
            self.assertEqual(g.nam10_day1_defense_phase, "outcome")
            await h.dispatch_defense("d1el", tid=target)
            self.assertEqual(g.nam10_day1_defense_phase, "confirm_elim")
            await h.dispatch_defense("elim_yes")
        self.assertFalse(g.players[target].is_alive)
        self.assertEqual(g.nmnd_narrator_host_day, 2)
        self.assertIsNone(getattr(g, "bazpors_narrator_step", None))
        step = g.nmnd_narrator_step
        self.assertTrue(
            step.startswith("nam10_")
            or step.startswith("nmnd_")
            or step in ("modir_start", "day_discuss", "night_start"),
            step,
        )

    async def test_snapshot_roundtrip_preserves_fork_state(self):
        from bot.game_snapshot import game_from_snapshot_dict, game_to_snapshot_dict
        from tests.nam10_flow_harness import Nam10FlowHarness

        h = await self._to_day2(Nam10FlowHarness.build(GameManager()))
        g = h.game
        data = json.dumps(game_to_snapshot_dict(g), ensure_ascii=False)
        g2 = game_from_snapshot_dict(json.loads(data))
        self.assertEqual(g2.scenario_name, "namayande")
        self.assertEqual(g2.nmnd_host_mode, "no_host")
        self.assertEqual(g2.nmnd_narrator_night_count, g.nmnd_narrator_night_count)
        self.assertEqual(g2.nmnd_narrator_step, g.nmnd_narrator_step)
        self.assertEqual(
            {p.user_id: p.role for p in g2.players.values()},
            {p.user_id: p.role for p in g.players.values()},
        )
        self.assertEqual(g2.players, g.players)
        self.assertTrue(is_namayande10_no_host_room(g2))

    async def test_audit_log_fork_rows(self):
        from tests.nam10_flow_harness import Nam10FlowHarness

        h = Nam10FlowHarness.build(GameManager())
        g = h.game
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            g.audit_log_path = path
            with (
                patch.object(game_audit_log, "game_audit_log_enabled", return_value=True),
                patch("bot.app_state.manager", h.gm),
            ):
                game_audit_log.log_event(g, "no_host.test_event", k=1)
                game_audit_log.log_player_eliminated(g, 123, source="test")
            rows = [json.loads(x) for x in open(path, encoding="utf-8")]
            self.assertTrue(rows)
            self.assertTrue(all(r["room"] == g.room_code for r in rows))
            self.assertIn("no_host.test_event", [r["event"] for r in rows])
            self.assertIn("player.eliminated", [r["event"] for r in rows])

    async def test_elim_report_fork_module(self):
        from bot.nam10 import no_host_elim_report as elim
        from tests.nam10_flow_harness import Nam10FlowHarness

        h = await self._to_day2(Nam10FlowHarness.build(GameManager()))
        g = h.game
        target = min(
            uid for uid, p in g.players.items()
            if p.is_alive and not nmnd_counts_as_alive_mafia_for_win(g, p)
        )
        with patch("bot.app_state.manager", h.gm):
            self.assertTrue(elim.is_fork_elim_report_scenario(g))
            g.players[target].is_alive = False
            entry = elim.capture_nam10_elim_report_cutoff(g, h.gm, target)
            self.assertIsNotNone(entry)
            html1 = elim.build_nam10_elim_cutoff_report_html(g, h.gm)
            self.assertIn("سناریو: نماینده", html1)
            self.assertIn("سناریو:", html1)
        with patch("bot.app_state.manager", h.gm):
            html2 = elim.build_nam10_elim_cutoff_report_html(g, h.gm)
        self.assertEqual(html1, html2)


if __name__ == "__main__":
    unittest.main()
