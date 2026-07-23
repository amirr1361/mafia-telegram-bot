"""ریست انتخاب‌های شبانهٔ ماسون بین شب‌ها — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.mason_multi_select_panels import (
    build_mason_multi_select_panel_text,
    mason_multi_select_none_button_label,
)
from bot.mason_night_entry import reset_mason_current_night_selections
from bot.mason_night_role import _show_mason_sniper_panel
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_sniper as ms_sn


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
    return game


class MasonNightSelectionResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _night1_carryover_state(self, game) -> None:
        game.mason_sniper_night_selected_uids = [20, 30]
        game.mason_commander_night_approved_uids = [20, 30]
        game.mason_doctor_night_save_uids = [40]
        game.mason_sniper_bullets_spent = 2
        game.mason_doctor_self_save_count = 1

    def test_sniper_selections_reset_between_nights(self) -> None:
        game = _mason_game(self.gm)
        self._night1_carryover_state(game)
        reset_mason_current_night_selections(game)
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [])
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])
        self.assertEqual(game.mason_sniper_bullets_spent, 2)

    def test_doctor_selections_reset_between_nights(self) -> None:
        game = _mason_game(self.gm)
        self._night1_carryover_state(game)
        reset_mason_current_night_selections(game)
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(game), [])
        self.assertEqual(game.mason_doctor_self_save_count, 1)

    def test_commander_approvals_reset_between_nights(self) -> None:
        game = _mason_game(self.gm)
        self._night1_carryover_state(game)
        reset_mason_current_night_selections(game)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])

    def test_sniper_night2_panel_starts_fresh(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "Erfan", Role.GODFATHER))
        gm.add_player(game, _p(30, "Farahani", Role.DETECTIVE))
        game.mason_sniper_night_selected_uids = [20, 30]
        reset_mason_current_night_selections(game)

        selected = ms_sn.mason_sniper_night_selected_uids(game)
        max_allowed = ms_sn.mason_sniper_max_targets_this_night(game)
        text = build_mason_multi_select_panel_text(
            "🎯 header",
            game,
            gm,
            selected,
            max_allowed,
        )
        self.assertIn("انتخاب‌های مجاز شما: 0 از 2", text)
        self.assertNotIn("انتخاب اول:", text)
        self.assertNotIn("انتخاب دوم:", text)

    def test_sniper_night2_no_more_button_after_first_pick(self) -> None:
        game = _mason_game(self.gm)
        label = mason_multi_select_none_button_label(
            1, first_step_label="بدون شلیک"
        )
        self.assertEqual(label, "انتخاب دوم ندارم")

    def test_sniper_night2_panel_after_one_selection(self) -> None:
        game = _mason_game(self.gm)
        gm = self.gm
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "Erfan", Role.GODFATHER))
        reset_mason_current_night_selections(game)
        ms_sn.commit_mason_sniper_night_selection(game, [20])

        captured_kb = []

        async def _capture(_bot, _game, _ui, _uid, _text, kb):
            captured_kb.append(kb)

        with patch(
            "bot.mason_night_role.sync_role_mirror_panel",
            side_effect=_capture,
        ):
            import asyncio

            asyncio.run(_show_mason_sniper_panel(AsyncMock(), game, gm, 10))

        labels = [
            btn.text
            for row in captured_kb[0].inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("انتخاب دوم ندارم" in t for t in labels))
        self.assertFalse(any("انتخاب سوم ندارم" in t for t in labels))

    def test_commander_night2_panel_starts_fresh(self) -> None:
        game = _mason_game(self.gm)
        game.mason_sniper_night_selected_uids = [20]
        game.mason_commander_night_approved_uids = [20]
        reset_mason_current_night_selections(game)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [])

    def test_bazpors_unchanged(self) -> None:
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1] / "bot" / "no_host_sniper_night.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("reset_mason_current_night_selections", text)
