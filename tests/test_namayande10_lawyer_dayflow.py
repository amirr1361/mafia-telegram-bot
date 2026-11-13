"""Namayande-10 — Lawyer next-day defense protection (Day 2 onward).

Covers the day-flow integration of the durable night-2 Lawyer effect:

- Night N valid (non-nullified) Lawyer pick stores
  ``nmnd_night2_lawyer_immune_uid`` / ``nmnd_night2_lawyer_immune_day``;
  the protection applies ONLY on the day immediately following that
  night (``immune_day == nmnd_narrator_night_count``).
- The assistant's defense-candidate selection panel is unchanged;
  protection is evaluated strictly AFTER the candidates are confirmed.
- The post-confirm defense-outcome panel appends a protection sentence
  only for protected candidates and omits their elimination buttons;
  non-protected candidates keep theirs and the no-elimination option
  always stays.
- Server-side enforcement: ``d1el`` and ``elim_yes`` callbacks re-check
  current-day immunity and reject protected targets; the ability is
  never re-consumed; expired/absent/nullified protection does nothing;
  the intro Day 1 (night_count == 0) can never have protection.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

os.environ.setdefault("GAME_AUDIT_LOG_ENABLED", "1")
os.environ["GAME_AUDIT_LOG_DIR"] = tempfile.mkdtemp(prefix="nm10-lawyer-audit-")

import bot.app_state as _app_state  # noqa: E402
from bot.game import GameManager as _GM  # noqa: E402

_app_state.manager = _GM()

import bot.db as _db  # noqa: E402

_db.init_db()
from bot.game import GameManager  # noqa: E402

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from tests.nam10_flow_harness import (  # noqa: E402
    Nam10FlowHarness,
    _callback,
    _telegram_patches,
)

PROTECT_FRAGMENT = "به دلیل حمایت معتبر وکیل در شب گذشته"


def _protect_alert(player) -> str:
    """Current contract: the helper popup names the protected player."""
    from bot.app_state import manager as _manager

    return (
        "⚖️ " + _manager.format_player_tag(player)
        + " به دلیل حمایت معتبر وکیل در شب گذشته، "
        "وارد دفاعیه نمی‌شود."
    )


def _button_texts(kb) -> list[str]:
    return [b.text for row in kb.inline_keyboard for b in row]


class Nam10LawyerDefenseTest(unittest.IsolatedAsyncioTestCase):
    """Defense-panel Lawyer protection integration tests."""

    async def asyncSetUp(self) -> None:
        self.gm = GameManager()
        self.h = Nam10FlowHarness.build(self.gm)
        self.game = self.h.game
        await self.h.run_intro_night()

    # ---------------------------------------------------------- helpers

    def _two_candidates(self):
        alive = [
            p
            for p in self.game.players.values()
            if p.is_alive and p.user_id != self.h.assistant_uid
        ]
        alive.sort(key=lambda p: p.user_id)
        return alive[0], alive[1]

    def _grant_immunity(self, uid: int, *, night: int = 1) -> None:
        """Authoritative night-N resolution product (valid pick)."""
        self.game.nmnd_night2_lawyer_uid = uid
        self.game.nmnd_night2_lawyer_used = True
        self.game.nmnd_night2_lawyer_used_night = night
        self.game.nmnd_night2_lawyer_immune_uid = uid
        self.game.nmnd_night2_lawyer_immune_day = night

    async def _dispatch(self, cb, act: str, tid: int = 0) -> None:
        from bot.nam10.dayflow import _dispatch_no_host_day1_defense_act

        async with _telegram_patches(self.gm):
            await _dispatch_no_host_day1_defense_act(
                cb,
                self.h.bot,
                self.game,
                self.h.assistant_uid,
                self.h.assistant_uid,
                act,
                tid=tid,
                source="nhd",
            )

    async def _pick_and_confirm(self, uids) -> None:
        for uid in uids:
            await self._dispatch(_callback(self.h.assistant_uid), "tog", tid=uid)
        await self._dispatch(_callback(self.h.assistant_uid), "confirm")

    # ------------------------------------------------------------- tests

    async def test_protected_candidate_excluded_from_elim_buttons(self):
        a, b = self._two_candidates()
        self.game.nmnd_narrator_night_count = 1  # day after night 1
        self._grant_immunity(b.user_id)
        await self._pick_and_confirm([a.user_id, b.user_id])
        self.assertEqual(self.game.nam10_day1_defense_phase, "outcome")

        from bot.nam10.dayflow import (
            _no_host_day1_defense_outcome_keyboard,
            build_no_host_day1_defense_outcome_html,
        )

        text = build_no_host_day1_defense_outcome_html(self.game)
        self.assertIn("بررسی بازیکنان انتخاب\u200cشده برای دفاعیه", text)
        self.assertIn(PROTECT_FRAGMENT, text)
        self.assertIn(b.full_name, text)
        # The pattern appears exactly once (for the protected candidate).
        self.assertEqual(text.count(PROTECT_FRAGMENT), 1)
        # Positional check: the protection sentence follows b's entry.
        self.assertLess(
            text.index(b.full_name),
            text.index(PROTECT_FRAGMENT),
        )

        kb = _no_host_day1_defense_outcome_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        texts = _button_texts(kb)
        self.assertTrue(
            any(t.startswith("خروج (") and a.full_name in t for t in texts),
            texts,
        )
        self.assertFalse(
            any(b.full_name in t for t in texts if t.startswith("خروج")),
            texts,
        )
        self.assertTrue(any("خروجی نداشتیم" in t for t in texts))

        # Server-side enforcement on the protected candidate.
        cb = _callback(self.h.assistant_uid)
        await self._dispatch(cb, "d1el", tid=b.user_id)
        cb.answer.assert_awaited_with(_protect_alert(b), show_alert=True)
        self.assertEqual(self.game.nam10_day1_defense_phase, "outcome")
        self.assertIsNone(self.game.nam10_day1_pending_elim_uid)

        # Non-protected candidate still eliminable end-to-end.
        cb2 = _callback(self.h.assistant_uid)
        await self._dispatch(cb2, "d1el", tid=a.user_id)
        self.assertEqual(self.game.nam10_day1_defense_phase, "confirm_elim")
        self.assertEqual(self.game.nam10_day1_pending_elim_uid, a.user_id)
        cb3 = _callback(self.h.assistant_uid)
        await self._dispatch(cb3, "elim_yes")
        self.assertFalse(self.game.players[a.user_id].is_alive)

    async def test_both_protected_keeps_no_exit_only(self):
        # The durable model holds one protected uid (once-per-game
        # ability), so a two-protected pool is only reachable in a
        # defensive-robustness sense; exercise it by extending the
        # protected set directly.
        a, b = self._two_candidates()
        self.game.nmnd_narrator_night_count = 1
        self._grant_immunity(a.user_id)
        self.game.nmnd_night2_lawyer_immune_uid = a.user_id
        self._grant_immunity(b.user_id, night=1)
        from bot.nam10 import dayflow

        real_helper = dayflow._nam10_day_lawyer_protected_uids

        def _both(game):
            return {a.user_id, b.user_id}

        dayflow._nam10_day_lawyer_protected_uids = _both
        try:
            await self._pick_and_confirm([a.user_id, b.user_id])
            await self._assert_both_protected()
            cb = _callback(self.h.assistant_uid)
            await self._dispatch(cb, "no_exit")
            self.assertTrue(
                self.game.nmnd_narrator_night_count >= 1
                or self.game.nmnd_narrator_step is not None
            )
        finally:
            dayflow._nam10_day_lawyer_protected_uids = real_helper

    async def _assert_both_protected(self):

        from bot.nam10.dayflow import (
            _no_host_day1_defense_outcome_keyboard,
            build_no_host_day1_defense_outcome_html,
        )

        text = build_no_host_day1_defense_outcome_html(self.game)
        self.assertEqual(text.count(PROTECT_FRAGMENT), 2)
        kb = _no_host_day1_defense_outcome_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        texts = _button_texts(kb)
        self.assertFalse(
            any(t.startswith("خروج (") for t in texts), texts
        )
        self.assertTrue(any("خروجی نداشتیم" in t for t in texts))

    async def test_no_retroactive_protection_on_intro_day1(self):
        a, b = self._two_candidates()
        # Intro Day 1: no night has run yet (night_count == 0) even if a
        # night-1 immunity row were hypothetically present.
        self.game.nmnd_narrator_night_count = 0
        self._grant_immunity(a.user_id, night=1)
        await self._pick_and_confirm([a.user_id, b.user_id])

        from bot.nam10.dayflow import (
            _no_host_day1_defense_outcome_keyboard,
            build_no_host_day1_defense_outcome_html,
        )

        text = build_no_host_day1_defense_outcome_html(self.game)
        self.assertNotIn(PROTECT_FRAGMENT, text)
        kb = _no_host_day1_defense_outcome_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        texts = _button_texts(kb)
        self.assertTrue(
            any(t.startswith("خروج (") and a.full_name in t for t in texts),
            texts,
        )

    async def test_expired_protection_not_applied_after_following_day(self):
        a, b = self._two_candidates()
        # Night 2 in progress: immunity obtained in night 1 is expired.
        self.game.nmnd_narrator_night_count = 2
        self._grant_immunity(a.user_id, night=1)
        await self._pick_and_confirm([a.user_id, b.user_id])

        from bot.nam10.dayflow import (
            _no_host_day1_defense_outcome_keyboard,
            build_no_host_day1_defense_outcome_html,
        )

        text = build_no_host_day1_defense_outcome_html(self.game)
        self.assertNotIn(PROTECT_FRAGMENT, text)
        kb = _no_host_day1_defense_outcome_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        self.assertTrue(
            any(
                t.startswith("خروج (") and a.full_name in t
                for t in _button_texts(kb)
            ),
            _button_texts(kb),
        )

    async def test_hacker_nullified_lawyer_grants_no_protection(self):
        a, b = self._two_candidates()
        self.game.nmnd_narrator_night_count = 1
        # Hacker-nullified resolution: no durable immunity is stored.
        self.game.nmnd_night2_lawyer_uid = a.user_id
        self.game.nmnd_night2_lawyer_used = True
        self.game.nmnd_night2_lawyer_used_night = 1
        self.game.nmnd_night2_outcome = {
            "lawyer": {
                "attempt_uid": a.user_id,
                "granted": False,
                "nullified_by_hacker": True,
                "consumed_anyway": True,
            }
        }
        await self._pick_and_confirm([a.user_id, b.user_id])

        from bot.nam10.dayflow import (
            _no_host_day1_defense_outcome_keyboard,
            build_no_host_day1_defense_outcome_html,
        )

        text = build_no_host_day1_defense_outcome_html(self.game)
        self.assertNotIn(PROTECT_FRAGMENT, text)
        kb = _no_host_day1_defense_outcome_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        self.assertTrue(
            any(
                t.startswith("خروج (") and a.full_name in t
                for t in _button_texts(kb)
            ),
            _button_texts(kb),
        )

    async def test_forged_elim_yes_for_protected_target_rejected(self):
        a, b = self._two_candidates()
        self.game.nmnd_narrator_night_count = 1
        self._grant_immunity(b.user_id)
        await self._pick_and_confirm([a.user_id, b.user_id])

        # Simulate a stale/forged state: the confirm-elim phase points at
        # the protected candidate even though the keyboard never offered
        # that option.
        self.game.nam10_day1_defense_phase = "confirm_elim"
        self.game.nam10_day1_pending_elim_uid = b.user_id
        cb = _callback(self.h.assistant_uid)
        await self._dispatch(cb, "elim_yes")
        cb.answer.assert_awaited_with(_protect_alert(b), show_alert=True)
        self.assertTrue(self.game.players[b.user_id].is_alive)
        self.assertEqual(self.game.nam10_day1_defense_phase, "confirm_elim")

    async def test_candidate_selection_panel_unchanged(self):
        a, b = self._two_candidates()
        self.game.nmnd_narrator_night_count = 1
        self._grant_immunity(b.user_id)

        from bot.nam10.dayflow import (
            _no_host_day1_defense_pick_keyboard,
            build_no_host_day1_defense_pick_html,
        )

        kb = _no_host_day1_defense_pick_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        texts = _button_texts(kb)
        # Both candidates (protected or not) stay selectable in the
        # initial candidate-selection panel.
        self.assertTrue(
            any(b.full_name[:24] in t for t in texts), texts
        )
        self.assertTrue(
            any(a.full_name[:24] in t for t in texts), texts
        )
        html_txt = build_no_host_day1_defense_pick_html(self.game)
        self.assertNotIn(PROTECT_FRAGMENT, html_txt)

    async def test_protection_not_consumed_again(self):
        a, b = self._two_candidates()
        self.game.nmnd_narrator_night_count = 1
        self._grant_immunity(b.user_id)
        await self._pick_and_confirm([a.user_id, b.user_id])

        cb = _callback(self.h.assistant_uid)
        await self._dispatch(cb, "d1el", tid=b.user_id)
        # The durable immunity state is untouched after the rejection.
        self.assertEqual(
            self.game.nmnd_night2_lawyer_immune_uid, b.user_id
        )
        self.assertEqual(self.game.nmnd_night2_lawyer_immune_day, 1)
        self.assertTrue(self.game.nmnd_night2_lawyer_used)

    async def test_room19_shape_immunity_non_candidate(self):
        """Room-19 mirror: immunity live on a NON-candidate player
        (the Guide) while the confirmed candidates are unprotected —
        exactly Example A."""
        a, b = self._two_candidates()
        third = next(
            p.user_id
            for p in self.game.players.values()
            if p.is_alive and p.user_id not in (a.user_id, b.user_id, self.h.assistant_uid)
        )
        self.game.nmnd_narrator_night_count = 1
        self._grant_immunity(third)
        await self._pick_and_confirm([a.user_id, b.user_id])

        from bot.nam10.dayflow import (
            _no_host_day1_defense_outcome_keyboard,
            build_no_host_day1_defense_outcome_html,
        )

        text = build_no_host_day1_defense_outcome_html(self.game)
        self.assertNotIn(PROTECT_FRAGMENT, text)
        self.assertIn(a.full_name, text)
        self.assertIn(b.full_name, text)
        kb = _no_host_day1_defense_outcome_keyboard(
            self.game, self.h.assistant_uid, mirror=False
        )
        texts = _button_texts(kb)
        self.assertTrue(
            any(t.startswith("خروج (") and a.full_name in t for t in texts),
            texts,
        )
        self.assertTrue(
            any(t.startswith("خروج (") and b.full_name in t for t in texts),
            texts,
        )
        self.assertTrue(any("خروجی نداشتیم" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
