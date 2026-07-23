"""چرخهٔ عمر تفنگ تفنگدار — فقط سناریوی ماسون."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_entry import (
    MASON_NIGHT_WAIT_TEXT,
    night_action_holder_uids,
    reset_mason_current_night_selections,
)
from bot.mason_night_role import dispatch_mason_gunner_panel
from bot.models import Player, Role
from bot.roles import mason_gunner as ms_gn


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
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
    return game


def _night1_give_gun(game, gm, *, gunner_uid=10, holder_uid=20) -> None:
    gunner = game.players[gunner_uid]
    holder = game.players[holder_uid]
    ms_gn.commit_mason_gunner_target(game, gunner, holder)
    ms_gn.prepare_mason_day_gun_from_night_choices(game)


class MasonGunnerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_gun_spent_on_panel_delivery_not_shot(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        victim = _p(30, "Victim", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, victim)
        _night1_give_gun(game, gm)
        self.assertFalse(ms_gn.mason_gun_is_spent(game))
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))
        ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))

    def test_shot_after_delivery_stays_spent(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        victim = _p(30, "Victim", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, victim)
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        game.mason_day_gun_sabotaged = True
        ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))

    def test_prepare_after_spent_does_not_reset_lifecycle(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        victim = _p(30, "Victim", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, victim)
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        game.mason_gunner_night_target_uid = 30
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))

    def test_holder_death_after_delivery_keeps_gun_spent(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        holder.is_alive = False
        ms_gn.refresh_mason_day_gun_holder_if_eliminated(game)
        self.assertTrue(ms_gn.mason_gun_is_spent(game))
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))

    def test_holder_alive_with_delivered_gun_blocks_gunner(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        other = _p(30, "Other", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, other)
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        self.assertFalse(ms_gn.mason_gunner_can_give_gun(game))
        self.assertFalse(
            ms_gn.commit_mason_gunner_target(game, gunner, other)
        )
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        self.assertEqual(ms_gn.mason_day_gun_holder_uid(game), 20)

    def test_night_selection_reset_preserves_gun_spent(self) -> None:
        game = _mason_game(self.gm)
        game.mason_gun_spent = True
        game.mason_day_gun_used = True
        game.mason_day_gun_holder_uid = 20
        reset_mason_current_night_selections(game)
        self.assertTrue(game.mason_gun_spent)
        self.assertTrue(game.mason_day_gun_used)
        self.assertEqual(game.mason_day_gun_holder_uid, 20)

    def test_spent_gunner_excluded_from_night_action_holders(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gunner = _p(10, "Gn", Role.GUNMAN)
        holder = _p(20, "Holder", Role.TOWN_SIMPLE)
        victim = _p(30, "Victim", Role.TOWN_SIMPLE)
        gm.add_player(game, gunner)
        gm.add_player(game, holder)
        gm.add_player(game, victim)
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        holders = night_action_holder_uids(game)
        self.assertNotIn(10, holders)

    def test_new_game_resets_gun_spent(self) -> None:
        game = _mason_game(self.gm)
        for i in range(12):
            self.gm.add_player(game, _p(100 + i, f"P{i}", Role.TOWN_SIMPLE))
        game.mason_gun_spent = True
        game.mason_day_gun_used = True
        self.gm.assign_roles(game)
        self.assertFalse(game.mason_gun_spent)
        self.assertFalse(game.mason_day_gun_used)


class MasonGunnerDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_spent_gunner_auto_confirmed_no_pick_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(20, "Holder", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Victim", Role.TOWN_SIMPLE))
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        holder = game.players[20]
        victim = game.players[30]
        ms_gn.resolve_mason_day_gun_shot(game, holder, victim)
        bot = MagicMock()
        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as reg:
            await dispatch_mason_gunner_panel(bot, game, gm)
        reg.assert_not_awaited()
        self.assertTrue(game.mason_night_gunner_confirmed)

    async def test_spent_gunner_gets_wait_panel_not_action_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(20, "Holder", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Victim", Role.TOWN_SIMPLE))
        _night1_give_gun(game, gm)
        ms_gn.mark_mason_gun_delivered_to_holder(game)
        ms_gn.resolve_mason_day_gun_shot(
            game, game.players[20], game.players[30]
        )
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.mason_night_gunner_confirmed = True
        captured: list[tuple[int, str]] = []

        async def _capture(_bot, _game, uid, _ui, text, _kb, **kw):
            captured.append((uid, text))

        with patch(
            "bot.mason_night_entry.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            from bot.mason_night_entry import _dispatch_mason_wait_panels

            await _dispatch_mason_wait_panels(AsyncMock(), game)

        gunner_msgs = [t for uid, t in captured if uid == 10]
        self.assertEqual(len(gunner_msgs), 0)

    async def test_synthetic_gunner_spent_same_as_real(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920010
        gm.add_player(game, _p(syn, "SynGn", Role.GUNMAN))
        gm.add_player(game, _p(20, "Holder", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Victim", Role.TOWN_SIMPLE))
        game.mason_gun_spent = True
        self.assertTrue(is_synthetic_player_uid(syn))
        bot = MagicMock()
        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as reg:
            await dispatch_mason_gunner_panel(bot, game, gm)
        reg.assert_not_awaited()
        self.assertTrue(game.mason_night_gunner_confirmed)


if __name__ == "__main__":
    unittest.main()
