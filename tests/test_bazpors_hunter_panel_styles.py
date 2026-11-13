"""Bazpors — Hunter player-selection & confirmation panel button styles.

Cosmetic-only contract:
- Bazpors: player-pick buttons are blue (primary); the tentative selection
  is red (danger); exactly ONE green (success) «✅ تأیید انتخاب» confirm
  button (act hnc) is visible from the initial panel rendering.
- Other scenarios keep the previous unstyled buttons completely unchanged.
"""

from __future__ import annotations

import html
import unittest

from aiogram.types import InlineKeyboardMarkup

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.no_host_night1 import (
    _hunter_confirm_keyboard,
    _hunter_pick_keyboard,
    dispatch_no_host_hunter_night1,
)
from bot.observer_delivery import PlayerMirrorCb


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _make_game(scenario_name: str = "bazpors") -> tuple[Game, GameManager]:
    gm = GameManager()
    game = Game(
        room_code="42",
        host_id=9001,
        scenario_name=scenario_name,
        players={
            1: _p(1, 1, "هانتر", Role.HUNTER),
            2: _p(2, 2, "شهروند یک", Role.CITIZEN),
            3: _p(3, 3, "شهروند دو", Role.CITIZEN),
            4: _p(4, 4, "مافیا", Role.MAFIA),
        },
    )
    game.bazpors_narrator_night_count = 1
    return game, gm


def _hnp_buttons(kb: InlineKeyboardMarkup) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            cb = PlayerMirrorCb.unpack(btn.callback_data)
            if cb.act == "hnp":
                out.append(btn)
    return out


def _buttons_by_act(kb: InlineKeyboardMarkup, act: str) -> list:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            cb = PlayerMirrorCb.unpack(btn.callback_data)
            if cb.act == act:
                out.append(btn)
    return out


class BazporsHunterPanelStyleTests(unittest.TestCase):
    """Initial panel: all selection buttons blue, none green."""

    def setUp(self) -> None:
        self.game, self.gm = _make_game("bazpors")

    def test_initial_panel_all_player_buttons_blue(self) -> None:
        kb = _hunter_pick_keyboard(self.game, 1, self.gm)
        for btn in _hnp_buttons(kb):
            self.assertEqual(btn.style, "primary")

    def test_initial_panel_single_green_confirm_visible(self) -> None:
        kb = _hunter_pick_keyboard(self.game, 1, self.gm)
        confirms = _buttons_by_act(kb, "hnc")
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0].style, "success")
        self.assertIn("تأیید انتخاب", confirms[0].text)

    def test_pending_selection_only_selected_player_red(self) -> None:
        self.game.no_host_hunter_pending_pick_uid = 3
        kb = _hunter_pick_keyboard(self.game, 1, self.gm)
        for btn in _hnp_buttons(kb):
            cb = PlayerMirrorCb.unpack(btn.callback_data)
            if cb.tid == 3:
                self.assertEqual(btn.style, "danger")
            else:
                self.assertEqual(btn.style, "primary")

    def test_committed_link_highlights_current_selection(self) -> None:
        self.game.bazpors_hunter_link_uid = 4
        self.game.bazpors_hunter_linked_this_night = True
        kb = _hunter_pick_keyboard(self.game, 1, self.gm)
        styles_by_tid = {
            PlayerMirrorCb.unpack(b.callback_data).tid: b.style
            for b in _hnp_buttons(kb)
        }
        self.assertEqual(styles_by_tid[4], "danger")
        self.assertEqual(styles_by_tid[2], "primary")
        self.assertEqual(styles_by_tid[3], "primary")

    def test_labels_and_callbacks_unchanged(self) -> None:
        """Only the style attribute may differ; text and callback stay intact."""
        kb = _hunter_pick_keyboard(self.game, 1, self.gm)
        expected = {
            html.escape(self.gm.format_player_tag(p)[:28])
            for p in self.game.players.values()
            if p.is_alive and p.user_id != 1
        }
        actual_texts = {b.text for b in _hnp_buttons(kb)}
        self.assertEqual(actual_texts, expected)
        for btn in _hnp_buttons(kb):
            cb = PlayerMirrorCb.unpack(btn.callback_data)
            self.assertEqual(cb.act, "hnp")
            self.assertEqual(cb.as_uid, 1)
            self.assertEqual(cb.code, "42")
            self.assertIn(cb.tid, {2, 3, 4})

    def test_confirmation_buttons_blue_not_green(self) -> None:
        kb = _hunter_confirm_keyboard(self.game, 1)
        confirm = _buttons_by_act(kb, "hnc")
        back = _buttons_by_act(kb, "hnb")
        self.assertEqual(len(confirm), 1)
        self.assertEqual(len(back), 1)
        self.assertEqual(confirm[0].style, "primary")
        self.assertEqual(back[0].style, "primary")
        self.assertEqual(confirm[0].text, "🔹 بله، تأیید انتخاب")
        self.assertEqual(back[0].text, "🔹 بازگشت و تصحیح انتخاب")


