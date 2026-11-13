#!/usr/bin/env python3
"""Namayande quick-fix regressions: Guide identity name resolution and
the Mine Layer self-target restriction (Room 37 follow-up).

- Room 37 case: the Guide selected a Mafia member and was eliminated the
  same night; the private Mafia-identity notice must still show the
  Guide's real display name (no '؟'), resolving from the stored player
  record. /myname custom-name priority is preserved.
- Mine Layer: self button absent, self picks rejected server-side
  (incl. forged callbacks), confirmation cannot commit a self-placement
  while valid placements and 'انتخابی ندارم' stay unchanged.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_expansion as _exp  # noqa: E402
from tests.test_namayande10_night_publish import (  # noqa: E402
    _SkipInheritedTests,
)
from tests.test_namayande10_night_v2 import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUIDE_UID,
    MINE_UID,
    SHIAD_UID,
    SYN_UID,
    Nam10NightV2Test,
)

from bot.observer_delivery import PlayerMirrorCb  # noqa: E402

NOTICE_MARK = "🧭 شناسایی راهنما"
INVALID_ALERT = "نامعتبر."
MINE_MARK = "انتخاب مین‌گذار"
NONE_OPT = "انتخابی ندارم"


class _SkipAllInherited(_SkipInheritedTests):
    pass


class Room37GuideIdentityTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """Guide dead the same night -> notice still resolves the name."""

    async def _guide_picks_mafia_then_dies(self):
        """Mafia-member recipient with no Hacker intercept (Room 32 walk),
        then the Guide is eliminated the same night (Room 37 shape)."""
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=SHIAD_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        g = self.game
        self.assertEqual(
            g.nmnd_night2_guide_uids.get(
                int(g.nmnd_narrator_night_count or 1)
            ),
            SHIAD_UID,
        )
        # Room 37: the Guide dies before the Mafia actions settle.
        g.players[GUIDE_UID].is_alive = False

    async def test_dead_guide_name_resolved_no_question_mark(self):
        from bot.nam10.night2 import (
            EXTRA_KIND_MAFIA_ID,
            _guide_holder_uid,
            _guide_identity_uid,
        )

        self._fork12()
        await self._enter_night()
        await self._guide_picks_mafia_then_dies()
        g = self.game
        self.assertEqual(g.nmnd_night2_extra_kind, EXTRA_KIND_MAFIA_ID)
        # Alive-only lookup fails; the identity fallback still resolves.
        self.assertIsNone(_guide_holder_uid(g))
        self.assertEqual(_guide_identity_uid(g), GUIDE_UID)
        # Nothing delivered yet (shot unsettled).
        self.assertEqual(
            int(bool(g.nmnd_night2_dispositions.get(
                "mafia_id_notified:%d" % SHIAD_UID
            ))),
            0,
        )
        self.assertFalse(
            any(NOTICE_MARK in t for t in self.bot.texts_to(SHIAD_UID))
        )
        # The Boss settles the plain shot -> delayed notice delivers.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        texts = self.bot.texts_to(SHIAD_UID)
        notices = [t for t in texts if NOTICE_MARK in t]
        self.assertTrue(notices, texts[-4:])
        self.assertEqual(len(notices), 1)
        joined = "".join(notices)
        # fork12 seat mapping puts the Guide on seat 6; resolved despite death
        self.assertIn("بازیکن 6", joined)
        self.assertNotIn("؟", joined)
        self.assertEqual(
            g.nmnd_night2_dispositions.get("mafia_id_notified:%d"
                                           % SHIAD_UID),
            "sent",
        )
        self.assertTrue(g.namayande_guide_identity_revealed_to_mafia)
        # Replay never duplicates.
        from bot.nam10.night2 import night2_maybe_grant_guide_extra

        await night2_maybe_grant_guide_extra(self.bot, g)
        self.assertEqual(
            len(
                [
                    t
                    for t in self.bot.texts_to(SHIAD_UID)
                    if NOTICE_MARK in t
                ]
            ),
            1,
        )

    async def test_myname_priority_on_guide_notice(self):
        import bot.app_state as _app

        _app.manager.user_display_names[GUIDE_UID] = "نام دلخواه"
        try:
            self._fork12()
            await self._enter_night()
            await self._guide_picks_mafia_then_dies()
            await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
            await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
            await self._press(BOSS_UID, "shtok", BOSS_UID)
        finally:
            _app.manager.user_display_names.pop(GUIDE_UID, None)
        notices = [
            t
            for t in self.bot.texts_to(SHIAD_UID)
            if NOTICE_MARK in t
        ]
        self.assertTrue(notices)
        joined = "".join(notices)
        self.assertIn("نام دلخواه", joined)  # /myname beats full_name
        self.assertNotIn("؟", joined)
        self.assertNotIn("بازیکن 5", joined)


class GuideDisplayNamePriorityTest(unittest.TestCase):
    """Display-name priority chain: /myname -> full_name; no @username."""

    def test_priority_and_no_username(self) -> None:
        from bot.game import GameManager
        from bot.models import Player
        from bot.no_host_role_pick_common import player_button_name

        gm = GameManager()
        p = Player(
            user_id=55, full_name="تله‌گرام نام", username="tguser"
        )
        self.assertEqual(player_button_name(p, 55), "تله‌گرام نام")
        self.assertEqual(
            player_button_name(p, 55, "نام‌کاستوم"), "نام‌کاستوم"
        )
        self.assertNotIn("@tguser", player_button_name(p, 55))
        # the manager-level tag keeps the same priority
        gm.user_display_names[55] = "نام‌کاستوم"
        self.assertEqual(gm.format_player_tag(p), "نام‌کاستوم")
        self.assertNotIn("@tguser", gm.format_player_tag(p))


class MineSelfTargetTest(Nam10NightV2Test):
    """Mine Layer self-target restriction (10-player harness)."""

    def _mine_pick_tids(self):
        tids = []
        for btn in self._button_objects(MINE_MARK):
            if not (btn.callback_data or "").startswith("pmr:"):
                continue
            cb = PlayerMirrorCb.unpack(btn.callback_data)
            if cb is not None and cb.act == "minp" and cb.tid:
                tids.append(cb.tid)
        return tids

    def _mine_texts(self):
        return [b.text for b in self._button_objects(MINE_MARK)]

    async def test_self_button_absent_others_present(self):
        self._fork_room()
        await self._enter_night()
        # A pick re-renders the panel with the current selection.
        await self._press(MINE_UID, "minp", MINE_UID, tid=DOC_UID)
        tids = self._mine_pick_tids()
        self.assertNotIn(MINE_UID, tids)
        for uid in (BOSS_UID, DOC_UID, CIT1_UID, SYN_UID):
            self.assertIn(uid, tids)
        # the none-option survives
        self.assertTrue(any(NONE_OPT in t for t in self._mine_texts()))

    async def test_self_pick_rejected_server_side(self):
        self._fork_room()
        await self._enter_night()
        # Forged/stale callback targeting self: rejected, nothing set.
        await self._press(MINE_UID, "minp", MINE_UID, tid=MINE_UID)
        self.assertTrue(
            any(INVALID_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(self.game.nmnd_night2_mine_pending_uid)
        self.assertIsNone(self.game.nmnd_night2_mine_uid)
        self.assertFalse(self.game.nmnd_night2_mine_used)

    async def test_confirm_cannot_commit_stale_self_pending(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        # Simulate a pre-rule pending self-target (stale state).
        g.nmnd_night2_mine_pending_uid = MINE_UID
        await self._press(MINE_UID, "minok", MINE_UID)
        self.assertTrue(
            any(INVALID_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(g.nmnd_night2_mine_uid)
        self.assertFalse(g.nmnd_night2_mine_used)
        self.assertIsNone(g.nmnd_night2_dispositions.get("mine_none"))

    async def test_valid_placement_unchanged(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        await self._press(MINE_UID, "minp", MINE_UID, tid=DOC_UID)
        self.assertEqual(g.nmnd_night2_mine_pending_uid, DOC_UID)
        await self._press(MINE_UID, "minok", MINE_UID)
        self.assertEqual(g.nmnd_night2_mine_uid, DOC_UID)
        self.assertTrue(g.nmnd_night2_mine_used)
        self.assertEqual(g.nmnd_night2_mine_used_night, 1)


if __name__ == "__main__":
    unittest.main()
