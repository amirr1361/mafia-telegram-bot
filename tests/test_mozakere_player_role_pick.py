"""Mozakere player-selected role-number distribution."""

from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.game import GameManager, SEMI_AUTO_SYNTHETIC_UID_BASE, mozakere_roles_for_count
from bot.main import host_deal_roles_keyboard
from bot.models import Player, Role
from bot.mozakere_player_role_pick import (
    CLAIM_SOURCE_AUTOMATIC_NON_REAL,
    CLAIM_SOURCE_PLAYER,
    ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX,
    all_real_mozakere_players_have_selected,
    auto_assign_remaining_numbers_to_non_real,
    available_number_button_text,
    build_role_pick_keyboard,
    claimed_number_button_text,
    dispatch_player_role_pick_panels,
    handle_player_role_pick_callback,
    handle_player_role_pick_taken_callback,
    inline_button_supports_style,
    start_player_role_pick,
)
from bot.player_role_pick_common import non_real_player_uids, real_player_uids


def _ready_mozakere(*, n: int = 12, real: int | None = None):
    gm = GameManager()
    real_n = n if real is None else real
    game = gm.create_game(
        host_id=2000 if real_n > 0 else 1,
        scenario_name="mozakere",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    for i in range(real_n):
        gm.add_player(game, Player(user_id=2000 + i, full_name=f"R{i}", username=None))
    for i in range(n - real_n):
        gm.add_player(
            game,
            Player(
                user_id=SEMI_AUTO_SYNTHETIC_UID_BASE - i,
                full_name=f"S{i}",
                username=None,
            ),
        )
    game.seats_finalized = True
    for seat, uid in enumerate(sorted(game.players), start=1):
        game.players[uid].seat = seat
    return gm, game


def _cb(uid: int):
    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data="", message=SimpleNamespace())


class MozakereRolePickUiTests(unittest.TestCase):
    def test_helper_sees_both_buttons(self) -> None:
        _, game = _ready_mozakere(n=10)
        labels = [
            btn.text for row in host_deal_roles_keyboard(game).inline_keyboard for btn in row
        ]
        self.assertIn("🎭 پخش نقش‌های تصادفی", labels)
        self.assertIn("انتخاب نقش‌ها توسط بازیکنان", labels)

    def test_generates_correct_mozakere_role_list(self) -> None:
        _, game = _ready_mozakere(n=12)
        start_player_role_pick(game)
        dealt = [Role(v) for v in game.mozakere_role_number_map.values()]
        self.assertEqual(Counter(dealt), Counter(mozakere_roles_for_count(12)))
        self.assertEqual(sorted(game.mozakere_role_number_map), list(range(1, 13)))

    def test_two_column_layout_and_styles(self) -> None:
        _, game = _ready_mozakere(n=12)
        start_player_role_pick(game)
        kb = build_role_pick_keyboard(game)
        self.assertEqual(len(kb.inline_keyboard), 6)
        self.assertTrue(all(len(row) == 2 for row in kb.inline_keyboard))
        flat = [b for row in kb.inline_keyboard for b in row]
        self.assertTrue(all((b.callback_data or "").startswith(f"{ROLE_PICK_CB_PREFIX}:") for b in flat))
        if inline_button_supports_style():
            self.assertTrue(all(b.style == "primary" for b in flat))
        game.mozakere_role_number_claims[4] = real_player_uids(game)[0]
        kb2 = build_role_pick_keyboard(game)
        claimed = [b for row in kb2.inline_keyboard for b in row][3]
        self.assertEqual(claimed.text, claimed_number_button_text(4))
        self.assertTrue((claimed.callback_data or "").startswith(f"{ROLE_PICK_TAKEN_CB_PREFIX}:"))
        if inline_button_supports_style():
            self.assertEqual(claimed.style, "danger")


class MozakereRolePickFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_panels_only_to_real_and_waits_before_synthetic(self) -> None:
        _, game = _ready_mozakere(n=12, real=8)
        start_player_role_pick(game)
        original_map = dict(game.mozakere_role_number_map)
        bot = AsyncMock()
        real_uids = real_player_uids(game)
        bot.send_message = AsyncMock(
            side_effect=[
                SimpleNamespace(chat=SimpleNamespace(id=uid), message_id=i)
                for i, uid in enumerate(real_uids, start=1)
            ]
        )
        with patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()):
            await dispatch_player_role_pick_panels(bot, game)
        self.assertEqual(bot.send_message.await_count, 8)
        game.mozakere_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(real_uids, start=1)
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)),
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()) as fin,
        ):
            for n, uid in enumerate(real_uids[:-1], start=1):
                await handle_player_role_pick_callback(_cb(uid), bot, game, n)
            self.assertFalse(all_real_mozakere_players_have_selected(game))
            for synth in non_real_player_uids(game):
                self.assertNotIn(synth, game.mozakere_player_role_claims)
            fin.assert_not_awaited()
            await handle_player_role_pick_callback(_cb(real_uids[-1]), bot, game, 8)
            self.assertTrue(game.mozakere_non_real_role_assignment_completed)
            self.assertEqual(len(game.mozakere_player_role_claims), 12)
            self.assertEqual(game.mozakere_role_number_map, original_map)
            roles = [info["role"] for info in game.mozakere_player_role_claims.values()]
            self.assertEqual(Counter(roles), Counter(original_map.values()))
            fin.assert_awaited_once()

    async def test_one_choice_and_stale_and_taken(self) -> None:
        _, game = _ready_mozakere(n=10, real=6)
        start_player_role_pick(game)
        uids = real_player_uids(game)
        bot = AsyncMock()
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()) as ans,
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)) as send_role,
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()),
        ):
            await handle_player_role_pick_callback(_cb(uids[0]), bot, game, 1)
            send_role.assert_awaited()
            await handle_player_role_pick_callback(_cb(uids[0]), bot, game, 2)
            await handle_player_role_pick_callback(_cb(uids[1]), bot, game, 1)
            await handle_player_role_pick_taken_callback(_cb(uids[1]), bot, game, 1)
        alerts = [c.args[1] for c in ans.await_args_list if len(c.args) > 1]
        self.assertIn("شما قبلا نقش خود را انتخاب کرده‌اید.", alerts)
        self.assertIn(
            "این شماره قبلا انتخاب شده است. لطفا یک شماره دیگر انتخاب کنید.",
            alerts,
        )
        self.assertIn("این شماره قبلاً انتخاب شده است.", alerts)
        self.assertEqual(game.mozakere_player_role_claims[uids[0]]["number"], 1)

    async def test_concurrent_first_claim_wins_and_finalizes_once(self) -> None:
        _, game = _ready_mozakere(n=10, real=2)
        start_player_role_pick(game)
        uids = real_player_uids(game)
        bot = AsyncMock()
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)),
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()) as fin,
        ):
            await asyncio.gather(
                handle_player_role_pick_callback(_cb(uids[0]), bot, game, 1),
                handle_player_role_pick_callback(_cb(uids[1]), bot, game, 2),
            )
        self.assertEqual(fin.await_count, 1)
        self.assertEqual(len(game.mozakere_player_role_claims), 10)
        self.assertTrue(all(p.role is not None for p in game.players.values()))

    async def test_mozakere_state_initialized_on_finalize(self) -> None:
        gm, game = _ready_mozakere(n=10, real=10)
        start_player_role_pick(game)
        bot = AsyncMock()
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)),
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()),
        ):
            for n, uid in enumerate(real_player_uids(game), start=1):
                await handle_player_role_pick_callback(_cb(uid), bot, game, n)
        self.assertFalse(game.mozakere_negotiation_used)
        self.assertEqual(game.mozakere_sniper_shots_used, 0)
        self.assertEqual(game.mozakere_mafia_recruit_ids, set())
        self.assertEqual(len(game.mafia_ids), 3)


if __name__ == "__main__":
    unittest.main()
