"""Namayande-10 Night v2 — post-night handoff reconciliation for the
Rebel assassination window + truthful activation-notice delivery.

Room 31 defect: after Night-2 (NATO) the synthetic Rebel (رامین-یاغی,
observer-mirrored) never saw the daytime assassination entry panel. The
authoritative records show the whole chain armed correctly:

- Hacker ابوالفضل-هکر eliminated on Day 2 by unanimous vote
  (``player.eliminated`` + ``night2.rebel_assassination_unlocked
  [cause=day_vote]``) with the Rebel alive;
- the day-2 window was correctly closed by the defense confirmation
  (``night2.rebel_window_closed``) and the once-per-game activation
  notice was flagged delivered;
- at Day-3 opening (``no_host.day_started_after_night host_day=3``), with
  the room at ``day_discuss`` and only the defense *pick* phase running,
  the panel still never appeared.

Root cause: ``game.nmnd_night2_publication_pending`` is set True at the
Night-2 resolution commit and — outside the game-ended path — its only
other clear was the NEXT night's entry reset. ``nam10_rebel_window_open``
therefore returned False for the entire post-night day and silently
skipped the panel. The fix settles the latch in
``nam10_complete_discipline_and_resolve`` (shared by every settle
point), so every post-night day opens with the window available.

Secondary hardened behavior (same module):
- the one-time activation notice is flagged sent only when a real
  Telegram ref (player DM or Observer mirror) was actually stored; a
  failed delivery audits ``night2.rebel_notice_delivery_failed`` and is
  retried instead of being silently swallowed;
- the Observer copy of the mirrored notice is seat-labelled
  (``observer_same_text=False``) so it is clear which seat owns it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from bot.observer_delivery import PlayerMirrorCb  # noqa: E402
from tests.test_namayande10_night_publish import _SkipInheritedTests  # noqa: E402
from tests.test_namayande10_night_v2 import (  # noqa: E402
    NATO_UID,
    OBS_UID,
    SYN_UID,
)

NOTICE_MARK = "🎯 قابلیت ترور فعال شد"
ENTRY_BUTTON = "🎯 استفاده از قابلیت ترور"
ENTRY_BODY_MARK = "قابلیت ترور شما فعال است."
OBS_LABEL_MARK = "ناظر — پیام صندلی"
ACT_REBEL_OPEN = "rebben"


class _FakeCallback:
    """Minimal callback stand-in for direct act dispatch in tests."""

    def __init__(self):
        self.message = None
        self.answered = []

    async def answer(self, *args, **kwargs):
        self.answered.append((args, kwargs))
        return None


def _rebel_buttons(bot):
    """All rebel mirror buttons currently in the harness bot's sent KBs."""
    out = []
    for _t, kb in bot.kb_segments():
        if kb is None:
            continue
        for row in kb.inline_keyboard:
            for b in row:
                try:
                    cb = PlayerMirrorCb.unpack(b.callback_data or "")
                except TypeError:
                    continue
                if cb is not None and cb.act.startswith("reb"):
                    out.append((cb, getattr(b, "style", None), b.text))
    return out


