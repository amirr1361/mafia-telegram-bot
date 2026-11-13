"""Namayande-10 Night v2 — spent Mine/Lawyer same-night acknowledgement.

Regression tests for the Room 9 production stall: after the mine placer
or the lawyer confirmed their one-time ability on the current night,
`night2_required_keys()` still listed them as pending ("spent Mine" /
"spent Lawyer" ack), but the confirmation panel was rendered without
any button, so the ack — and therefore the whole night collection —
could never complete. The fix attaches `_wait_ok_kb` to those panels.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_v2 as base
from tests.test_namayande10_night_v2 import (
    LAW_UID,
    CIT1_UID,
    MINE_UID,
    Nam10NightV2Test,
)


class _SkipInheritedTests(type):
    """Shadow inherited test methods so only the subclass tests run."""

    def __new__(mcls, name, bases, ns):
        own = set(ns)
        for base_cls in bases:
            for attr in [a for a in vars(base_cls) if a.startswith("test_")]:
                if attr not in own:
                    ns[attr] = None
        return super().__new__(mcls, name, bases, ns)


def _find_wait_ok_buttons(bot, text_marker: str):
    """All OK buttons across the most recent panel containing marker."""
    found = None
    for text, kb in bot.kb_segments():
        if kb is not None and text_marker in (text or ""):
            found = kb
    if found is None:
        return []
    out = []
    for row in found.inline_keyboard:
        for b in row:
            data = getattr(b, "callback_data", "") or ""
            if "waitok" in data:
                out.append(b)
    return out


class Nam10Night2SpentAckTest(Nam10NightV2Test, metaclass=_SkipInheritedTests):
    """Spent-role acknowledgement panels and collection gating."""

    async def test_mine_confirm_panel_offers_wait_ok_button(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        from bot.nam10.night2 import night2_required_keys

        # Mine placer places a mine and confirms it.
        await self._press(MINE_UID, "minp", MINE_UID, tid=CIT1_UID)
        await self._press(MINE_UID, "minok", MINE_UID)
        self.assertTrue(g.nmnd_night2_mine_used)
        # Deepest bug report: the confirm panel must expose the ack button.
        ok_btns = _find_wait_ok_buttons(self.bot, "✅ انتخاب شما")
        self.assertTrue(
            ok_btns,
            "spent-mine confirm panel must offer the ✅ اوکی button",
        )
        # Until the ack is pressed the placer stays pending and the night
        # cannot collect (Room 9 blocker).
        self.assertIn("RUINTAN", night2_required_keys(g))
        self.assertNotIn(
            MINE_UID, g.nmnd_night2_waiting_acked.get("RUINTAN", [])
        )
        await self._press(MINE_UID, "waitok", MINE_UID)
        self.assertEqual(
            g.nmnd_night2_waiting_acked.get("RUINTAN"), [MINE_UID]
        )
        self.assertNotIn("RUINTAN", night2_required_keys(g))

    async def test_mine_none_pick_satisfies_requirement_without_button(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        from bot.nam10.night2 import night2_required_keys

        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        self.assertFalse(g.nmnd_night2_mine_used)
        # The none-pick disposition satisfies the requirement immediately;
        # the panel must not present a dead ack button.
        ok_btns = _find_wait_ok_buttons(self.bot, "انتخابی ندارم — ثبت شد")
        self.assertFalse(
            ok_btns,
            "none-pick panel must NOT offer a further OK button",
        )
        self.assertNotIn("RUINTAN", night2_required_keys(g))

    async def test_lawyer_confirm_panel_offers_wait_ok_button(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        from bot.nam10.night2 import night2_required_keys

        await self._press(LAW_UID, "lawp", LAW_UID, tid=CIT1_UID)
        await self._press(LAW_UID, "lawok", LAW_UID)
        self.assertTrue(g.nmnd_night2_lawyer_used)
        ok_btns = _find_wait_ok_buttons(self.bot, "✅ انتخاب شما")
        self.assertTrue(
            ok_btns,
            "spent-lawyer confirm panel must offer the ✅ اوکی button",
        )
        self.assertIn("HUNTER", night2_required_keys(g))
        await self._press(LAW_UID, "waitok", LAW_UID)
        self.assertEqual(
            g.nmnd_night2_waiting_acked.get("HUNTER"), [LAW_UID]
        )
        self.assertNotIn("HUNTER", night2_required_keys(g))

    async def test_unpressed_spent_acks_block_night_collection(self):
        """Room-9 shape: every visible action done, acks unpressed →
        collection boundary must NOT resolve the night."""
        self._fork_room()
        await self._enter_night()
        g = self.game
        from bot.nam10.night2 import night2_required_keys

        await self._press(MINE_UID, "minp", MINE_UID, tid=CIT1_UID)
        await self._press(MINE_UID, "minok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=CIT1_UID)
        await self._press(LAW_UID, "lawok", LAW_UID)
        keys = night2_required_keys(g)
        self.assertIn("RUINTAN", keys)
        self.assertIn("HUNTER", keys)
        # Resolution is blocked while the acks are outstanding.
        from bot.nam10.night2 import PENDING_COLLECTING

        self.assertEqual(g.nmnd_night2_phase, PENDING_COLLECTING)
        self.assertFalse(g.nmnd_night2_resolved)
        self.assertFalse(g.nmnd_night2_publication_pending)
        # Pressing the newly exposed buttons completes the obligations.
        await self._press(LAW_UID, "waitok", LAW_UID)
        await self._press(MINE_UID, "waitok", MINE_UID)
        self.assertEqual(
            g.nmnd_night2_waiting_acked.get("HUNTER"), [LAW_UID]
        )
        self.assertEqual(
            g.nmnd_night2_waiting_acked.get("RUINTAN"), [MINE_UID]
        )
        # With only citizens/rebel/boss actions left pending the acks are
        # gone from the required set.
        self.assertNotIn("RUINTAN", night2_required_keys(g))
        self.assertNotIn("HUNTER", night2_required_keys(g))

    async def test_duplicate_ack_rejected(self):
        self._fork_room()
        await self._enter_night()
        # Use the mine on a real target so the same-night ack is required.
        await self._press(MINE_UID, "minp", MINE_UID, tid=CIT1_UID)
        await self._press(MINE_UID, "minok", MINE_UID)
        await self._press(MINE_UID, "waitok", MINE_UID)
        before = list(self.game.nmnd_night2_waiting_acked.get("RUINTAN", []))
        self.assertTrue(before)
        await self._press(MINE_UID, "waitok", MINE_UID)
        self.assertTrue(
            any("قبلاً ثبت شده است." in (a or "") for a in self.bot.acks()),
        )
        self.assertEqual(
            list(self.game.nmnd_night2_waiting_acked.get("RUINTAN", [])),
            before,
        )


if __name__ == "__main__":
    unittest.main()
