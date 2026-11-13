"""Phase 4 — Namayande-10 fork: activation, identity, elim-report access.

Covers the public routing activation (Namayande -> 10 players only), fork
identity in role displays, eliminated-player report invitations (real and
synthetic players + Observer), report callback authorization, immutable
cutoffs, extended seeded equivalence, and snapshot restore into a manager.
All storage is isolated; production data is never touched.
"""

from __future__ import annotations

import json
import random
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot import db
from bot.game import GameManager
from bot.models import Phase, Player, Role
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


def _callback(actor_uid: int) -> MagicMock:
    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = actor_uid
    cb.from_user.full_name = f"U{actor_uid}"
    cb.from_user.username = None
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.chat = MagicMock()
    cb.message.chat.type = "private"
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


def _register_sends(mod):
    """Capture sends + callback answers made through the fork elim module."""
    sends: list[tuple[int, str, object]] = []
    answers: list[tuple[object, bool]] = []

    async def capture_send(bot, chat_id, text, *args, **kwargs):
        sends.append((chat_id, text, kwargs.get("reply_markup")))
        return True

    async def capture_answer(cb, text=None, *, show_alert=False, **kwargs):
        answers.append((text, show_alert))
        return True

    patcher_send = patch(f"{mod}.safe_send_message", new=capture_send)
    patcher_answer = patch(f"{mod}.safe_callback_answer", new=capture_answer)
    return sends, answers, patcher_send, patcher_answer


FORK_ONLY_LABELS = (
    "رئیس مافیا",
    "یاغی",
    "هکر",
    "وکیل",
    "راهنما",
    "محافظ",
    "مین‌گذار",
)
CLASSIC_ONLY_LABELS = ("دان مافیا", "هکر مافیا", "وکیل شهروند")
OLD_FORK_LABELS = (
    "ناتو",
    "شیاد",
    "بازپرس",
    "هانتر (شهروند)",
    "کاراگاه",
    "رویین تن",
)


class ActivationRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_fork_room_created_only_for_count_10(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=5001,
            scenario_name="namayande",
            max_players=10,
            host_full_name="H",
            nam10_no_host=True,
        )
        self.assertIsNotNone(game)
        self.assertEqual(game.nmnd_host_mode, "no_host")
        self.assertTrue(is_namayande10_no_host_room(game))
        # expansion: 11/12/13 also become fork rooms
        for n in (11, 12, 13):
            game_n = gm.create_game(
                host_id=5001 + n,
                scenario_name="namayande",
                max_players=n,
                host_full_name="H",
                nam10_no_host=True,
            )
            self.assertIsNotNone(game_n, n)
            self.assertTrue(is_namayande10_no_host_room(game_n), n)
        # hard guard: no other count may become a fork room
        for n in (9, 14, 16):
            self.assertIsNone(gm.create_game(
                host_id=5001 + n,
                scenario_name="namayande",
                max_players=n,
                host_full_name="H",
                nam10_no_host=True,
            ))

    async def test_classic_namayande_counts_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=5100,
            scenario_name="namayande",
            max_players=11,
            host_full_name="H",
        )
        self.assertIsNone(game.nmnd_host_mode)
        self.assertFalse(is_namayande10_no_host_room(game))
        for i in range(11):
            gm.add_player(game, Player(user_id=6000 + i, full_name=f"P{i}", username=None))
        game.seats_finalized = True
        gm.assign_roles(game)
        from bot.game import namayande_roles_for_count

        expected = namayande_roles_for_count(11)
        roles = [p.role for p in game.players.values()]
        self.assertEqual(sorted(r.value for r in roles), sorted(r.value for r in expected))
        # classic composition, not the fork snapshot
        self.assertIn(Role.DON_MAFIA, roles)
        self.assertNotIn(Role.MAFIA_BOSS, roles)

    async def test_fork_roster_and_join_preview_identity(self) -> None:
        from bot.game import role_roster_banner_text
        from bot.main import build_join_preview_html

        gm = GameManager()
        fork_banner = role_roster_banner_text(
            "namayande", 10, gm, nam10_no_host=True
        )
        self.assertIn("سناریو نماینده", fork_banner)
        for label in FORK_ONLY_LABELS:
            self.assertIn(label, fork_banner)
        for label in CLASSIC_ONLY_LABELS:
            self.assertNotIn(label, fork_banner)
        for label in OLD_FORK_LABELS:
            self.assertNotIn(label, fork_banner)

        classic = role_roster_banner_text("namayande", 10, gm)
        for label in CLASSIC_ONLY_LABELS:
            self.assertIn(label, classic)
        for label in ("ناتو", "شیاد", "رویین تن"):
            self.assertNotIn(label, classic)

        game = gm.create_game(
            host_id=5300,
            scenario_name="namayande",
            max_players=10,
            host_full_name="H",
            nam10_no_host=True,
        )
        with patch("bot.main.manager", gm), patch("bot.app_state.manager", gm):
            preview = build_join_preview_html(game)
        self.assertIn("سناریو: نماینده", preview)
        for label in FORK_ONLY_LABELS:
            self.assertIn(label, preview)
        for label in CLASSIC_ONLY_LABELS:
            self.assertNotIn(label, preview)

    async def test_observer_mirror_gate_fork_aware(self) -> None:
        from bot.observer_delivery import (
            game_observer_mirror_active,
            no_host_observer_registered,
        )

        game = GameManager().create_game(
            host_id=5400,
            scenario_name="namayande",
            max_players=10,
            host_full_name="H",
            nam10_no_host=True,
        )
        game.observer_prompt_status = "registered"
        self.assertFalse(no_host_observer_registered(game))
        game.observer_user_id = 7700
        self.assertTrue(no_host_observer_registered(game))
        self.assertTrue(game_observer_mirror_active(game))
        # observer skipped stays inactive
        game2 = GameManager().create_game(
            host_id=5401,
            scenario_name="namayande",
            max_players=10,
            host_full_name="H",
            nam10_no_host=True,
        )
        game2.observer_user_id = 7701
        game2.observer_prompt_status = "skipped"
        self.assertFalse(no_host_observer_registered(game2))


