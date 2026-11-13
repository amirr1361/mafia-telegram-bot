"""Namayande-10 Night v2 — observer mirror duplicate-panel regression.

Production incident (Room 31, night 2 v2): after the Guide-granted
extra-investigation panel was delivered to seat 5, the next act's
periodic re-render (`night2_maybe_grant_guide_extra` re-send branch
invoked by doctor_confirmed) fell into `update_mirror_prompt_pair`.
Telegram rejects the no-op re-edit of an identical text/keyboard with
"Bad Request: message is not modified"; `_try_edit_mirror_message`
misclassified that as a failed edit, so `update_mirror_prompt_pair`
compensated by SENDING a brand-new observer copy — the observer then
held two active panels for the same act key.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

from aiogram.exceptions import TelegramBadRequest

from tests.test_namayande10_night_v2 import (
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUIDE_UID,
    GUARD_UID,
    LAW_UID,
    MINE_UID,
    NATO_UID,
    OBS_UID,
    SHIAD_UID,
    SYN_UID,
    Nam10NightV2Test,
)
from bot.nam10.night2 import (
    EXTRA_KIND_SENT,
    _extra_key,
    night2_maybe_grant_guide_extra,
)


class _SkipInheritedTests(type):
    """Shadow inherited test methods so only this class's tests run."""

    def __new__(mcls, name, bases, ns):
        own = set(ns)
        for base_cls in bases:
            for attr in [a for a in vars(base_cls) if a.startswith("test_")]:
                if attr not in own:
                    ns[attr] = None
        return super().__new__(mcls, name, bases, ns)


def _nm_error(msg: str = "Bad Request: message is not modified"):
    return TelegramBadRequest(method=None, message=msg)


class _NoopEditBot:
    """Both edit calls raise Telegram's no-op rejection."""

    async def edit_message_text(self, **kwargs):
        raise _nm_error()

    async def edit_message_reply_markup(self, **kwargs):
        raise _nm_error()


class _NoopMarkupEditBot:
    """Text edit no-op; fallback markup edit actually applies."""

    async def edit_message_text(self, **kwargs):
        raise _nm_error()

    async def edit_message_reply_markup(self, **kwargs):
        return None


class _NotFoundBot:
    async def edit_message_text(self, **kwargs):
        raise _nm_error("Bad Request: message to edit not found")

    async def edit_message_reply_markup(self, **kwargs):
        raise _nm_error("Bad Request: message to edit not found")


async def _probe_edit(bot, markup=None):
    from bot.observer_delivery import _try_edit_mirror_message

    return await _try_edit_mirror_message(
        bot,
        chat_id=1,
        message_id=2,
        body="متن",
        reply_markup=markup,
        parse_mode="HTML",
    )


def _obs_extra_fresh_sends(bot):
    """Fresh (non-edit) messages to the observer about the extra panel."""
    n = 0
    for c in bot.calls:
        if getattr(c, "_cls", None) == "send_message":
            kw = getattr(c, "_rec_kwargs", {}) or {}
            args = getattr(c, "_rec_args", ())
            chat = kw.get("chat_id", args[0] if args else None)
            text = kw.get("text", args[1] if len(args) > 1 else "")
            if chat == OBS_UID and "استعلام کارآگاهی" in (text or ""):
                n += 1
    return n


class Nam10Night2MirrorDupTest(Nam10NightV2Test, metaclass=_SkipInheritedTests):
    """No-op mirror edits must never spawn duplicate observer panels."""

    async def test_noop_edit_treated_as_success(self):
        self.assertTrue(await _probe_edit(_NoopEditBot()))
        self.assertTrue(await _probe_edit(_NoopMarkupEditBot()))
        # A genuinely failed edit (message deleted) still reports failure.
        self.assertFalse(await _probe_edit(_NotFoundBot()))

    async def test_room31_shape_reissue_never_duplicates_observer(self):
        self._fork_room()
        await self._enter_night()
        g = self.game

        # v2 walk up to the Guide confirmation. The Guide sends the extra
        # investigation to DOCTOR (town, Room-31-shape recipient). Hacker
        # pair is DOCTOR -> SYN, so interception cannot match and the
        # recipient's own original action (doctor save) is already settled
        # — the extra panel materializes right after gdsok.
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=DOC_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        self.assertEqual(g.nmnd_night2_extra_kind, EXTRA_KIND_SENT)
        self.assertEqual(g.nmnd_night2_extra_uid, DOC_UID)
        self.assertTrue(g.nmnd_night2_extra_materialized)
        key = _extra_key(g, DOC_UID)
        ref_before = g.mirror_prompt_messages.get(key, {}).get("observer")

        first = _obs_extra_fresh_sends(self.bot)
        self.assertEqual(first, 1, "extra panel must be delivered once")

        # Simulate Telegram's no-op rejection on the existing panel
        # refs, exactly like production, then re-run the periodic
        # maybe-grant re-render twice (doctor_confirmed-style trigger).
        saved_edit = self.bot.edit_message_text
        saved_markup = self.bot.edit_message_reply_markup

        async def _raise_noop(**kwargs):
            raise _nm_error()

        self.bot.edit_message_text = _raise_noop
        self.bot.edit_message_reply_markup = _raise_noop
        try:
            await night2_maybe_grant_guide_extra(self.bot, self.game)
            await night2_maybe_grant_guide_extra(self.bot, self.game)
        finally:
            self.bot.edit_message_text = saved_edit
            self.bot.edit_message_reply_markup = saved_markup

        self.assertEqual(
            _obs_extra_fresh_sends(self.bot),
            first,
            "no-op re-render must not send a duplicate observer panel",
        )
        ref_after = g.mirror_prompt_messages.get(key, {}).get("observer")
        self.assertEqual(ref_before, ref_after, "observer ref must be stable")

        # The panel stays functional after the simulated no-op updates,
        # and the remaining walk (guard/mine/law/citizen re-renders that
        # each re-invoke the maybe-grant check) adds no duplicates.
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=BOSS_UID)
        await self._press(GUARD_UID, "gdnok", GUARD_UID)
        await self._press(MINE_UID, "minp", MINE_UID, tid=0)
        await self._press(MINE_UID, "minok", MINE_UID)
        await self._press(LAW_UID, "lawp", LAW_UID, tid=0)
        await self._press(LAW_UID, "lawok", LAW_UID)
        await self._press(NATO_UID, "waitok", NATO_UID)
        await self._press(CIT1_UID, "waitok", CIT1_UID)
        await self._press(OBS_UID, "waitok", SYN_UID)
        self.assertEqual(
            _obs_extra_fresh_sends(self.bot),
            first,
            "walk re-renders must keep exactly one observer extra panel",
        )
        await self._press(DOC_UID, "exin", DOC_UID, tid=CIT1_UID)
        self.assertEqual(g.nmnd_night2_extra_target_pending, CIT1_UID)
        await self._press(DOC_UID, "exok", DOC_UID)
        self.assertEqual(g.nmnd_night2_extra_target_uid, CIT1_UID)
        self.assertFalse(_night2_extra_owed_public(g))


def _night2_extra_owed_public(game):
    from bot.nam10.night2 import _night2_extra_owed

    return _night2_extra_owed(game)


if __name__ == "__main__":
    unittest.main()
