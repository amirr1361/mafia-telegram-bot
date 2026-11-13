"""Namayande (10-13) — integrated regressions for the three rule changes:

A. Mine / Doctor / Mafia-shot FINAL matrix: all eight combinations,
   Hacker-nullified Doctor saves, previously-placed (prior-night) mines,
   permanent mine consumption and the no-sacrifice guarantee after a
   neutralized shot.
B. Guide-identity permanent NATO restriction
   (``namayande_guide_identity_revealed_to_mafia``): flag only after a
   confirmed successful disclosure delivery, removed from the NATO
   role-guess panel in both 10/11 (shooter-owned) and 12/13
   (independent agent-owned) architectures, forged/stale callbacks
   rejected without consuming the NATO opportunity, snapshot/restart
   and per-night-reset persistence.
C. Mandatory temporary-Sniper shot: the pending obligation survives a
   snapshot round-trip and still blocks night completion after restore.
"""

import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/root/mafia-telegram-bot")

from bot.game_snapshot import (  # noqa: E402
    game_from_snapshot_dict,
    game_to_snapshot_dict,
)
from bot.models import Phase  # noqa: E402
from bot.nam10.nmnd_narrator import Role  # noqa: E402
from bot.nam10.night2 import (  # noqa: E402
    BOSS_PHASE_NATO_ROLE,
    PENDING_COLLECTING,
    PENDING_RESOLVED,
    night2_required_keys,
    night2_run_resolution,
)
from tests.test_namayande10_expansion import (  # noqa: E402
    AGT_UID,
    NamExpansionRoomTest,
)
from tests.test_namayande10_night_v2 import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUIDE_UID,
    GUARD_UID,
    MINE_UID,
    Nam10NightV2ResolveTest,
    NATO_UID,
    OBS_UID,
    SHIAD_UID,
    SYN_UID,
)

GUIDE_NOTICE_MARK = "شناسایی راهنما"
NATO_ROLE_PANEL_MARK = "ناتویی — انتخاب نقش"
GUIDE_REMOVED_ALERT = "این نقش دیگر برای حدس ناتو در دسترس نیست."