class Phase4HarnessTests(unittest.IsolatedAsyncioTestCase):
    def _fork_room(self):
        from tests.nam10_flow_harness import Nam10FlowHarness

        return Nam10FlowHarness.build(GameManager())

    def _dead_real_uid(self, g):
        return min(uid for uid in g.players if uid > 0)

    async def test_elim_invite_real_synthetic_observer_dedup(self) -> None:
        from bot.nam10 import no_host_elim_report as elim

        h = self._fork_room()
        g = h.game
        g.observer_user_id = 7099
        g.observer_prompt_status = "registered"
        with patch("bot.app_state.manager", h.gm):
            # real dead player
            real_uid = self._dead_real_uid(g)
            g.players[real_uid].is_alive = False
            sends, answers, ps, pa = _register_sends("bot.nam10.no_host_elim_report")
            with ps, pa:
                sent = await elim.send_nam10_elim_report_invitation(
                    h.bot, g, h.gm, real_uid
                )
            self.assertTrue(sent)
            targets = [uid for uid, _, _ in sends]
            self.assertIn(real_uid, targets)
            self.assertIn(7099, targets)  # observer copy
            self.assertTrue(any("گزارش بازی" in text for _, text, _ in sends))
            # replay is a no-op (dedup)
            sends.clear()
            with ps, pa:
                sent2 = await elim.send_nam10_elim_report_invitation(
                    h.bot, g, h.gm, real_uid
                )
            self.assertFalse(sent2)
            self.assertEqual(sends, [])
            # synthetic dead player: no DM, observer copy only
            syn_uid = next(
                uid for uid, p in g.players.items() if p.user_id < 0 and p.is_alive
            )
            g.players[syn_uid].is_alive = False
            sends2, _, ps2, _ = _register_sends("bot.nam10.no_host_elim_report")
            with ps2:
                sent3 = await elim.send_nam10_elim_report_invitation(
                    h.bot, g, h.gm, syn_uid
                )
            self.assertTrue(sent3)
            targets2 = [uid for uid, _, _ in sends2]
            self.assertNotIn(syn_uid, targets2)
            self.assertIn(7099, targets2)

    async def test_elim_callback_authorization_and_immutable_cutoff(self) -> None:
        from bot.nam10 import no_host_elim_report as elim

        h = self._fork_room()
        g = h.game
        dead_uid = self._dead_real_uid(g)
        other_uid = next(
            uid for uid, p in g.players.items() if p.is_alive and uid != dead_uid
        )
        with patch("bot.app_state.manager", h.gm):
            g.players[dead_uid].is_alive = False
            entry = elim.capture_nam10_elim_report_cutoff(g, h.gm, dead_uid)
            self.assertIsNotNone(entry)
            html1 = elim.build_nam10_elim_cutoff_report_html(g, h.gm)
            self.assertIn("سناریو: نماینده", html1)
            self.assertNotIn("سناریو: بازپرس", html1)
            gts = elim._game_created_ts(g)
            # later mutations must not change the resolved report
            late_uid = other_uid
            g.players[late_uid].is_alive = False
            self.assertEqual(
                elim.resolve_nam10_elim_report_html(g, dead_uid, gts=gts),
                html1,
            )
            # wrong gts (fresh room reusing the code) is rejected
            self.assertIsNone(
                elim.resolve_nam10_elim_report_html(g, dead_uid, gts=gts + 10)
            )
            # dead player can read
            sends, _, ps, _ = _register_sends("bot.nam10.no_host_elim_report")
            cb_dead = _callback(dead_uid)
            with ps:
                await elim.handle_nam10_elim_report_callback(
                    cb_dead, h.bot, g, as_uid=dead_uid, gts=gts
                )
            self.assertTrue(any(uid == dead_uid and html1 in text for uid, text, _ in sends))
            # alive player denied
            sends.clear()
            cb_alive = _callback(other_uid)
            with ps:
                await elim.handle_nam10_elim_report_callback(
                    cb_alive, h.bot, g, as_uid=dead_uid, gts=gts
                )
            self.assertEqual(sends, [])
            # registered observer can read another player's report
            cb_obs = _callback(7099)
            g.observer_user_id = 7099
            g.observer_prompt_status = "registered"
            with ps:
                await elim.handle_nam10_elim_report_callback(
                    cb_obs, h.bot, g, as_uid=dead_uid, gts=gts
                )
            self.assertTrue(any(uid == 7099 and html1 in text for uid, text, _ in sends))
            # unregistered outsider denied
            sends.clear()
            cb_rnd = _callback(4242)
            with ps:
                await elim.handle_nam10_elim_report_callback(
                    cb_rnd, h.bot, g, as_uid=dead_uid, gts=gts
                )
            self.assertEqual(sends, [])

    async def test_report_route_shared_router_delegates_fork(self) -> None:
        import inspect

        from bot import bazpors_elim_report as shared

        src = inspect.getsource(shared.cb_bazpors_elim_report)
        self.assertIn("cb_nam10_elim_report", src)
        self.assertIn("is_namayande10_no_host_room", src)

    async def test_snapshot_restore_into_manager(self) -> None:
        from bot.game_snapshot import (
            persist_game_snapshot,
            restore_games_into_manager,
        )

        h1 = self._fork_room()
        g = h1.game
        g_nmnd_step = g.nmnd_narrator_step
        persist_game_snapshot(g, reason="test")
        code = g.room_code
        # drop from the first manager so restore brings it back
        h1.gm.games.pop(code, None)
        h1.gm.host_to_room.pop(g.host_id, None)
        m2 = GameManager()
        restored = restore_games_into_manager(m2)
        self.assertIn(code, restored)
        back = m2.get_game(code)
        self.assertIsNotNone(back)
        self.assertTrue(is_namayande10_no_host_room(back))
        self.assertEqual(back.nmnd_narrator_step, g_nmnd_step)
        self.assertEqual(len(back.players), 10)


