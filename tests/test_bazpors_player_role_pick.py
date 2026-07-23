from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.bazpors_player_role_pick import (
    CLAIM_SOURCE_AUTOMATIC_NON_REAL,
    CLAIM_SOURCE_PLAYER,
    ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX,
    all_real_bazpors_players_have_selected,
    auto_assign_remaining_numbers_to_non_real,
    available_number_button_text,
    build_role_pick_keyboard,
    claimed_number_button_text,
    dispatch_player_role_pick_panels,
    handle_player_role_pick_callback,
    handle_player_role_pick_taken_callback,
    inline_button_supports_style,
    non_real_bazpors_player_uids,
    real_bazpors_player_uids,
    start_player_role_pick,
)
from bot.game import GameManager, SEMI_AUTO_SYNTHETIC_UID_BASE, bazpors_roles_for_count
from bot.main import host_deal_roles_keyboard
from bot.models import Player, Role


def _ready_bazpors_game(*, n: int = 12, real: int | None = None):
    """ساخت لابی بازپرس؛ real تعداد بازیکن واقعی است (باقی synthetic)."""
    gm = GameManager()
    real_n = n if real is None else real
    assert 0 <= real_n <= n
    game = gm.create_game(
        host_id=1000 if real_n > 0 else 1,
        scenario_name="bazpors",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    for i in range(real_n):
        uid = 1000 + i
        gm.add_player(game, Player(user_id=uid, full_name=f"Real{i}", username=None))
    for i in range(n - real_n):
        uid = SEMI_AUTO_SYNTHETIC_UID_BASE - i
        gm.add_player(game, Player(user_id=uid, full_name=f"Synth{i}", username=None))
    game.seats_finalized = True
    for seat, uid in enumerate(sorted(game.players), start=1):
        game.players[uid].seat = seat
    return gm, game


def _cb(uid: int):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=uid),
        data="",
        message=SimpleNamespace(),
    )


class BazporsRolePickUiTests(unittest.TestCase):
    def test_host_deal_keyboard_has_both_buttons_in_bazpors(self) -> None:
        _, game = _ready_bazpors_game(n=10)
        kb = host_deal_roles_keyboard(game)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🎭 پخش نقش‌های تصادفی", labels)
        self.assertIn("انتخاب نقش‌ها توسط بازیکنان", labels)

    def test_random_button_callback_unchanged(self) -> None:
        _, game = _ready_bazpors_game(n=10)
        kb = host_deal_roles_keyboard(game)
        first_cb = kb.inline_keyboard[0][0].callback_data or ""
        self.assertIn(":dr", first_cb)

    def test_start_builds_fixed_hidden_number_role_map(self) -> None:
        _, game = _ready_bazpors_game(n=12)
        err = start_player_role_pick(game)
        self.assertIsNone(err)
        self.assertTrue(game.bazpors_player_role_pick_active)
        self.assertEqual(len(game.bazpors_role_number_map), 12)
        self.assertEqual(
            sorted(game.bazpors_role_number_map),
            list(range(1, 13)),
        )
        dealt = {Role(v) for v in game.bazpors_role_number_map.values()}
        self.assertEqual(dealt, set(bazpors_roles_for_count(12)))

    def test_keyboard_contains_all_numbers(self) -> None:
        _, game = _ready_bazpors_game(n=12)
        start_player_role_pick(game)
        kb = build_role_pick_keyboard(game)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("شماره ۱", labels)
        self.assertIn("شماره ۱۲", labels)
        self.assertEqual(len(labels), 12)

    def test_twelve_players_six_rows_of_two(self) -> None:
        _, game = _ready_bazpors_game(n=12)
        start_player_role_pick(game)
        kb = build_role_pick_keyboard(game)
        self.assertEqual(len(kb.inline_keyboard), 6)
        self.assertTrue(all(len(row) == 2 for row in kb.inline_keyboard))
        numbers = []
        for row in kb.inline_keyboard:
            for btn in row:
                self.assertTrue((btn.callback_data or "").startswith(f"{ROLE_PICK_CB_PREFIX}:"))
                numbers.append(btn.text)
        self.assertEqual(
            numbers,
            [available_number_button_text(n) for n in range(1, 13)],
        )
        if inline_button_supports_style():
            self.assertTrue(all(btn.style == "primary" for row in kb.inline_keyboard for btn in row))

    def test_eleven_players_final_single_button_row(self) -> None:
        _, game = _ready_bazpors_game(n=11)
        start_player_role_pick(game)
        kb = build_role_pick_keyboard(game)
        self.assertEqual(len(kb.inline_keyboard), 6)
        self.assertTrue(all(len(row) == 2 for row in kb.inline_keyboard[:-1]))
        self.assertEqual(len(kb.inline_keyboard[-1]), 1)
        self.assertEqual(
            kb.inline_keyboard[-1][0].text,
            available_number_button_text(11),
        )

    def test_claimed_number_stays_visible_in_place(self) -> None:
        _, game = _ready_bazpors_game(n=12)
        start_player_role_pick(game)
        uid = real_bazpors_player_uids(game)[0]
        game.bazpors_role_number_claims[4] = uid
        game.bazpors_player_role_claims[uid] = {
            "number": 4,
            "role": game.bazpors_role_number_map[4],
            "claimed_at": "t",
            "claim_source": CLAIM_SOURCE_PLAYER,
        }
        kb = build_role_pick_keyboard(game)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        self.assertEqual(len(flat), 12)
        claimed_btn = flat[3]  # index 3 => number 4
        self.assertEqual(claimed_btn.text, claimed_number_button_text(4))
        self.assertTrue(
            (claimed_btn.callback_data or "").startswith(
                f"{ROLE_PICK_TAKEN_CB_PREFIX}:"
            )
        )
        if inline_button_supports_style():
            self.assertEqual(claimed_btn.style, "danger")
            self.assertEqual(flat[0].style, "primary")
        # Position preserved: number 5 still follows
        self.assertEqual(flat[4].text, available_number_button_text(5))


