"""Room 00 — 18-player Mason Sniper/Commander shot capacity regression."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_multi_select_panels import build_mason_multi_select_panel_text
from bot.mason_night_role import (
    MASON_NO_NIGHT_PICK_WAIT_TEXT,
    _show_mason_commander_panel,
    _show_mason_sniper_panel,
    dispatch_mason_commander_panel,
)
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_sniper as ms_sn


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _room00_game(gm: GameManager):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=18,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    return game


class MasonSniper18PlayerCapacityTests(unittest.TestCase):
    def test_total_bullets_is_three(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        self.assertEqual(ms_sn.mason_sniper_total_bullets(game), 3)
        self.assertEqual(ms_sn.mason_sniper_bullet_limit(game), 3)

    def test_max_targets_this_night_allows_three_when_full(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        self.assertEqual(ms_sn.mason_sniper_max_targets_this_night(game), 3)

    def test_max_targets_follows_remaining_not_hard_capped_at_two(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        game.mason_sniper_bullets_spent = 1
        self.assertEqual(ms_sn.mason_sniper_bullets_remaining(game), 2)
        self.assertEqual(ms_sn.mason_sniper_max_targets_this_night(game), 2)

    def test_three_targets_in_one_night_when_three_remain(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "C", Role.TOWN_SIMPLE))
        self.assertTrue(
            ms_sn.commit_mason_sniper_night_selection(game, [20, 30, 40])
        )
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [20, 30, 40])

    def test_two_spent_leaves_one_remaining(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        game.mason_sniper_bullets_spent = 2
        self.assertEqual(ms_sn.mason_sniper_bullets_remaining(game), 1)
        self.assertEqual(ms_sn.mason_sniper_max_targets_this_night(game), 1)

    def test_three_spent_leaves_zero(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        game.mason_sniper_bullets_spent = 3
        self.assertEqual(ms_sn.mason_sniper_bullets_remaining(game), 0)
        self.assertFalse(ms_sn.mason_sniper_needs_night_pick(game))

    def test_14_player_still_two_total_bullets(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=14,
        )
        assert game is not None
        self.assertEqual(ms_sn.mason_sniper_total_bullets(game), 2)
        self.assertEqual(ms_sn.mason_sniper_max_targets_this_night(game), 2)


class MasonSniper18PlayerPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_sniper_panel_shows_three_of_three_remaining(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        captured: list[str] = []

        async def _sync(_bot, _game, _ui, _uid, text, _kb):
            captured.append(text)

        with patch(
            "bot.mason_night_role.sync_role_mirror_panel",
            side_effect=_sync,
        ):
            await _show_mason_sniper_panel(AsyncMock(), game, gm, 10)

        self.assertIn("تعداد تیرهای باقی‌مانده شما: ۳ از ۳", captured[0])
        self.assertIn("انتخاب‌های مجاز شما: 0 از 3", captured[0])

    async def test_commander_inherit_panel_shows_same_remaining_count(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        captured: list[str] = []

        async def _sync(_bot, _game, _ui, _uid, text, _kb):
            captured.append(text)

        with patch(
            "bot.mason_night_role.sync_role_mirror_panel",
            side_effect=_sync,
        ):
            await _show_mason_commander_panel(AsyncMock(), game, gm, 51)

        self.assertIn("تعداد تیرهای باقی‌مانده شما: ۳ از ۳", captured[0])
        self.assertIn("انتخاب‌های مجاز شما: 0 از 3", captured[0])

    async def test_commander_inherit_three_direct_shots(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "C", Role.TOWN_SIMPLE))
        self.assertTrue(
            ms_cmd.commit_mason_commander_direct_shots(game, [20, 30, 40])
        )
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 3)

    async def test_commander_zero_bullets_gets_no_action_panel(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        game.mason_night_sniper_confirmed = True
        bot = MagicMock()
        captured: list[str] = []

        async def _cap(_b, _g, _uid, _ui, text, _kb, **kw):
            captured.append(text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_cap,
        ):
            await dispatch_mason_commander_panel(bot, game, gm)

        self.assertTrue(any(MASON_NO_NIGHT_PICK_WAIT_TEXT in t for t in captured))


class MasonSniperPanelProgressTests(unittest.TestCase):
    def test_progress_line_uses_three_for_18_player_room(self) -> None:
        gm = GameManager()
        game = _room00_game(gm)
        text = build_mason_multi_select_panel_text(
            ms_sn.build_mason_sniper_remaining_bullets_line(game),
            game,
            gm,
            [],
            ms_sn.mason_sniper_max_targets_this_night(game),
        )
        self.assertIn("انتخاب‌های مجاز شما: 0 از 3", text)


if __name__ == "__main__":
    unittest.main()
