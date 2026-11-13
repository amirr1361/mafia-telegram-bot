"""Room 83 — Bazpors defence OUTCOME panel duplicate fix (focused tests).

The bug: every outcome-selection press (d1el / no_exit tentative toggles)
called ``send_no_host_day1_defense_outcome_panel`` which always sent a NEW
panel pair (player + observer) instead of editing the existing one —
duplicates with live buttons accumulated in the operator chat.

The fix: the sender now updates the tracked mirror-prompt message(s) in
place (``update_mirror_prompt_pair``), falls back to in-place promotion
from sibling panels, and only registers a fresh pair when no panel exists.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


ASSISTANT = 9999
OBSERVER = 777


def _game() -> Game:
    game = Game(
        room_code="83",
        host_id=ASSISTANT,
        scenario_name="bazpors",
        players={
            1: _p(1, 1, "one", Role.CITIZEN),
            2: _p(2, 2, "two", Role.CITIZEN),
            3: _p(3, 3, "three", Role.CITIZEN),
        },
    )
    game.bazpors_narrator_night_count = 1
    game.bazpors_host_mode = "no_host"
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = ASSISTANT
    game.observer_user_id = OBSERVER
    game.observer_prompt_status = "registered"
    game.no_host_intro_night_started = True
    from bot.bazpors_narrator import set_day_vote_defender_uids

    set_day_vote_defender_uids(game, {1, 2})
    game.no_host_day1_defense_active = True
    game.no_host_day1_defense_phase = "outcome"
    return game


class _Msg:
    def __init__(self, chat_id: int, message_id: int) -> None:
        self.chat = type("Chat", (), {"id": chat_id})()
        self.message_id = message_id
        self.html_text = "old"


def _next_id(start: int = 700):
    counter = {"n": start}

    def _take():
        counter["n"] += 1
        return counter["n"]

    return _take


class _RecordingBot:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.sends: list[dict[str, Any]] = []
        self._take = _next_id()

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return True

    async def edit_message_reply_markup(self, **kwargs):
        self.edits.append(kwargs)
        return True

    async def send_message(self, **kwargs):
        self.sends.append(kwargs)
        return _Msg(kwargs.get("chat_id", 0), self._take())

    async def delete_message(self, chat_id, message_id, **kwargs):
        return True


def _buttons_by_act(kb, act: str) -> list[Any]:
    from bot.main import NoHostDay1DefenseCb
    from bot.observer_delivery import PlayerMirrorCb

    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            for cls in (NoHostDay1DefenseCb, PlayerMirrorCb):
                try:
                    cb = cls.unpack(btn.callback_data)
                except Exception:
                    continue
                if cb.act == act:
                    out.append((btn, cb))
                break
    return out


class OutcomePanelInPlaceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_send_then_selection_edit_same_message(self) -> None:
        from bot.main import send_no_host_day1_defense_outcome_panel

        game = _game()
        bot = _RecordingBot()
        # First delivery (fresh phase — no tracked panel yet).
        await send_no_host_day1_defense_outcome_panel(bot, game)
        key = "day1_defense_outcome:83:9999"
        entry = game.mirror_prompt_messages.get(key) or {}
        refs = {r: entry.get(r) for r in ("player", "observer") if entry.get(r)}
        self.assertTrue(refs, "first send must store tracked panel refs")
        initial_sends = len(bot.sends)
        self.assertEqual(initial_sends, len(refs))

        # Outcome selection press #1 → must EDIT the SAME message(s).
        game.no_host_day1_pending_elim_uid = 1
        await send_no_host_day1_defense_outcome_panel(bot, game)
        self.assertEqual(len(bot.sends), initial_sends, "no duplicate panel!")
        self.assertEqual(len(bot.edits), len(refs))

        # Outcome selection press #2 (replaced selection) → still in place.
        game.no_host_day1_pending_elim_uid = 2
        await send_no_host_day1_defense_outcome_panel(bot, game)
        self.assertEqual(len(bot.sends), initial_sends, "no duplicate panel!")
        self.assertEqual(len(bot.edits), 2 * len(refs))
        edited_ids = {(e["chat_id"], e["message_id"]) for e in bot.edits}
        for r in refs.values():
            self.assertIn((r[0], r[1]), edited_ids)

    async def test_selected_red_replaced_selection_turns_blue(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_keyboard

        game = _game()
        game.no_host_day1_pending_elim_uid = 1
        kb = _no_host_day1_defense_outcome_keyboard(game, ASSISTANT, mirror=True)
        red = [cb.tid for btn, cb in _buttons_by_act(kb, "d1el") if btn.style == "danger"]
        self.assertEqual(red, [1])
        no_exits = _buttons_by_act(kb, "no_exit") + _buttons_by_act(kb, "d1d0")
        self.assertEqual(no_exits[0][0].style, "primary")
        confirms = _buttons_by_act(kb, "elim_yes") + _buttons_by_act(kb, "d1ey")
        self.assertEqual(confirms[0][0].style, "success")

        game.no_host_day1_pending_elim_uid = 2
        kb = _no_host_day1_defense_outcome_keyboard(game, ASSISTANT, mirror=True)
        red = [cb.tid for btn, cb in _buttons_by_act(kb, "d1el") if btn.style == "danger"]
        self.assertEqual(red, [2])
        styles = {cb.tid: btn.style for btn, cb in _buttons_by_act(kb, "d1el")}
        self.assertEqual(styles[1], "primary", "previous selection must turn blue")

    async def test_dispatch_selection_edits_tracked_panel(self) -> None:
        from bot.main import _no_host_day1_defense_pick_elim

        game = _game()
        bot = _RecordingBot()
        # Seed the panel (fresh phase → register path).
        await _seed_outcome_panel(bot, game)
        before = len(bot.sends)
        refs = {
            r: v
            for r, v in (game.mirror_prompt_messages.get(
                "day1_defense_outcome:83:9999"
            ) or {}).items()
            if r in ("player", "observer") and isinstance(v, tuple)
        }
        self.assertTrue(refs)

        class _Cb:
            alerts: list[tuple[str, bool]] = []

            async def answer(self, text: str = "", show_alert: bool = False):
                self.alerts.append((text, show_alert))

        cb = _Cb()
        cb.alerts = []
        await _no_host_day1_defense_pick_elim(cb, bot, game, ASSISTANT, ASSISTANT, 1)
        self.assertEqual(game.no_host_day1_pending_elim_uid, 1)
        self.assertEqual(len(bot.sends), before, "no duplicate panel on selection")
        self.assertTrue(bot.edits, "tracked panel must be edited in place")

        # Selecting a different outcome updates the SAME panel.
        await _no_host_day1_defense_pick_elim(cb, bot, game, ASSISTANT, ASSISTANT, 2)
        self.assertEqual(game.no_host_day1_pending_elim_uid, 2)
        self.assertEqual(len(bot.sends), before, "no duplicate panel on reselect")
        # Entry refs unchanged → preserved message ids.
        for r, v in refs.items():
            self.assertEqual((game.mirror_prompt_messages[  # type: ignore[union-attr]
                "day1_defense_outcome:83:9999"
            ] or {}).get(r), v)

    async def test_final_confirmation_commits_once_and_rejects_repeat(self) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game = _game()
        game.no_host_day1_pending_elim_uid = 1
        bot = _RecordingBot()
        await _seed_outcome_panel(bot, game)

        class _Cb:
            alerts: list[tuple[str, bool]] = []
            message = None

            async def answer(self, text: str = "", show_alert: bool = False):
                self.alerts.append((text, show_alert))

        cb = _Cb()
        cb.alerts = []
        with patch(
            "bot.main.eliminate_player_from_game"
        ) as elim, patch(
            "bot.russian_mafia_flow.finish_russian_confirmed_elimination",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.bazpors_narrator.hunter_chain_confirm_alert_text",
            return_value=None,
        ), patch(
            "bot.main.flush_elimination_notifications", new=AsyncMock()
        ), patch(
            "bot.main.close_mirror_prompt_keyboards", new=AsyncMock()
        ) as close, patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ), patch(
            "bot.no_host_mafia_win.no_host_maybe_end_on_faction_win",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.no_host_handoff.offer_handoff_day1_after_elim",
            return_value=False,
        ), patch(
            "bot.main.no_host_day1_after_elim_enter_night"
        ) as enter_night, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ):
            await _no_host_day1_defense_confirm_elim_yes(
                cb, bot, game, ASSISTANT, ASSISTANT
            )
        elim.assert_called_once()
        self.assertIsNone(game.no_host_day1_pending_elim_uid)
        enter_night.assert_called_once()
        # The tracked outcome panel is closed (keyboard removed).
        closed_keys = [c.args[2] for c in close.await_args_list]
        self.assertTrue(any("day1_defense_outcome" in k for k in closed_keys))

        # A repeat press on a surviving stale copy must be rejected.
        await _no_host_day1_defense_confirm_elim_yes(
            cb, bot, game, ASSISTANT, ASSISTANT
        )
        elim.assert_called_once()
        self.assertTrue(cb.alerts and cb.alerts[-1][1])
        self.assertIn("انتخاب کنید", cb.alerts[-1][0])

    async def test_observer_panel_stays_synchronized(self) -> None:
        from bot.main import send_no_host_day1_defense_outcome_panel

        game = _game()
        bot = _RecordingBot()
        await send_no_host_day1_defense_outcome_panel(bot, game)
        entry = game.mirror_prompt_messages.get("day1_defense_outcome:83:9999") or {}
        obs_ref = entry.get("observer")
        self.assertTrue(obs_ref, "observer mirror copy must be tracked")
        game.no_host_day1_pending_elim_uid = 1
        await send_no_host_day1_defense_outcome_panel(bot, game)
        observer_chat = OBSERVER
        obs_edits = [
            e for e in bot.edits if e.get("chat_id") == observer_chat
        ]
        self.assertTrue(obs_edits, "observer copy must be edited, not resent")
        self.assertEqual(
            entry["observer"], obs_ref, "observer message_id preserved"
        )


async def _seed_outcome_panel(bot: _RecordingBot, game: Game) -> None:
    from bot.main import send_no_host_day1_defense_outcome_panel

    await send_no_host_day1_defense_outcome_panel(bot, game)


if __name__ == "__main__":
    unittest.main()
