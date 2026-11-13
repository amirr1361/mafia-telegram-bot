"""Namayande-10 — Tasks 1-3 regression tests.

1. Shooter succession Boss → Rebel → Hacker with a shared once-per-game
   NATO allowance and the inherited-shot obligations (incl. the Hacker's
   separate intercept duty).
2. Public Lawyer protection defence-skip announcement (buttonless,
   idempotent, helper popup).
3. Guardian armor re-grant Room-12 regression: a fresh Night-N pick must
   cover the day after night N even when a stale expired record stands.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_night_publish import _SkipInheritedTests  # noqa: E402
from tests.test_namayande10_night_v2 import (  # noqa: E402
    ASSIST_UID,
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    GUARD_UID,
    LAW_UID,
    MINE_UID,
    NATO_UID,
    OBS_UID,
    SHIAD_UID,
    SYN_UID,
)

from bot.nam10.night2 import (  # noqa: E402
    ALERT_STALE,
    PENDING_COLLECTED,
    night2_active_shooter,
    night2_rebel_assassination_effect,
    night2_required_keys,
    night2_run_resolution,
    nam10_night2_entry_dispatch,
)
from bot.observer_delivery import mirror_ui_claim_key  # noqa: E402

SHOOTER_MENU_MARK = "جانشین رئیس مافیا"
BOSS_MENU_MARK = "انتخاب قابلیت رئیس مافیا"
LAWYER_ANNOUNCE_MARK = "به دلیل حمایت معتبر وکیل در شب گذشته، وارد دفاعیه نمی‌شود."
DOCTOR_GUESS_IDX = 1  # N2_NATO_GUESS_ROLES[0] == Role.DOCTOR


class Nam10SuccessionNatoLawyerArmorTest(
    _v2.Nam10NightV2Test, metaclass=_SkipInheritedTests
):
    # ------------------------------------------------------------- helpers

    def _menu_tids(self, mark: str) -> set[int]:
        from bot.observer_delivery import PlayerMirrorCb

        tids: set[int] = set()
        for text, kb in self.bot.kb_segments():
            if mark in text and kb is not None:
                for row in kb.inline_keyboard:
                    for b in row:
                        cb = PlayerMirrorCb.unpack(b.callback_data or "")
                        if cb is not None:
                            tids.add(cb.tid)
        return tids

    async def _dispatch_night2_with(self, g, *, dead=()):
        await self._enter_night()
        for uid in dead:
            g.players[uid].is_alive = False
        g.nmnd_narrator_night_count = 2
        ok = await nam10_night2_entry_dispatch(self.bot, g, self.manager)
        self.assertTrue(ok)
        return g

    def _resolution_game(self, g):
        g.nmnd_night2_night_count = g.nmnd_narrator_night_count
        g.nmnd_night2_phase = PENDING_COLLECTED
        g.nmnd_night2_resolved = False
        g.nmnd_night2_resolved_night = None
        g.nmnd_night2_outcome_committed = False
        return g

    # -------------------------------------- Task 1: succession + shared NATO

    async def test_boss_alive_shoots_with_nato_option(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        self.assertEqual(night2_active_shooter(g).user_id, BOSS_UID)
        tids = self._menu_tids(BOSS_MENU_MARK)
        self.assertIn(3, tids)

    async def test_rebel_inherits_shot_and_shared_nato(self):
        g = self._fork_room()
        await self._dispatch_night2_with(g, dead=(BOSS_UID,))
        self.assertEqual(night2_active_shooter(g).user_id, NATO_UID)
        # NATO unused → the Rebel shooter sees the NATO option too.
        tids = self._menu_tids(SHOOTER_MENU_MARK)
        self.assertEqual(tids, {1, 2, 3})

    async def test_rebel_shooter_uses_nato_end_to_end(self):
        g = self._fork_room()
        await self._dispatch_night2_with(g, dead=(BOSS_UID,))
        await self._press(NATO_UID, "bmode", NATO_UID, tid=3)
        self.assertEqual(g.nmnd_night2_boss_phase, "nato_role")
        self.assertTrue(g.nmnd_night2_nato_used)
        self.assertEqual(g.nmnd_night2_nato_used_night, 2)
        # Stage 1: pick the Doctor guess, confirm.
        await self._press(NATO_UID, "nrole", NATO_UID, tid=DOCTOR_GUESS_IDX)
        await self._press(NATO_UID, "nrok", NATO_UID)
        self.assertEqual(g.nmnd_night2_boss_phase, "nato_player")
        # Stage 2: pick the Doctor player, confirm.
        await self._press(NATO_UID, "npl", NATO_UID, tid=DOC_UID)
        await self._press(NATO_UID, "npok", NATO_UID)
        self.assertEqual(g.nmnd_night2_nato_target_uid, DOC_UID)
        self.assertEqual(g.nmnd_night2_boss_phase, "done")
        self.assertNotIn("NATO", night2_required_keys(g))

    async def test_hacker_third_in_line_gets_both_panels(self):
        g = self._fork_room()
        await self._dispatch_night2_with(
            g, dead=(BOSS_UID, NATO_UID)
        )
        self.assertEqual(night2_active_shooter(g).user_id, SHIAD_UID)
        keys = night2_required_keys(g)
        self.assertIn("SHIAD", keys)
        self.assertNotIn("MAFIA_BOSS", keys)
        self.assertNotIn("NATO", keys)
        # Both obligations surfaced: intercept panel + shooting menu.
        self.assertTrue(
            any(SHOOTER_MENU_MARK in t for t in self.bot.texts_to(SHIAD_UID))
        )
        self.assertTrue(
            any("هکر" in t for t in self.bot.texts_to(SHIAD_UID))
        )
        # Intercept alone must NOT clear the SHIAD key while the shot is owed.
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=LAW_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        self.assertEqual(list(g.nmnd_night2_hacker_uids), [CIT1_UID, LAW_UID])
        self.assertIn("SHIAD", night2_required_keys(g))
        # Completing the inherited shot clears it.
        await self._press(SHIAD_UID, "bmode", SHIAD_UID, tid=1)
        await self._press(SHIAD_UID, "sht", SHIAD_UID, tid=MINE_UID)
        await self._press(SHIAD_UID, "shtok", SHIAD_UID)
        self.assertNotIn("SHIAD", night2_required_keys(g))

    async def test_nato_used_by_boss_unavailable_to_rebel(self):
        g = self._fork_room()
        g.nmnd_night2_nato_used = True
        g.nmnd_night2_nato_used_night = 1
        await self._dispatch_night2_with(g, dead=(BOSS_UID,))
        tids = self._menu_tids(SHOOTER_MENU_MARK)
        self.assertEqual(tids, {1, 2})
        await self._press(NATO_UID, "bmode", NATO_UID, tid=3)
        self.assertIn(ALERT_STALE, self.bot.acks())
        self.assertIsNone(g.nmnd_night2_boss_mode)

    async def test_nato_used_by_rebel_unavailable_to_hacker(self):
        g = self._fork_room()
        g.nmnd_night2_nato_used = True
        g.nmnd_night2_nato_used_night = 1
        await self._dispatch_night2_with(
            g, dead=(BOSS_UID, NATO_UID)
        )
        tids = self._menu_tids(SHOOTER_MENU_MARK)
        self.assertEqual(tids, {1, 2})
        await self._press(SHIAD_UID, "bmode", SHIAD_UID, tid=3)
        self.assertIn(ALERT_STALE, self.bot.acks())
        self.assertIsNone(g.nmnd_night2_boss_mode)

    async def test_no_shooter_does_not_deadlock_readiness(self):
        g = self._fork_room()
        await self._dispatch_night2_with(
            g, dead=(BOSS_UID, NATO_UID, SHIAD_UID)
        )
        self.assertIsNone(night2_active_shooter(g))
        keys = night2_required_keys(g)
        for k in ("MAFIA_BOSS", "NATO", "SHIAD"):
            self.assertNotIn(k, keys)

    async def test_synthetic_hacker_shooter_mirrors_to_observer(self):
        g = self._fork_room()
        from bot.models import Role

        g.players[SYN_UID].role = Role.SHIAD
        g.players[SHIAD_UID].role = Role.CITIZEN
        await self._dispatch_night2_with(
            g, dead=(BOSS_UID, NATO_UID)
        )
        key = mirror_ui_claim_key(g.room_code, "n2boss", SYN_UID)
        entry = g.mirror_prompt_messages.get(key) or {}
        self.assertTrue(entry.get("observer"))
        await self._press(OBS_UID, "bmode", SYN_UID, tid=1)
        self.assertEqual(g.nmnd_night2_boss_mode, "shot_plain")

    async def test_neutralized_allowance_shared_not_reset(self):
        g = self._fork_room()
        g.nmnd_night2_boss_neutral_shot_used = True
        g.nmnd_night2_boss_neutral_shot_used_night = 1
        await self._dispatch_night2_with(g, dead=(BOSS_UID,))
        tids = self._menu_tids(SHOOTER_MENU_MARK)
        self.assertNotIn(2, tids)
        self.assertIn(1, tids)

    def test_persistence_snapshot_carries_nato_stamp(self):
        """Allowance stamps survive a snapshot round-trip (dynamic attrs)."""
        import json

        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_night2_nato_used = True
        g.nmnd_night2_nato_used_night = 2
        blob = json.dumps(
            {
                a: getattr(g, a)
                for a in (
                    "nmnd_night2_nato_used",
                    "nmnd_night2_nato_used_night",
                    "nmnd_night2_boss_neutral_shot_used",
                    "nmnd_night2_boss_neutral_shot_used_night",
                )
            }
        )
        self.assertIn("nmnd_night2_nato_used_night", blob)

    # ------------------------------------------- Task 2: lawyer announcement

    def _lawyer_day_setup(self):
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 1
        g.nmnd_night2_lawyer_immune_uid = CIT1_UID
        g.nmnd_night2_lawyer_immune_day = 1
        from bot.nam10.dayflow import _nam10_day_lawyer_protected_uids

        self.assertIn(CIT1_UID, _nam10_day_lawyer_protected_uids(g))
        return g

    async def test_defense_confirm_announces_protected_player(self):
        g = self._lawyer_day_setup()
        from bot.nam10.dayflow import (
            _no_host_day1_defense_confirm,
            announce_nam10_lawyer_defense_skip,
        )
        from bot.nam10.nmnd_narrator import set_day_vote_pick_uids

        g.nam10_day1_defense_active = True
        g.nam10_day1_defense_phase = "pick"
        set_day_vote_pick_uids(g, {CIT1_UID, BOSS_UID})

        # Route through the real dispatcher so the helper popup (callback
        # answer) is recorded by the harness bot.
        await self._press(ASSIST_UID, "d1dc", ASSIST_UID)
        expected = self.manager.format_player_tag(g.players[CIT1_UID])
        announce = [
            t
            for t in self.bot.texts_to(CIT1_UID)
            if "⚖️" in t and LAWYER_ANNOUNCE_MARK in t
        ]
        self.assertEqual(len(announce), 1)
        self.assertIn(expected, announce[0])
        # Observer receives a mirror copy too (synthetic/observer delivery).
        self.assertTrue(
            any(
                "⚖️" in t and LAWYER_ANNOUNCE_MARK in t
                for t in self.bot.texts_to(OBS_UID)
            )
        )
        self.assertEqual(g.nam10_lawyer_defense_announced.get(str(CIT1_UID)), 1)
        # Idempotent: re-running the announcement never duplicates.
        self.assertFalse(
            await announce_nam10_lawyer_defense_skip(self.bot, g, CIT1_UID)
        )
        self.assertEqual(
            len(
                [
                    t
                    for t in self.bot.texts_to(CIT1_UID)
                    if "⚖️" in t and LAWYER_ANNOUNCE_MARK in t
                ]
            ),
            1,
        )
        # No inline buttons on the public announcement. The assistant's
        # own outcome panel legitimately starts with ⚖️ too, so exclude
        # panel texts (they contain the «بررسی بازیکنان» header) as well
        # as observer mirror seat copies.
        for t, kb in self.bot.kb_segments():
            if (
                t.startswith("⚖️")
                and LAWYER_ANNOUNCE_MARK in t
                and "بررسی بازیکنان" not in t
            ):
                self.assertIsNone(kb)
        # Helper popup carries the same information (show_alert).
        self.assertTrue(
            any(
                expected in (a or "") and "⚖️" in (a or "")
                for a in self.bot.acks()
            )
        )

    async def test_protected_player_receives_own_announcement(self):
        g = self._lawyer_day_setup()
        from bot.nam10.dayflow import announce_nam10_lawyer_defense_skip
        from bot.nam10.nmnd_narrator import set_day_vote_defender_uids

        # Task A final condition: only CONFIRMED defence candidates are
        # announced; simulate the assistant's committed selection.
        set_day_vote_defender_uids(g, {CIT1_UID})
        got = await announce_nam10_lawyer_defense_skip(self.bot, g, CIT1_UID)
        self.assertTrue(got)
        expected = self.manager.format_player_tag(g.players[CIT1_UID])
        self.assertIn(expected, " ".join(self.bot.texts_to(CIT1_UID)))

    async def test_unselected_protected_player_is_silent(self):
        # Room 17 regression: valid protection for a player who was NOT
        # among the confirmed defence candidates must stay silent.
        g = self._lawyer_day_setup()
        from bot.nam10.dayflow import announce_nam10_lawyer_defense_skip
        from bot.nam10.nmnd_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(g, set())
        self.assertFalse(
            await announce_nam10_lawyer_defense_skip(self.bot, g, CIT1_UID)
        )
        self.assertFalse(
            [
                t
                for t in self.bot.texts()
                if "⚖️" in t and LAWYER_ANNOUNCE_MARK in t
            ]
        )
        self.assertNotIn(
            str(CIT1_UID),
            getattr(g, "nam10_lawyer_defense_announced", None) or {},
        )

    async def test_lawyer_identity_not_disclosed(self):
        g = self._lawyer_day_setup()
        from bot.nam10.dayflow import announce_nam10_lawyer_defense_skip
        from bot.nam10.nmnd_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(g, {CIT1_UID})
        await announce_nam10_lawyer_defense_skip(self.bot, g, CIT1_UID)
        lawyer_tag = self.manager.format_player_tag(g.players[LAW_UID])
        # Skip observer mirror seat copies (their header legitimately
        # labels the seat's role — the Observer already knows all roles).
        for t in self.bot.texts():
            if "⚖️" in t and LAWYER_ANNOUNCE_MARK in t and "👁" not in t:
                self.assertNotIn(lawyer_tag, t)

    async def test_invalid_protection_no_announcement(self):
        g = self._lawyer_day_setup()
        g.nmnd_night2_lawyer_immune_day = 2  # protection belongs to a later day
        from bot.nam10.dayflow import announce_nam10_lawyer_defense_skip

        self.assertFalse(
            await announce_nam10_lawyer_defense_skip(self.bot, g, CIT1_UID)
        )
        self.assertFalse(
            [
                t
                for t in self.bot.texts()
                if "⚖️" in t and LAWYER_ANNOUNCE_MARK in t
            ]
        )

    async def test_rejection_popup_carries_name(self):
        g = self._lawyer_day_setup()
        from bot.nam10.dayflow import _no_host_day1_defense_pick_elim  # noqa

        g.nam10_day1_defense_active = True
        g.nam10_day1_defense_phase = "pick_elim"
        from bot.nam10.nmnd_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(g, {CIT1_UID, BOSS_UID})
        # Route through the real dispatcher so the helper popup (callback
        # answer) is recorded by the harness bot.
        await self._press(ASSIST_UID, "d1el", ASSIST_UID, tid=CIT1_UID)
        expected = self.manager.format_player_tag(g.players[CIT1_UID])
        self.assertTrue(
            any(
                expected in (a or "") and "⚖️" in (a or "")
                for a in self.bot.acks()
            )
        )
        # Public announcement also fires (once).
        self.assertEqual(len(g.nam10_lawyer_defense_announced), 1)

    # ---------------------------------------- Task 3: guardian armor vs rebel

    async def test_room12_regranted_armor_blocks_assassination(self):
        """Room 12 regression: Night-2 re-grant must refresh the armor day."""
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        g.nmnd_night2_armor_uid = CIT1_UID  # stale Night-1 grant
        g.nmnd_night2_armor_day = 1
        g.nmnd_night2_guardian_uid = CIT1_UID  # Guardian re-picked same target
        self._resolution_game(g)
        out = night2_run_resolution(g)
        self.assertTrue(out["guardian"]["granted"])
        self.assertEqual(out["guardian"].get("protects_day_after_night"), 2)
        self.assertEqual(g.nmnd_night2_armor_day, 2)
        # Day 3 assassination against the protected player is absorbed.
        g.nmnd_night2_rebel_unlocked = True
        g.nmnd_night2_rebel_assassin_used = False
        res = night2_rebel_assassination_effect(g, CIT1_UID)
        self.assertTrue(res["accepted"])
        self.assertEqual(res["reason"], "armor_absorbed")
        self.assertFalse(res["target_eliminated"])
        self.assertTrue(g.players[CIT1_UID].is_alive)
        self.assertIsNone(g.nmnd_night2_armor_uid)

    async def test_unprotected_assassination_eliminates(self):
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        self._resolution_game(g)
        g.nmnd_night2_rebel_unlocked = True
        g.nmnd_night2_rebel_assassin_used = False
        res = night2_rebel_assassination_effect(g, CIT1_UID)
        self.assertEqual(res["reason"], "eliminated")
        self.assertTrue(res["target_eliminated"])
        self.assertFalse(g.players[CIT1_UID].is_alive)

    async def test_expired_stale_armor_cleared_not_swallowing(self):
        """Expired stale armor is cleaned; a Guardian re-pick overwrites."""
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        g.nmnd_night2_armor_uid = MINE_UID  # stale Night-1 grant, other player
        g.nmnd_night2_armor_day = 1
        g.nmnd_night2_guardian_uid = CIT1_UID  # Guardian picked a NEW target
        self._resolution_game(g)
        out = night2_run_resolution(g)
        self.assertTrue(out["guardian"]["granted"])
        self.assertEqual(g.nmnd_night2_armor_uid, CIT1_UID)
        self.assertEqual(g.nmnd_night2_armor_day, 2)

    async def test_guardian_self_intrinsically_immune(self):
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        self._resolution_game(g)
        from bot.models import Role

        g.players[CIT1_UID].role = Role.DETECTIVE
        g.nmnd_night2_rebel_unlocked = True
        g.nmnd_night2_rebel_assassin_used = False
        res = night2_rebel_assassination_effect(g, CIT1_UID)
        self.assertEqual(res["reason"], "guardian_immune")
        self.assertFalse(res["target_eliminated"])
        self.assertTrue(g.players[CIT1_UID].is_alive)

    async def test_armor_consumed_exactly_once(self):
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        g.nmnd_night2_armor_uid = CIT1_UID
        g.nmnd_night2_armor_day = 2
        g.nmnd_night2_rebel_unlocked = True
        g.nmnd_night2_rebel_assassin_used = False
        res1 = night2_rebel_assassination_effect(g, CIT1_UID)
        self.assertEqual(res1["reason"], "armor_absorbed")
        # Ability is once-per-game: a second effect call is rejected.
        res2 = night2_rebel_assassination_effect(g, BOSS_UID)
        self.assertFalse(res2["accepted"])

    async def test_missing_guardian_holder_does_not_grant(self):
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        g.nmnd_night2_guardian_uid = CIT1_UID
        g.players[GUARD_UID].is_alive = False  # no living Guardian
        self._resolution_game(g)
        out = night2_run_resolution(g)
        self.assertFalse(out["guardian"]["granted"])
        self.assertIsNone(g.nmnd_night2_armor_uid)


if __name__ == "__main__":
    unittest.main()
