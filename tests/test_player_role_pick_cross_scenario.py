"""Cross-scenario isolation for player-selected role distribution."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.bazpors_player_role_pick import (
    ROLE_PICK_CB_PREFIX as BAZPORS_PREFIX,
    handle_player_role_pick_callback as handle_bazpors,
    start_player_role_pick as start_bazpors,
)
from bot.game import GameManager, SEMI_AUTO_SYNTHETIC_UID_BASE
from bot.mason_player_role_pick import (
    ROLE_PICK_CB_PREFIX as MASON_PREFIX,
    handle_player_role_pick_callback as handle_mason,
    start_player_role_pick as start_mason,
)
from bot.models import Player
from bot.mozakere_player_role_pick import (
    ROLE_PICK_CB_PREFIX as MOZAKERE_PREFIX,
    handle_player_role_pick_callback as handle_mozakere,
    start_player_role_pick as start_mozakere,
)


def _cb(uid: int):
    return SimpleNamespace(from_user=SimpleNamespace(id=uid), data="", message=SimpleNamespace())


def _make(scenario: str, *, n: int, host: int):
    gm = GameManager()
    game = gm.create_game(
        host_id=host,
        scenario_name=scenario,
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    for i in range(n):
        gm.add_player(game, Player(user_id=host + i, full_name=f"P{i}", username=None))
    game.seats_finalized = True
    for seat, uid in enumerate(sorted(game.players), start=1):
        game.players[uid].seat = seat
    return gm, game


class CrossScenarioRolePickIsolationTests(unittest.IsolatedAsyncioTestCase):
    def test_callback_prefixes_are_distinct(self) -> None:
        self.assertNotEqual(BAZPORS_PREFIX, MOZAKERE_PREFIX)
        self.assertNotEqual(BAZPORS_PREFIX, MASON_PREFIX)
        self.assertNotEqual(MOZAKERE_PREFIX, MASON_PREFIX)

    async def test_bazpors_callback_ignored_on_mozakere_room(self) -> None:
        _, moz = _make("mozakere", n=10, host=4000)
        start_mozakere(moz)
        bot = AsyncMock()
        before = dict(moz.mozakere_role_number_claims)
        with patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()) as ans:
            await handle_bazpors(_cb(4000), bot, moz, 1)
        self.assertEqual(moz.mozakere_role_number_claims, before)
        self.assertIn(
            "این دکمه برای این اتاق نیست.",
            [c.args[1] for c in ans.await_args_list if len(c.args) > 1],
        )

    async def test_mozakere_callback_ignored_on_mason_room(self) -> None:
        _, mason = _make("masoon", n=12, host=5000)
        start_mason(mason)
        bot = AsyncMock()
        before = dict(mason.mason_role_number_claims)
        with patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()) as ans:
            await handle_mozakere(_cb(5000), bot, mason, 1)
        self.assertEqual(mason.mason_role_number_claims, before)
        self.assertIn(
            "این دکمه برای این اتاق نیست.",
            [c.args[1] for c in ans.await_args_list if len(c.args) > 1],
        )

    async def test_mason_callback_ignored_on_bazpors_room(self) -> None:
        _, baz = _make("bazpors", n=10, host=6000)
        start_bazpors(baz)
        bot = AsyncMock()
        before = dict(baz.bazpors_role_number_claims)
        with patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()) as ans:
            await handle_mason(_cb(6000), bot, baz, 1)
        self.assertEqual(baz.bazpors_role_number_claims, before)
        self.assertIn(
            "این دکمه برای این اتاق نیست.",
            [c.args[1] for c in ans.await_args_list if len(c.args) > 1],
        )

    async def test_state_isolated_across_rooms(self) -> None:
        _, baz = _make("bazpors", n=10, host=7000)
        _, moz = _make("mozakere", n=10, host=8000)
        start_bazpors(baz)
        start_mozakere(moz)
        bot = AsyncMock()
        with (
            patch("bot.player_role_pick_common.safe_callback_answer", new=AsyncMock()),
            patch("bot.player_role_pick_common.safe_send_message", new=AsyncMock()),
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)),
            patch("bot.main.finalize_roles_deal_pipeline", new=AsyncMock()),
        ):
            await handle_bazpors(_cb(7000), bot, baz, 1)
            await handle_mozakere(_cb(8000), bot, moz, 2)
        self.assertIn(1, baz.bazpors_role_number_claims)
        self.assertNotIn(1, moz.mozakere_role_number_claims)
        self.assertIn(2, moz.mozakere_role_number_claims)
        self.assertNotIn(2, baz.bazpors_role_number_claims)


if __name__ == "__main__":
    unittest.main()
