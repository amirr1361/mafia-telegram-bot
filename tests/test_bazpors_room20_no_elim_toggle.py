"""Room 20 — Bazpors «خروجی نداشتیم. شب کن» unselectable fix (focused tests).

Root cause: `_no_host_day1_defense_outcome_no_exit_pick` gated the toggle on
the one-shot mirror claim `day1_defense_outcome:<room>:<assistant>`. With an
observer registered (mirror active), the FIRST press claimed the key; every
later press got `dup_self` → `_answer_mirror_claim` answered
«قبلاً ثبت شده.» and returned BEFORE toggling. The panel froze: the button
never turned red and the toggle could never be applied (Room 20 log:
repeated `d1d0` presses, all `received`, phase stuck at `outcome`).

Fix: the claim gate was removed — the handler is a pure repeatable toggle
for both actors (assistant + observer); authorization stays at dispatch
level (`_no_host_day1_defense_actor_may_act`) and panel sync uses the
Room-83 in-place sender.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from bot.game import GameManager  # noqa: F401  (db side-effects for tests)
from bot.models import Game, Player, Role


ASSISTANT = 8100001
OBSERVER = 777
PANEL_KEY = f"day1_defense_outcome:20:{ASSISTANT}"


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _game() -> Game:
    """Fixture WITH observer registered → mirror active (Room 20 shape)."""
    game = Game(
        room_code="20",
        host_id=ASSISTANT,
        scenario_name="bazpors",
        players={
            1: _p(1, 1, "one", Role.CITIZEN),
            2: _p(2, 2, "two", Role.CITIZEN),
            3: _p(3, 3, "three", Role.CITIZEN),
        },
    )
    game.bazpors_narrator_night_count = 1
    game.bazpors_narrator_host_day = 1
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


class _Cb:
    message = None

    def __init__(self) -> None:
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False):
        self.answers.append((text, show_alert))


class _RecordingBot:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.sends: list[dict[str, Any]] = []
        self._mid = 700

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return True

    async def edit_message_reply_markup(self, **kwargs):
        self.edits.append(kwargs)
        return True

    async def send_message(self, **kwargs):
        self.sends.append(kwargs)
        self._mid += 1
        msg = self._mid
        return type("M", (), {"chat": type("C", (), {"id": kwargs["chat_id"]})(),
                              "message_id": msg, "html_text": "t", "text": "t"})

    async def delete_message(self, chat_id, message_id, **kwargs):
        return True


def _button_acts(kb) -> dict[str, list[str]]:
    """act -> [style, ...] for both mirror (PlayerMirrorCb) and legacy cb types."""
    from bot.main import NoHostDay1DefenseCb
    from bot.observer_delivery import PlayerMirrorCb

    out: dict[str, list[str]] = {}
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            for cls in (PlayerMirrorCb, NoHostDay1DefenseCb):
                try:
                    cb = cls.unpack(btn.callback_data)
                except Exception:
                    continue
                out.setdefault(cb.act, []).append(btn.style)
                break
    return out


class NoElimToggleTests(unittest.IsolatedAsyncioTestCase):
    async def test_selecting_no_elim_toggles_and_restyles_in_place(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_no_exit_pick
        from bot.main import _no_host_day1_defense_outcome_keyboard

        game = _game()
        bot = _RecordingBot()
        from bot.main import send_no_host_day1_defense_outcome_panel
        await send_no_host_day1_defense_outcome_panel(bot, game)
        initial_sends = len(bot.sends)
        self.assertTrue(initial_sends)

        cb = _Cb()
        await _no_host_day1_defense_outcome_no_exit_pick(
            cb, bot, game, ASSISTANT, ASSISTANT
        )
        self.assertTrue(game.no_host_day1_pending_no_elim)
        self.assertEqual(game.no_host_day1_pending_elim_uid, None)
        self.assertEqual(len(bot.sends), initial_sends, "no duplicate panel")
        self.assertTrue(bot.edits, "panel must be edited in place")
        styles = _button_acts(
            _no_host_day1_defense_outcome_keyboard(game, ASSISTANT, mirror=True)
        )
        self.assertEqual(styles.get("d1d0"), ["danger"], "no-elim selected → red")
        for cand_act in ("d1el",):
            self.assertNotIn("danger", styles.get(cand_act, []))
        confirms = styles.get("d1ey", [])
        self.assertEqual(confirms.count("success"), 1, "exactly ONE green confirm")

    async def test_repeated_press_toggles_off_not_freeze(self) -> None:
        """The Room-20 deadlock: second press must toggle OFF, not answer
        «قبلاً ثبت شده.» and exit."""
        from bot.main import _no_host_day1_defense_outcome_no_exit_pick

        game = _game()
        bot = _RecordingBot()
        cb = _Cb()
        await _no_host_day1_defense_outcome_no_exit_pick(
            cb, bot, game, ASSISTANT, ASSISTANT
        )
        self.assertTrue(game.no_host_day1_pending_no_elim)
        await _no_host_day1_defense_outcome_no_exit_pick(
            cb, bot, game, ASSISTANT, ASSISTANT
        )
        self.assertFalse(game.no_host_day1_pending_no_elim, "second press deselects")
        self.assertFalse(
            any("قبلاً ثبت شده" in t for t, _ in cb.answers),
            "no already-registered dead-end",
        )

    async def test_observer_press_also_toggles(self) -> None:
        """Observer must be able to apply the no-elim toggle too (no claim wall)."""
        from bot.main import _no_host_day1_defense_outcome_no_exit_pick

        game = _game()
        bot = _RecordingBot()
        cb = _Cb()
        await _no_host_day1_defense_outcome_no_exit_pick(
            cb, bot, game, ASSISTANT, OBSERVER
        )
        self.assertTrue(game.no_host_day1_pending_no_elim)
        self.assertFalse(
            any("قبلاً ثبت شده" in t for t, _ in cb.answers)
        )

    async def test_switch_candidate_and_no_elim_replaces_selection(self) -> None:
        from bot.main import (
            _no_host_day1_defense_outcome_keyboard,
            _no_host_day1_defense_outcome_no_exit_pick,
            _no_host_day1_defense_pick_elim,
        )
        from bot.main import send_no_host_day1_defense_outcome_panel

        game = _game()
        bot = _RecordingBot()
        await send_no_host_day1_defense_outcome_panel(bot, game)
        initial_sends = len(bot.sends)

        cb = _Cb()
        # Candidate select → then no-elim select replaces it.
        await _no_host_day1_defense_pick_elim(
            cb, bot, game, ASSISTANT, ASSISTANT, 1
        )
        self.assertEqual(game.no_host_day1_pending_elim_uid, 1)
        await _no_host_day1_defense_outcome_no_exit_pick(
            cb, bot, game, ASSISTANT, ASSISTANT
        )
        self.assertTrue(game.no_host_day1_pending_no_elim)
        self.assertIsNone(game.no_host_day1_pending_elim_uid)
        styled = _button_acts(
            _no_host_day1_defense_outcome_keyboard(game, ASSISTANT, mirror=True)
        )
        self.assertEqual(styled.get("d1d0"), ["danger"])
        self.assertNotIn("danger", styled.get("d1el", []), "candidate back to blue")

        # And back again: candidate replaces the no-elim selection.
        await _no_host_day1_defense_pick_elim(
            cb, bot, game, ASSISTANT, ASSISTANT, 2
        )
        self.assertEqual(game.no_host_day1_pending_elim_uid, 2)
        self.assertFalse(game.no_host_day1_pending_no_elim)
        styled = _button_acts(
            _no_host_day1_defense_outcome_keyboard(game, ASSISTANT, mirror=True)
        )
        self.assertEqual(styled.get("d1el", []).count("danger"), 1)
        self.assertEqual(styled.get("d1d0"), ["primary"])

        self.assertEqual(
            len(bot.sends), initial_sends,
            "whole flow must stay on ONE panel pair (no duplicates)",
        )

    async def test_confirm_no_elim_enters_night_once(self) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game = _game()
        bot = _RecordingBot()
        cb = _Cb()
        game.no_host_day1_pending_no_elim = True

        with patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ) as broadcast, patch(
            "bot.russian_mafia_flow.apply_russian_day_result",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.main.no_host_day1_no_exit_enter_night"
        ) as enter_night, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ):
            await _no_host_day1_defense_confirm_elim_yes(
                cb, bot, game, ASSISTANT, ASSISTANT
            )
        enter_night.assert_called_once()
        broadcast.assert_called_once()
        self.assertFalse(game.no_host_day1_pending_no_elim)
        self.assertIsNone(game.no_host_day1_pending_elim_uid)
        # (phase clearing itself happens inside the real
        # no_host_day1_no_exit_enter_night → mocked here; asserted by the
        # full-flow simulation tests.)

        # Stale repeat (surviving copy of the panel): no second night entry.
        n_enter = enter_night.call_count
        await _no_host_day1_defense_confirm_elim_yes(
            cb, bot, game, ASSISTANT, ASSISTANT
        )
        self.assertEqual(enter_night.call_count, n_enter)
        self.assertTrue(cb.answers and cb.answers[-1][1])

    async def test_confirm_without_selection_rejected(self) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game = _game()
        bot = _RecordingBot()
        cb = _Cb()

        with patch("bot.main.no_host_day1_no_exit_enter_night") as enter_night:
            await _no_host_day1_defense_confirm_elim_yes(
                cb, bot, game, ASSISTANT, ASSISTANT
            )
        enter_night.assert_not_called()
        self.assertTrue(cb.answers and cb.answers[-1][1])
        self.assertIn("انتخاب کنید", cb.answers[-1][0])
        self.assertEqual(game.no_host_day1_defense_phase, "outcome")


if __name__ == "__main__":
    unittest.main()