class BazporsRealVsNonRealHelpersTests(unittest.TestCase):
    def test_classifies_via_is_synthetic_player_uid(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=6)
        self.assertEqual(len(real_bazpors_player_uids(game)), 6)
        self.assertEqual(len(non_real_bazpors_player_uids(game)), 4)
        self.assertTrue(all(uid > 0 for uid in real_bazpors_player_uids(game)))
        self.assertTrue(all(uid < 0 for uid in non_real_bazpors_player_uids(game)))


class BazporsRolePickFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_sends_panel_only_to_real_players(self) -> None:
        _, game = _ready_bazpors_game(n=12, real=8)
        start_player_role_pick(game)
        bot = AsyncMock()
        real_uids = real_bazpors_player_uids(game)
        bot.send_message = AsyncMock(
            side_effect=[
                SimpleNamespace(chat=SimpleNamespace(id=uid), message_id=idx)
                for idx, uid in enumerate(real_uids, start=1)
            ]
        )
        with patch(
            "bot.main.finalize_roles_deal_pipeline",
            new=AsyncMock(),
        ):
            await dispatch_player_role_pick_panels(bot, game)
        self.assertEqual(len(game.bazpors_role_pick_panel_messages), 8)
        self.assertEqual(bot.send_message.await_count, 8)
        sent_to = {c.args[0] for c in bot.send_message.await_args_list}
        self.assertEqual(sent_to, set(real_uids))
        self.assertFalse(all_real_bazpors_players_have_selected(game))
        self.assertFalse(game.bazpors_non_real_role_assignment_completed)

    async def test_all_real_room_manual_only_no_automatic(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=10)
        start_player_role_pick(game)
        original_map = dict(game.bazpors_role_number_map)
        bot = AsyncMock()
        game.bazpors_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(game.players.keys(), start=1)
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()),
            patch(
                "bot.main.finalize_roles_deal_pipeline",
                new=AsyncMock(),
            ) as fin,
        ):
            for n, uid in enumerate(list(game.players.keys()), start=1):
                await handle_player_role_pick_callback(_cb(uid), bot, game, n)
        self.assertTrue(
            all(
                info.get("claim_source") == CLAIM_SOURCE_PLAYER
                for info in game.bazpors_player_role_claims.values()
            )
        )
        self.assertEqual(
            sum(
                1
                for info in game.bazpors_player_role_claims.values()
                if info.get("claim_source") == CLAIM_SOURCE_AUTOMATIC_NON_REAL
            ),
            0,
        )
        self.assertEqual(game.bazpors_role_number_map, original_map)
        fin.assert_awaited_once()

    async def test_waits_for_all_real_before_non_real_assignment(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=6)
        start_player_role_pick(game)
        original_map = dict(game.bazpors_role_number_map)
        bot = AsyncMock()
        real_uids = real_bazpors_player_uids(game)
        game.bazpors_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(real_uids, start=1)
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()),
            patch(
                "bot.main.finalize_roles_deal_pipeline",
                new=AsyncMock(),
            ) as fin,
        ):
            for n, uid in enumerate(real_uids[:-1], start=1):
                await handle_player_role_pick_callback(_cb(uid), bot, game, n)
            self.assertFalse(all_real_bazpors_players_have_selected(game))
            self.assertFalse(game.bazpors_non_real_role_assignment_completed)
            for synth in non_real_bazpors_player_uids(game):
                self.assertNotIn(synth, game.bazpors_player_role_claims)
            fin.assert_not_awaited()

            await handle_player_role_pick_callback(_cb(real_uids[-1]), bot, game, 6)
            self.assertTrue(all_real_bazpors_players_have_selected(game))
            self.assertTrue(game.bazpors_non_real_role_assignment_completed)
            self.assertEqual(len(game.bazpors_player_role_claims), 10)
            for synth in non_real_bazpors_player_uids(game):
                self.assertIn(synth, game.bazpors_player_role_claims)
                self.assertEqual(
                    game.bazpors_player_role_claims[synth]["claim_source"],
                    CLAIM_SOURCE_AUTOMATIC_NON_REAL,
                )
            # Real players keep their numbers
            for n, uid in enumerate(real_uids, start=1):
                self.assertEqual(game.bazpors_player_role_claims[uid]["number"], n)
            # Only unclaimed numbers for non-real
            auto_nums = {
                game.bazpors_player_role_claims[uid]["number"]
                for uid in non_real_bazpors_player_uids(game)
            }
            self.assertEqual(auto_nums, {7, 8, 9, 10})
            self.assertEqual(game.bazpors_role_number_map, original_map)
            # No duplicate numbers/roles
            numbers = [
                info["number"] for info in game.bazpors_player_role_claims.values()
            ]
            roles = [info["role"] for info in game.bazpors_player_role_claims.values()]
            self.assertEqual(len(numbers), len(set(numbers)))
            self.assertEqual(Counter(roles), Counter(original_map.values()))
            fin.assert_awaited_once()

    async def test_player_claim_gets_role_message_and_cannot_claim_twice(self) -> None:
        _, game = _ready_bazpors_game(n=10)
        start_player_role_pick(game)
        bot = AsyncMock()
        game.bazpors_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(game.players.keys(), start=1)
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()) as ans,
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()) as send_msg,
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()),
        ):
            uid = next(iter(game.players.keys()))
            await handle_player_role_pick_callback(_cb(uid), bot, game, 1)
            self.assertIn(uid, game.bazpors_player_role_claims)
            send_text = send_msg.await_args.args[2]
            self.assertIn("نقش شما", send_text)
            await handle_player_role_pick_callback(_cb(uid), bot, game, 2)
            self.assertIn(
                "شما قبلا نقش خود را انتخاب کرده‌اید.",
                [c.args[1] for c in ans.await_args_list if len(c.args) > 1],
            )

    async def test_claimed_number_cannot_be_claimed_by_another_player(self) -> None:
        _, game = _ready_bazpors_game(n=10)
        start_player_role_pick(game)
        bot = AsyncMock()
        game.bazpors_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(game.players.keys(), start=1)
        }
        uids = list(game.players.keys())
        with patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()) as ans:
            await handle_player_role_pick_callback(_cb(uids[0]), bot, game, 1)
            await handle_player_role_pick_callback(_cb(uids[1]), bot, game, 1)
            alerts = [c.args[1] for c in ans.await_args_list if len(c.args) > 1]
            self.assertIn(
                "این شماره قبلا انتخاب شده است. لطفا یک شماره دیگر انتخاب کنید.",
                alerts,
            )

    async def test_remaining_panels_keep_claimed_visible(self) -> None:
        _, game = _ready_bazpors_game(n=10)
        start_player_role_pick(game)
        bot = AsyncMock()
        game.bazpors_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(game.players.keys(), start=1)
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()),
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()),
        ):
            await handle_player_role_pick_callback(
                _cb(next(iter(game.players))), bot, game, 1
            )
        found_claimed = False
        for c in bot.edit_message_text.await_args_list:
            kb = c.kwargs.get("reply_markup")
            if kb is None:
                continue
            labels = [b.text for row in kb.inline_keyboard for b in row]
            if claimed_number_button_text(1) in labels:
                found_claimed = True
                self.assertEqual(len(labels), 10)
                break
        self.assertTrue(found_claimed)

    async def test_taken_button_alert_does_not_change_state(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=6)
        start_player_role_pick(game)
        uid = real_bazpors_player_uids(game)[0]
        game.bazpors_role_number_claims[4] = uid
        game.bazpors_player_role_claims[uid] = {
            "number": 4,
            "role": game.bazpors_role_number_map[4],
            "claimed_at": "t",
            "claim_source": CLAIM_SOURCE_PLAYER,
        }
        before_claims = dict(game.bazpors_role_number_claims)
        before_player = dict(game.bazpors_player_role_claims)
        before_map = dict(game.bazpors_role_number_map)
        bot = AsyncMock()
        with patch(
            "bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()
        ) as ans:
            await handle_player_role_pick_taken_callback(
                _cb(real_bazpors_player_uids(game)[1]), bot, game, 4
            )
        self.assertEqual(ans.await_args.args[1], "این شماره قبلاً انتخاب شده است.")
        self.assertTrue(ans.await_args.kwargs.get("show_alert"))
        self.assertEqual(game.bazpors_role_number_claims, before_claims)
        self.assertEqual(game.bazpors_player_role_claims, before_player)
        self.assertEqual(game.bazpors_role_number_map, before_map)
        self.assertFalse(game.bazpors_non_real_role_assignment_completed)

    async def test_style_unavailable_still_builds_keyboard(self) -> None:
        _, game = _ready_bazpors_game(n=12)
        start_player_role_pick(game)
        game.bazpors_role_number_claims[2] = real_bazpors_player_uids(game)[0]
        with patch(
            "bot.player_role_pick_common.inline_button_supports_style",
            return_value=False,
        ):
            kb = build_role_pick_keyboard(game)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        self.assertEqual(flat[1].text, claimed_number_button_text(2))
        self.assertTrue(
            (flat[1].callback_data or "").startswith(f"{ROLE_PICK_TAKEN_CB_PREFIX}:")
        )
        self.assertIsNone(flat[1].style)

    async def test_finalize_persists_roles_and_calls_common_pipeline(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=7)
        start_player_role_pick(game)
        bot = AsyncMock()
        real_uids = real_bazpors_player_uids(game)
        game.bazpors_role_pick_panel_messages = {
            uid: (uid, i) for i, uid in enumerate(real_uids, start=1)
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()),
            patch(
                "bot.main.finalize_roles_deal_pipeline",
                new=AsyncMock(),
            ) as fin,
        ):
            for n, uid in enumerate(real_uids, start=1):
                await handle_player_role_pick_callback(_cb(uid), bot, game, n)
        self.assertFalse(game.bazpors_player_role_pick_active)
        self.assertEqual(len(game.mafia_ids), 3)
        self.assertTrue(all(p.role is not None for p in game.players.values()))
        fin.assert_awaited_once_with(bot, game)

    async def test_mismatch_does_not_corrupt_or_finalize(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=6)
        start_player_role_pick(game)
        # Corrupt: claim one remaining number without a player claim, skewing counts
        real_uids = real_bazpors_player_uids(game)
        for n, uid in enumerate(real_uids, start=1):
            game.bazpors_role_number_claims[n] = uid
            game.bazpors_player_role_claims[uid] = {
                "number": n,
                "role": game.bazpors_role_number_map[n],
                "claimed_at": "t",
                "claim_source": CLAIM_SOURCE_PLAYER,
            }
        # Steal one remaining number from pool (no player entry)
        game.bazpors_role_number_claims[7] = -999
        before_claims = dict(game.bazpors_player_role_claims)
        before_map = dict(game.bazpors_role_number_map)
        ok = auto_assign_remaining_numbers_to_non_real(game)
        self.assertFalse(ok)
        self.assertFalse(game.bazpors_non_real_role_assignment_completed)
        self.assertEqual(game.bazpors_player_role_claims, before_claims)
        self.assertEqual(game.bazpors_role_number_map, before_map)
        for synth in non_real_bazpors_player_uids(game):
            self.assertNotIn(synth, game.bazpors_player_role_claims)

    async def test_auto_assign_idempotent_under_concurrent_last_claims(self) -> None:
        _, game = _ready_bazpors_game(n=10, real=2)
        start_player_role_pick(game)
        bot = AsyncMock()
        uids = real_bazpors_player_uids(game)
        game.bazpors_role_pick_panel_messages = {
            uids[0]: (uids[0], 1),
            uids[1]: (uids[1], 2),
        }
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()),
            patch(
                "bot.main.finalize_roles_deal_pipeline",
                new=AsyncMock(),
            ) as fin,
        ):
            await asyncio.gather(
                handle_player_role_pick_callback(_cb(uids[0]), bot, game, 1),
                handle_player_role_pick_callback(_cb(uids[1]), bot, game, 2),
            )
        self.assertEqual(fin.await_count, 1)
        self.assertEqual(len(game.bazpors_player_role_claims), 10)
        self.assertTrue(game.bazpors_non_real_role_assignment_completed)
        numbers = [info["number"] for info in game.bazpors_player_role_claims.values()]
        self.assertEqual(sorted(numbers), list(range(1, 11)))


if __name__ == "__main__":
    unittest.main()