class Nam10RebelHandoffTest(_v2.Nam10NightV2Test, metaclass=_SkipInheritedTests):
    """Night resolution must not poison the following day's window."""

    # ------------------------------------------------------------ helpers

    def _armed_rebel_room(self):
        """Harness room with the synthetic Rebel (seat 10) unlocked,
        mirroring Room 31's verdict trail: hacker eliminated, Rebel
        alive, unlocked, notice consumed, ability unused, yesterday's
        defense cutoff recorded."""
        self._fork_room()
        from bot.models import Role

        self.game.players[SYN_UID].role = Role.NATO
        self.game.players[NATO_UID].role = Role.CITIZEN
        self.game.nmnd_night2_rebel_unlocked = True
        self.game.nmnd_night2_rebel_assassin_used = False
        self.game.nmnd_night2_rebel_notice_sent = True
        self.game.nmnd_night2_rebel_cutoff_day = 2

    def _enter_day3_open_state(self):
        """Day-3 daylight state mirroring Room 31: yesterday's day-2
        cutoff, current-day defense only in the pick phase."""
        g = self.game
        from bot.models import Phase
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

        g.phase = Phase.MANUAL
        g.nmnd_night2_mode = True
        g.nmnd_narrator_host_day = 3
        g.nmnd_narrator_night_count = 2
        g.nmnd_narrator_step = DAY_DISCUSS
        g.nmnd_night2_rebel_cutoff_day = 2  # yesterday's cutoff only
        g.nam10_day1_defense_active = False
        g.nam10_day1_defense_phase = "pick"

    def _settle_publication(self):
        """Run the shared settle point exactly as the engine does after
        the discipline answer / apply_resolve / game-ended path."""
        from bot.nam10.no_host_night_resolve import (
            nam10_complete_discipline_and_resolve,
        )

        return nam10_complete_discipline_and_resolve(
            self.bot,
            self.game,
            self.manager,
            send_discipline_broadcast=False,
        )

    # ------------------------------------------------------------- tests

    async def test_day3_panel_delivered_after_night_settle(self):
        """Room-31 e2e: with the sticky latch armed, the window is shut
        (the exact silent skip); clearing it at the settle point lets the
        Day-3 opening hook deliver the synthetic Rebel's entry panel."""
        self._armed_rebel_room()
        self._enter_day3_open_state()
        self.game.nmnd_night2_publication_pending = True
        self.game.nmnd_night2_publication_active = True
        self.game.nmnd_night2_publication_stage = "discipline_ask"
        from bot.nam10.rebel_day import nam10_rebel_window_open

        # Before the settle: the sticky latch keeps the window shut and
        # no panel can be delivered (Room 31's silent failure).
        self.assertFalse(nam10_rebel_window_open(self.game))
        await self._settle_publication()
        self.assertFalse(self.game.nmnd_night2_publication_pending)
        self.assertIsNone(self.game.nmnd_night2_publication_stage)
        # The settle hands the room to its pre-day gate (step moves);
        # re-enter the open daylight state the way the real day opening
        # reaches the hook. The window then opens and the opening hook
        # delivers the entry panel through the Observer mirror.
        self._enter_day3_open_state()
        self.assertTrue(nam10_rebel_window_open(self.game))
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        g = self.game
        self.assertEqual(g.nmnd_night2_rebel_panel_day, 3)
        self.assertEqual(g.nmnd_night2_rebel_stage, "entry")
        self.assertEqual(g.nmnd_night2_rebel_panel_uid, SYN_UID)
        entry_key = next(
            (k for k in g.mirror_prompt_messages if k.startswith("reb3:")),
            None,
        )
        self.assertIsNotNone(entry_key, "no reb3 mirror pair registered")
        self.assertTrue(
            g.mirror_prompt_messages[entry_key].get("observer"),
            "observer copy ref missing",
        )
        obs_text = "".join(self.bot.texts_to(OBS_UID))
        self.assertIn(ENTRY_BODY_MARK, obs_text)
        open_cbs = [
            cb for cb, _s, t in _rebel_buttons(self.bot) if t == ENTRY_BUTTON
        ]
        self.assertEqual(len(open_cbs), 1)
        self.assertEqual(open_cbs[0].as_uid, SYN_UID)
        # The synthetic negative uid is never a Telegram recipient.
        self.assertNotIn(ENTRY_BUTTON, "".join(self.bot.texts_to(SYN_UID)))

    async def test_settle_point_idempotent_across_retries(self):
        """Retrying the settle (disc_no_ok replay, restore tick) never
        resurrects the latch."""
        self._fork_room()
        self.game.nmnd_night2_publication_pending = True
        self.game.nmnd_night2_publication_active = True
        self.game.nmnd_night2_publication_stage = "discipline_ask"
        self.game.nmnd_night2_resolved = True
        self.game.nmnd_night2_resolved_night = 2
        await self._settle_publication()
        self.assertFalse(self.game.nmnd_night2_publication_pending)
        await self._settle_publication()
        self.assertFalse(self.game.nmnd_night2_publication_pending)
        self.assertIsNone(self.game.nmnd_night2_publication_stage)

    async def test_day_window_predicate_priorities_unchanged(self):
        """The latch is one gate among several; the others still close
        the window when their own condition holds."""
        self._armed_rebel_room()
        self._enter_day3_open_state()
        from bot.nam10.rebel_day import nam10_rebel_window_open

        # Clean opening state: open.
        self.assertTrue(nam10_rebel_window_open(self.game))
        # Night stage / publication pending each close it independently.
        from bot.nam10.nmnd_narrator import NIGHT_ACTIONS

        self.game.nmnd_narrator_step = NIGHT_ACTIONS
        self.assertFalse(nam10_rebel_window_open(self.game))
        self._enter_day3_open_state()
        self.game.nmnd_night2_publication_pending = True
        self.assertFalse(nam10_rebel_window_open(self.game))
        self._enter_day3_open_state()

    async def test_defense_confirm_cutoff_still_blocks_after_settle(self):
        """Even after the settle, today's defense-candidates confirmation
        closes the window and preserves the unused charge."""
        self._armed_rebel_room()
        await self._settle_publication()
        self._enter_day3_open_state()  # settle moves the step to its gate
        from bot.nam10.rebel_day import (
            close_nam10_rebel_window,
            nam10_rebel_window_open,
        )

        self.assertTrue(await close_nam10_rebel_window(self.bot, self.game))
        self.assertFalse(nam10_rebel_window_open(self.game))
        self.assertEqual(self.game.nmnd_night2_rebel_cutoff_day, 3)
        self.assertFalse(self.game.nmnd_night2_rebel_assassin_used)

    async def test_duplicate_day_opening_sends_no_second_panel(self):
        self._armed_rebel_room()
        await self._settle_publication()
        self._enter_day3_open_state()  # settle moves the step to its gate
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        first_day = self.game.nmnd_night2_rebel_panel_day
        first_count = (
            "".join(self.bot.texts_to(OBS_UID)).count(ENTRY_BUTTON)
        )
        await send_nam10_rebel_day_opening(self.bot, self.game)
        self.assertEqual(self.game.nmnd_night2_rebel_panel_day, first_day)
        self.assertEqual(
            "".join(self.bot.texts_to(OBS_UID)).count(ENTRY_BUTTON),
            first_count,
        )

    async def test_observer_operates_synthetic_rebel_entry(self):
        """The mirrored Day-3 entry button is operable on behalf of the
        synthetic Rebel seat."""
        self._armed_rebel_room()
        await self._settle_publication()
        self._enter_day3_open_state()  # settle moves the step to its gate
        from bot.nam10.rebel_day import dispatch_nam10_rebel_act, send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, self.game)
        open_cbs = [
            cb for cb, _s, t in _rebel_buttons(self.bot) if t == ENTRY_BUTTON
        ]
        self.assertEqual(len(open_cbs), 1)
        self.assertEqual(open_cbs[0].as_uid, SYN_UID)
        await dispatch_nam10_rebel_act(
            _FakeCallback(),
            self.bot,
            self.game,
            self.manager,
            actor_uid=OBS_UID,  # Observer operating the synthetic seat
            act=ACT_REBEL_OPEN,
            as_uid=SYN_UID,
            tid=0,
        )
        self.assertEqual(self.game.nmnd_night2_rebel_stage, "target")
        picks = [
            cb for cb, _s, _t in _rebel_buttons(self.bot) if cb.act == "rebpick"
        ]
        self.assertTrue(picks)
        self.assertEqual(picks[0].as_uid, SYN_UID)

    async def test_notice_flag_requires_real_ref(self):
        """A failed ghost delivery must not mark the notice as sent and
        must be auditable; the synthetic uid is never a recipient."""
        self._fork_room()
        from bot.models import Role

        self.game.players[SYN_UID].role = Role.NATO
        self.game.players[NATO_UID].role = Role.CITIZEN
        self.game.nmnd_night2_rebel_unlocked = True
        self.game.nmnd_night2_rebel_notice_sent = False
        from bot.models import Phase

        game = self.game
        game.phase = Phase.MANUAL
        game.nmnd_night2_mode = True
        # Delivery impossible: no observer registered, synthetic seat.
        game.observer_user_id = None
        game.observer_full_name = None
        from bot.nam10.rebel_day import dispatch_nam10_rebel_activation

        await dispatch_nam10_rebel_activation(self.bot, game)
        self.assertFalse(game.nmnd_night2_rebel_notice_sent)
        self.assertEqual("".join(self.bot.texts_to(SYN_UID)), "")
        notice_key = next(
            (k for k in game.mirror_prompt_messages if "rebnotice" in k),
            None,
        )
        if notice_key is not None:
            self.assertIsNone(
                game.mirror_prompt_messages[notice_key].get("observer")
            )
            self.assertIsNone(
                game.mirror_prompt_messages[notice_key].get("player")
            )
        # Retry with the observer registered delivers and flags it.
        game.observer_user_id = OBS_UID
        game.observer_full_name = "Adrian"
        game.observer_prompt_status = "registered"
        await dispatch_nam10_rebel_activation(self.bot, game)
        self.assertTrue(game.nmnd_night2_rebel_notice_sent)

    async def test_notice_observer_copy_is_seat_labelled(self):
        """The Observer's mirrored notice identifies the owning seat."""
        self._armed_rebel_room()
        await self._settle_publication()
        self._enter_day3_open_state()  # settle moves the step to its gate
        game = self.game
        game.nmnd_night2_rebel_notice_sent = False
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        await send_nam10_rebel_day_opening(self.bot, game)
        text = "".join(self.bot.texts_to(OBS_UID))
        self.assertIn(OBS_LABEL_MARK, text)
        self.assertIn(NOTICE_MARK, text)
        # The seat label carries the rebel seat + role context.
        self.assertIn("۱۰", text)


if __name__ == "__main__":
    unittest.main()