class BazporsButtonStyleIsolationTests(unittest.TestCase):
    """Scenario isolation: Mozakere / Masoon keep the previous default styles."""

    def test_mozakere_panel_unstyled(self) -> None:
        game, gm = _make_game("mozakere")
        kb = _hunter_pick_keyboard(game, 1, gm)
        for row in kb.inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)

    def test_mozakere_confirm_unstyled(self) -> None:
        game, _gm = _make_game("mozakere")
        kb = _hunter_confirm_keyboard(game, 1)
        for row in kb.inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)

    def test_mason_panel_unstyled(self) -> None:
        game, gm = _make_game("masoon")
        kb = _hunter_pick_keyboard(game, 1, gm)
        for row in kb.inline_keyboard:
            for btn in row:
                self.assertIsNone(btn.style)


class _StubCallback:
    def __init__(self) -> None:
        self.alerts: list[str] = []

    async def answer(self, text: str, show_alert: bool = False) -> None:
        self.alerts.append(text)


class BazporsHunterSelectionRejectionTests(unittest.IsolatedAsyncioTestCase):
    """Invalid / unauthorized selections stay rejected (behaviour untouched)."""

    async def test_self_link_rejected(self) -> None:
        game, gm = _make_game("bazpors")
        game.no_host_night1_hunter_flow_active = True
        game.no_host_night1_hunter_done = False
        cb = _StubCallback()
        await dispatch_no_host_hunter_night1(
            cb,
            None,  # bot not reached before rejection
            game,
            gm,
            hunter_uid=1,
            actor_uid=1,
            act="hnp",
            tid=1,
        )
        self.assertEqual(cb.alerts, ["انتخاب نامعتبر."])
        self.assertIsNone(game.no_host_hunter_pending_pick_uid)

    async def test_unauthorized_actor_rejected(self) -> None:
        game, gm = _make_game("bazpors")
        game.no_host_night1_hunter_flow_active = True
        game.no_host_night1_hunter_done = False
        cb = _StubCallback()
        await dispatch_no_host_hunter_night1(
            cb,
            None,
            game,
            gm,
            hunter_uid=1,
            actor_uid=424242,
            act="hnp",
            tid=2,
        )
        self.assertEqual(cb.alerts, ["شما مجاز به این عمل نیستید."])
        self.assertIsNone(game.no_host_hunter_pending_pick_uid)

    async def test_valid_selection_still_sets_pending(self) -> None:
        game, gm = _make_game("bazpors")
        game.no_host_night1_hunter_flow_active = True
        game.no_host_night1_hunter_done = False
        game.observer_user_id = None

        class _Bot:
            async def edit_message_text(self, *a, **k):  # pragma: no cover
                raise AssertionError("not used in this path")

        cb = _StubCallback()
        await dispatch_no_host_hunter_night1(
            cb,
            _Bot(),
            game,
            gm,
            hunter_uid=1,
            actor_uid=1,
            act="hnp",
            tid=3,
        )
        self.assertEqual(game.no_host_hunter_pending_pick_uid, 3)
        self.assertTrue(game.no_host_hunter_awaiting_confirm)


if __name__ == "__main__":
    unittest.main()