class Phase4ExtendedEquivalenceTests(unittest.IsolatedAsyncioTestCase):
    async def _paired_run(self, seed: int):
        from tests.nam10_flow_harness import Nam10FlowHarness, _telegram_patches
        from tests.nam10_game_loop import run_until_natural_end
        from tests.no_host_flow_harness import NoHostFlowHarness, _telegram_patches as bp_pat
        from tests.no_host_game_loop import run_until_natural_end as bp_run

        random.seed(seed)
        h_n = Nam10FlowHarness.build(GameManager())
        random.seed(seed)
        h_b = NoHostFlowHarness.build(GameManager())
        async with _telegram_patches(h_n.gm):
            w_n = await run_until_natural_end(h_n)
            a_n = sorted(p.role.value for p in h_n.game.players.values() if p.is_alive)
            r_n = (h_n.game.nmnd_narrator_night_count, h_n.game.nmnd_narrator_host_day)
        async with bp_pat(h_b.gm):
            w_b = await bp_run(h_b)
            a_b = sorted(p.role.value for p in h_b.game.players.values() if p.is_alive)
            r_b = (h_b.game.bazpors_narrator_night_count, h_b.game.bazpors_narrator_host_day)
        return w_n, a_n, r_n, w_b, a_b, r_b

    async def test_paired_equivalence_extended_seeds(self) -> None:
        for seed in (42, 101, 5):
            w_n, a_n, r_n, w_b, a_b, r_b = await self._paired_run(seed)
            self.assertEqual(w_n, w_b, f"seed {seed}: winner mismatch")
            self.assertEqual(a_n, a_b, f"seed {seed}: alive mismatch")
            self.assertEqual(r_n, r_b, f"seed {seed}: rounds mismatch")
            self.assertIn(w_n, ("mafia", "citizen"))


if __name__ == "__main__":
    unittest.main()