class NamMineDoctorMatrixTest(Nam10NightV2ResolveTest):
    """All eight matrix combinations + Hacker nullification + prior-night
    mines. Every neutralized outcome must never require a Mafia
    sacrifice; every detonated outcome must."""

    async def test_no_mine_neutralized_save_survives(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2, shot_target=CIT1_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["accepted"])
        self.assertFalse(res["eliminated"])
        self.assertTrue(res["protected_by_doctor"])
        self.assertFalse(res["had_mine"])
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)
        self.assertEqual(self.game.nmnd_night2_mine_events, [])

    async def test_no_mine_neutralized_no_save_dies(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2, shot_target=CIT1_UID, doc_pick=DOC_UID, mine_pick=0
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertFalse(res["protected_by_doctor"])
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_no_mine_plain_save_survives(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1, shot_target=CIT1_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertFalse(res["eliminated"])
        self.assertTrue(res["protected_by_doctor"])
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_no_mine_plain_no_save_dies(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1, shot_target=CIT1_UID, doc_pick=DOC_UID, mine_pick=0
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_neutralized_nullified_save_mine_still_neutralized(self):
        # Hacker pair (DOC -> CIT1) intercepts the Doctor's save; with
        # neutralization the mine is still consumed and the target dies
        # by the ordinary shot — no sacrifice.
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=CIT1_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertFalse(res["protected_by_doctor"])
        self.assertEqual(res["mine_disposition"], "neutralized")
        self.assertTrue(self.game.nmnd_night2_mine_events[0]["neutralized"])
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_plain_nullified_save_no_mine_dies(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=CIT1_UID,
            mine_pick=0,
            law_pick=0,
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertFalse(res["protected_by_doctor"])
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_prior_night_mine_plain_detonates_casualty_required(self):
        # A mine placed on a previous night is still active; the plain
        # shot detonates it regardless of the Doctor's save.
        self._fork_room()
        await self._enter_night()
        self.game.nmnd_night2_active_mine_uid = CIT1_UID
        await self._walk_v2(
            boss_tid=1, shot_target=CIT1_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertTrue(res["doctor_save_ineffective"])
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)

    async def test_prior_night_mine_neutralized_save_survives(self):
        self._fork_room()
        await self._enter_night()
        self.game.nmnd_night2_active_mine_uid = CIT1_UID
        await self._walk_v2(
            boss_tid=2, shot_target=CIT1_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertFalse(res["eliminated"])
        self.assertTrue(res["protected_by_doctor"])
        self.assertEqual(res["mine_disposition"], "neutralized")
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_neutralized_outcomes_never_require_sacrifice(self):
        self._fork_room()
        await self._enter_night()
        self.game.nmnd_night2_active_mine_uid = CIT1_UID
        await self._walk_v2(
            boss_tid=2, shot_target=CIT1_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        outcome = self.game.nmnd_night2_outcome
        pub = outcome.get("publication") or {}
        self.assertNotIn(
            "mine_casualty_selection", list(pub.get("pending_items") or [])
        )
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)
        # Mine permanently consumed: a later plain shot cannot re-detonate.
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)

    async def test_resolution_idempotent_repeat_same_result(self):
        self._fork_room()
        await self._enter_night()
        self.game.nmnd_night2_active_mine_uid = CIT1_UID
        await self._walk_v2(
            boss_tid=2, shot_target=CIT1_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        first = dict(self.game.nmnd_night2_shot_result)
        again = night2_run_resolution(self.game)
        self.assertEqual(
            (again.get("shot") or {}).get("result", first), first
        )
        self.assertEqual(
            len(self.game.nmnd_night2_mine_events), 1
        )


class NamGuideNatoRestrictionTest(Nam10NightV2ResolveTest):
    """10-player shooter-owned NATO architecture."""

    async def test_flag_initially_false(self):
        self._fork_room()
        await self._enter_night()
        self.assertFalse(self.game.namayande_guide_identity_revealed_to_mafia)

    async def test_town_recipient_keeps_flag_false(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(guide_target=CIT1_UID)
        self.assertEqual(self.game.nmnd_night2_extra_kind, "extra_sent")
        self.assertFalse(self.game.namayande_guide_identity_revealed_to_mafia)

    async def test_mafia_selected_before_shot_settled_flag_false(self):
        self._fork_room()
        await self._enter_night()
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=NATO_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)
        self.assertEqual(self.game.nmnd_night2_extra_kind, "mafia_id")
        self.assertFalse(self.game.namayande_guide_identity_revealed_to_mafia)
        self.assertFalse(
            any(GUIDE_NOTICE_MARK in t for t in self.bot.texts_to(NATO_UID))
        )

    async def test_successful_disclosure_sets_flag(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1, shot_target=DOC_UID, doc_pick=CIT1_UID, mine_pick=0
        )
        g = self.game
        self.assertTrue(g.namayande_guide_identity_revealed_to_mafia)
        self.assertEqual(
            g.nmnd_night2_dispositions.get("mafia_id_notified:%d" % NATO_UID),
            "sent",
        )
        self.assertTrue(
            any(GUIDE_NOTICE_MARK in t for t in self.bot.texts_to(NATO_UID))
        )
        self.assertEqual(g.nmnd_night2_phase, PENDING_RESOLVED)

    async def test_failed_delivery_then_retry_sets_flag_only_after_success(
        self,
    ):
        self._fork_room()
        await self._enter_night()
        with patch(
            "bot.observer_delivery.safe_send_message_return",
            return_value=None,
        ):
            await self._walk_v2(
                boss_tid=1,
                shot_target=DOC_UID,
                doc_pick=CIT1_UID,
                mine_pick=0,
            )
        g = self.game
        self.assertFalse(g.namayande_guide_identity_revealed_to_mafia)
        self.assertFalse(
            g.nmnd_night2_dispositions.get("mafia_id_notified:%d" % NATO_UID)
        )
        # A later reconcile tick retries the notice; the flag engages
        # only after the confirmed successful delivery.
        from bot.nam10.night2 import night2_maybe_grant_guide_extra

        await night2_maybe_grant_guide_extra(self.bot, g)
        self.assertTrue(g.namayande_guide_identity_revealed_to_mafia)
        self.assertEqual(
            g.nmnd_night2_dispositions.get("mafia_id_notified:%d" % NATO_UID),
            "sent",
        )

    async def test_nato_role_panel_omits_guide_after_reveal(self):
        self._fork_room()
        await self._enter_night()
        from bot.nam10.night2 import _send_nato_role_panel

        # Restriction off: راهنما offered.
        await _send_nato_role_panel(self.bot, self.game, BOSS_UID)
        self.assertIn(
            "راهنما", [b.text for b in self._button_objects(
                NATO_ROLE_PANEL_MARK)]
        )
        # Successful disclosure → permanent removal.
        self.game.namayande_guide_identity_revealed_to_mafia = True
        await _send_nato_role_panel(self.bot, self.game, BOSS_UID)
        texts = [b.text for b in self._button_objects(NATO_ROLE_PANEL_MARK)]
        self.assertNotIn("راهنما", texts)
        for kept in ("پزشک", "وکیل", "محافظ", "مین‌گذار"):
            self.assertIn(kept, texts)

    async def test_forged_and_stale_guide_callbacks_rejected_no_consumption(
        self,
    ):
        self._fork_room()
        await self._enter_night()
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        g = self.game
        self.assertEqual(g.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)
        self.assertEqual(g.nmnd_night2_nato_used_night, 1)
        # The disclosure lands between the stages: the rendered panel is
        # stale and راهنما must no longer be selectable.
        g.namayande_guide_identity_revealed_to_mafia = True
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=2)
        self.assertTrue(
            any(GUIDE_REMOVED_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(g.nmnd_night2_nato_pending_role_idx)
        # A forged pending راهنما selection can never be confirmed.
        g.nmnd_night2_nato_pending_role_idx = 2
        await self._press(BOSS_UID, "nrok", BOSS_UID)
        self.assertTrue(
            any(GUIDE_REMOVED_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(g.nmnd_night2_nato_pending_role_idx)
        self.assertIsNone(g.nmnd_night2_nato_role)
        self.assertEqual(g.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)
        # Valid roles remain fully usable.
        await self._press(BOSS_UID, "nrole", BOSS_UID, tid=1)
        self.assertEqual(g.nmnd_night2_nato_pending_role_idx, 1)
        await self._press(BOSS_UID, "nrok", BOSS_UID)
        self.assertEqual(g.nmnd_night2_nato_role, Role.DOCTOR.value)

    async def test_flag_survives_snapshot_and_per_night_reset(self):
        self._fork_room()
        await self._enter_night()
        self.game.namayande_guide_identity_revealed_to_mafia = True
        payload = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(payload)
        self.assertTrue(restored.namayande_guide_identity_revealed_to_mafia)
        from bot.nam10.night2 import _reset_per_night_state

        _reset_per_night_state(self.game, 2)
        self.assertTrue(self.game.namayande_guide_identity_revealed_to_mafia)

    async def test_synthetic_mafia_disclosure_via_observer_mirror(self):
        self._fork_room()
        g = self.game
        # Swap: the synthetic seat becomes the Rebel (mafia member) and
        # the real Rebel seat becomes a citizen.
        g.players[NATO_UID].role = Role.CITIZEN
        g.players[SYN_UID].role = Role.NATO
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=DOC_UID,
            doc_pick=CIT1_UID,
            hack_src=GUARD_UID,
            hack_dst=CIT1_UID,
            guide_target=SYN_UID,
            mine_pick=0,
        )
        self.assertTrue(g.namayande_guide_identity_revealed_to_mafia)
        self.assertEqual(
            g.nmnd_night2_dispositions.get("mafia_id_notified:%d" % SYN_UID),
            "sent",
        )
        # The authorised Observer mirror carried the disclosure.
        self.assertTrue(
            any(GUIDE_NOTICE_MARK in t for t in self.bot.texts_to(OBS_UID))
        )


class Nam12GuideNatoRestrictionTest(NamExpansionRoomTest):
    """12/13-player independent-NATO architecture."""

    async def test_disclosure_after_independent_nato_stages(self):
        self._fork12()
        await self._enter_night()
        # NATO completes through the agent; the Guide's disclosure to the
        # Rebel waits for it, then engages the restriction.
        await self._walk12(
            boss_tid=3,
            nato_role_tid=1,
            nato_target=GUIDE_UID,
            guide_target=NATO_UID,
            sniper_target=BOSS_UID,
        )
        g = self.game
        self.assertTrue(g.namayande_guide_identity_revealed_to_mafia)
        self.assertEqual(g.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(
            any(GUIDE_NOTICE_MARK in t for t in self.bot.texts_to(NATO_UID))
        )
        from bot.nam10.night2 import _send_nato_role_panel

        await _send_nato_role_panel(self.bot, g, AGT_UID)
        texts = [b.text for b in self._button_objects(NATO_ROLE_PANEL_MARK)]
        self.assertNotIn("راهنما", texts)
        for kept in ("پزشک", "وکیل", "محافظ", "مین‌گذار"):
            self.assertIn(kept, texts)

    async def test_forged_guide_callbacks_rejected_no_consumption(self):
        self._fork12()
        await self._enter_night()
        from bot.nam10.night2 import _send_nato_role_panel

        # Control (restriction off): the agent's panel offers راهنما.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(
            self.game.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE
        )
        self.assertIn(
            "راهنما",
            [b.text for b in self._button_objects(NATO_ROLE_PANEL_MARK)],
        )
        g = self.game
        # The disclosure lands between the stages: the rendered panel is
        # stale and راهنما must no longer be selectable.
        g.namayande_guide_identity_revealed_to_mafia = True
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        self.assertTrue(
            any(GUIDE_REMOVED_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(g.nmnd_night2_nato_pending_role_idx)
        # A forged pending راهنما selection can never be confirmed.
        g.nmnd_night2_nato_pending_role_idx = 2
        await self._press(AGT_UID, "nrok", AGT_UID)
        self.assertTrue(
            any(GUIDE_REMOVED_ALERT in (a or "") for a in self.bot.acks())
        )
        self.assertIsNone(g.nmnd_night2_nato_pending_role_idx)
        self.assertIsNone(g.nmnd_night2_nato_role)
        self.assertEqual(g.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)
        # Valid roles remain usable; the panel re-renders without راهنما.
        await _send_nato_role_panel(self.bot, g, AGT_UID)
        texts = [b.text for b in self._button_objects(NATO_ROLE_PANEL_MARK)]
        self.assertNotIn("راهنما", texts)
        await self._press(AGT_UID, "nrole", AGT_UID, tid=1)
        self.assertEqual(g.nmnd_night2_nato_pending_role_idx, 1)
        await self._press(AGT_UID, "nrok", AGT_UID)
        self.assertEqual(g.nmnd_night2_nato_role, Role.DOCTOR.value)


class NamSniperMandatoryDurabilityTest(NamExpansionRoomTest):
    """Pending mandatory-Sniper obligation is durable across snapshot
    round-trips and still blocks normal night completion."""

    async def test_pending_sniper_survives_snapshot_and_blocks_finish(self):
        self._fork12()
        await self._enter_night()
        await self._walk12(soldier_target=CIT1_UID)
        self.assertIn("n2sniper", night2_required_keys(self.game))
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_COLLECTING)
        payload = game_to_snapshot_dict(self.game)
        restored = game_from_snapshot_dict(payload)
        self.assertEqual(restored.nmnd_night2_soldier_grant_status, "delivered")
        self.assertFalse(restored.nmnd_night2_sniper_resolved)
        self.assertIn("n2sniper", night2_required_keys(restored))
        # Completing the obligation resolves the night exactly once.
        await self._press(CIT1_UID, "tsnp", CIT1_UID, tid=BOSS_UID)
        await self._press(CIT1_UID, "tsnok", CIT1_UID)
        self.assertTrue(self.game.nmnd_night2_sniper_resolved)
        self.assertNotIn("n2sniper", night2_required_keys(self.game))
        self.assertEqual(self.game.nmnd_night2_phase, PENDING_RESOLVED)


def load_tests(loader, tests, pattern):
    """Collect only the tests defined in this module.

    The harness classes are shared TestCase bases carrying their own
    suites; collecting them through these subclasses would re-run every
    inherited harness test.
    """
    suite = unittest.TestSuite()
    for cls in (
        NamMineDoctorMatrixTest,
        NamGuideNatoRestrictionTest,
        Nam12GuideNatoRestrictionTest,
        NamSniperMandatoryDurabilityTest,
    ):
        for name in sorted(n for n in cls.__dict__ if n.startswith("test_")):
            suite.addTest(cls(name))
    return suite


if __name__ == "__main__":
    unittest.main()
