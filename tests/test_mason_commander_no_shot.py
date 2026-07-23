"""فرمانده — وقتی اسنایپر هدفی ندارد."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_role import (
    MASON_COMMANDER_SNIPER_NO_SHOT_TEXT,
    MSC_INFO_OK,
    dispatch_mason_commander_panel,
    dispatch_mason_night_role,
)
from bot.models import Player, Role


def _p(uid: int, name: str, role: Role) -> Player:
    return Player(user_id=uid, full_name=name, username=None, role=role)


def _mason_game(gm: GameManager, *, n: int = 16):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.no_host_night_parallel_collect_active = True
    return game


class MasonCommanderNoShotTests(unittest.IsolatedAsyncioTestCase):
    async def test_info_panel_when_sniper_has_zero_targets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "Cmd", Role.COMMANDER))
        gm.add_player(game, _p(30, "T", Role.TOWN_SIMPLE))
        game.mason_night_sniper_confirmed = True
        bot = MagicMock()
        captured: list[tuple[str, list[str]]] = []

        async def _cap(_b, _g, uid, _ui, text, kb, **kw):
            if uid == 20:
                btns = [b.text for row in kb.inline_keyboard for b in row] if kb else []
                captured.append((text, btns))

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_cap,
        ):
            await dispatch_mason_commander_panel(bot, game, gm)

        self.assertEqual(len(captured), 1)
        text, btns = captured[0]
        self.assertIn(MASON_COMMANDER_SNIPER_NO_SHOT_TEXT, text)
        self.assertTrue(any("اوکی" in b for b in btns))
        self.assertFalse(game.mason_night_commander_confirmed)

    async def test_observer_ok_confirms_commander(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        cmd_uid = -920020
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(cmd_uid, "Cmd", Role.COMMANDER))
        game.mason_night_commander_panel_sent = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=cmd_uid,
                actor_uid=999,
                act=MSC_INFO_OK,
                tid=0,
            )
        self.assertTrue(game.mason_night_commander_confirmed)
