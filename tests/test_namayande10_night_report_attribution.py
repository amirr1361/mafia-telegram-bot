"""Namayande-10 Night v2 — per-night attribution of the historical
night report (`night2_night_report_extra_section`) regression tests.

Room 31 defect: the Night-2 (NATO) blocks of the eliminated-player
report and of the real `night.resolved` record carried Night 1's
confirmed Mafia shot («🔴 شات مافیا: رضا-شهروند ساده») and its
mine-neutralization line («💣 مین خنثی شد.»). Root cause: the shot
branch of `night2_night_report_extra_section` read the durable
`nmnd_night2_shot_result` surface without checking that the recorded
shot belongs to the night being reported. The fix gates the shot block
on `shot["night"] == game.nmnd_night2_night_count`; every other line of
the section already comes from the per-night committed outcome dict or
per-night reset state.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

from bot.observer_delivery import PlayerMirrorCb  # noqa: E402
from tests.test_namayande10_night_publish import _SkipInheritedTests  # noqa: E402
import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_night_v2 import (  # noqa: E402
    ASSIST_UID,
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
)

from bot.nam10.night2_publish import night2_night_report_extra_section  # noqa: E402
from bot.nam10.no_host_elim_report import (  # noqa: E402
    _nam10_unlogged_night_resolved_records,
)

NIGHT_SHOT_MARK = "🔴 شات مافیا"
MINE_NEUTRAL_MARK = "💣 مین خنثی شد."
NATO_MARK = "ناتویی مافیا"
NATO_SUCCESS_MARK = "🎭 ناتویی مافیا: موفق"
NATO_FAIL_MARK = "🎭 ناتویی مافیا: ناموفق"
DOCTOR_NATO_CANCEL_MARK = "به دلیل اجرای ناتویی، امشب امکان نجات نداشت."
MISSING_MARK = "🔴 شات مافیا: ثبت نشد."
DOCTOR_MARK = "💉 پزشک"
HACKER_MARK = "💻 هکر"
GUARD_MARK = "🛡️ محافظ"
LAWYER_MARK = "⚖️ وکیل"
MINE_PLACED_MARK = "💣 مین‌گذار"


class Nam10NightReportAttributionTest(
    _v2.Nam10NightV2Test, metaclass=_SkipInheritedTests
):
    """Historical night lines must come only from their own night."""

    # ------------------------------------------------------------ helpers

    async def _fork_night(self):
        self._fork_room()
        await self._enter_night()
        return self.game

    def _set_night1_shot_history(self, game):
        """Room-31 Night-1 authoritative shot record, mirrored into the
        durable state exactly as the engine writes it."""
        game.nmnd_night2_shot_result = {
            "accepted": True,
            "mode": "shot_neutralized",
            "target_uid": CIT1_UID,
            "night": 1,
            "protected_by_doctor": False,
            "had_mine": True,
            "eliminated": True,
            "mine_disposition": "permanently_neutralized",
        }
        return CIT1_UID

    def _night1_roster_snapshot(self, game):
        return {uid: p.is_alive for uid, p in game.players.items()}

    def _extra_lines(self):
        joined = night2_night_report_extra_section(self.game, self.manager)
        return joined, [ln for ln in joined.splitlines() if ln.strip()]

    # ------------------------------------------------------------- tests

    async def test_nato_night_does_not_inherit_previous_shot(self):
        """Room 31: Night-2 NATO report has no Night-1 shot/mine lines."""
        game = await self._fork_night()
        shot_target = self._set_night1_shot_history(game)
        # Warp to the Night-2 committed NATO outcome exactly like the
        # Room 31 trail (boss chose NATO; no shot this night).
        await night2_mod_entry(game, self.bot, self.manager)
        game.nmnd_night2_outcome = {
            "nato": {
                "activated": True,
                "guessed_role": "DOCTOR",
                "target_uid": DOC_UID,
                "success": True,
                "eliminated": True,
                "consumed": True,
            },
            "doctor": {
                "cancelled": True,
                "cancelled_reason": "cancelled_by_nato",
            },
            "shot": {"skipped": True, "reason": "nato_mode"},
        }
        joined, lines = self._extra_lines()
        self.assertIn(NATO_SUCCESS_MARK, joined)
        # A NATO night has no ordinary Mafia-shot line at all — neither a
        # current one nor the stale Night-1 shot/mine lines.
        self.assertNotIn(NIGHT_SHOT_MARK, joined)
        self.assertNotIn(MINE_NEUTRAL_MARK, joined)
        self.assertIn("🎯 نقش حدس‌زده‌شده:", joined)
        self.assertIn("👤 بازیکن انتخاب‌شده:", joined)
        self.assertIn("🚪 نتیجه: بازیکن انتخاب‌شده از بازی خارج شد.", joined)
        # Exactly one NATO summary — no duplicate line.
        self.assertEqual(joined.count(NATO_MARK), 1)
        # Doctor cancellation line renders from THIS night's outcome.
        self.assertIn(DOCTOR_NATO_CANCEL_MARK, joined)

    async def test_current_night_shot_fully_rendered(self):
        """A confirmed shot of the reported night renders with mine line."""
        game = await self._fork_night()
        self._set_night1_shot_history(game)
        joined, _lines = self._extra_lines()
        self.assertIn(NIGHT_SHOT_MARK, joined)
        self.assertIn(MINE_NEUTRAL_MARK, joined)

    async def test_next_night_without_shot_reports_missing_not_stale(self):
        """Night-2 with no shot: no fallback to Night 1's record."""
        game = await self._fork_night()
        self._set_night1_shot_history(game)
        await night2_mod_entry(game, self.bot, self.manager)
        joined, _lines = self._extra_lines()
        self.assertIn(MISSING_MARK, joined)
        self.assertNotIn(MINE_NEUTRAL_MARK, joined)
        # Mine casualty is also per-night: never carries over.
        self.assertNotIn("💥 مین فعال شد", joined)

    async def test_shot_without_night_stamp_is_not_attributed(self):
        """Legacy entries lacking a night stamp are never re-attributed."""
        game = await self._fork_night()
        self._set_night1_shot_history(game)
        stale = dict(game.nmnd_night2_shot_result)
        stale.pop("night")
        game.nmnd_night2_shot_result = stale
        joined, _lines = self._extra_lines()
        self.assertIn(MISSING_MARK, joined)
        self.assertNotIn(MINE_NEUTRAL_MARK, joined)

    async def test_identical_shot_across_nights_is_preserved(self):
        """Two legitimate shots of the same target in different nights
        must both render inside their own night, never de-duplicated."""
        game = await self._fork_night()
        self._set_night1_shot_history(game)
        joined1, _ = self._extra_lines()
        self.assertIn(MINE_NEUTRAL_MARK, joined1)
        # Night 2 confirms an identical plain shot against the same uid.
        await night2_mod_entry(game, self.bot, self.manager)
        game.nmnd_night2_shot_result = {
            "accepted": True,
            "mode": "shot_plain",
            "target_uid": CIT1_UID,
            "night": 2,
            "protected_by_doctor": False,
            "had_mine": False,
            "eliminated": True,
        }
        joined2, _ = self._extra_lines()
        self.assertIn(NIGHT_SHOT_MARK, joined2)
        self.assertNotIn(MINE_NEUTRAL_MARK, joined2)

    async def test_hacker_selections_are_night_specific(self):
        """Night-1 Hacker pair is not re-reported on Night 2."""
        game = await self._fork_night()
        game.nmnd_night2_hacker_uids = [GUARD_UID, CIT1_UID]
        joined1, _ = self._extra_lines()
        self.assertIn(HACKER_MARK, joined1)
        self.assertIn("مبدأ:", joined1)
        await night2_mod_entry(game, self.bot, self.manager)
        joined2, _ = self._extra_lines()
        self.assertIn(f"{HACKER_MARK}: ثبت نشد.", joined2)
        self.assertNotIn("مبدأ:", joined2)
        # A different Night-2 pair renders for its own night.
        game.nmnd_night2_hacker_uids = [LAW_UID, DOC_UID]
        joined3, _ = self._extra_lines()
        self.assertIn("مبدأ:", joined3)

    async def test_doctor_cancelled_by_nato_not_stale_save(self):
        """NATO cancellation replaces the previous night's save line."""
        game = await self._fork_night()
        game.nmnd_night2_shot_result = {}
        game.nmnd_night2_outcome = {
            "shot": {"skipped": True, "reason": "nato_mode"},
            "doctor": {
                "cancelled": True,
                "cancelled_reason": "cancelled_by_nato",
            },
        }
        joined, _lines = self._extra_lines()
        self.assertIn(DOCTOR_NATO_CANCEL_MARK, joined)
        self.assertNotIn("لغو توسط یاغی", joined)
        self.assertNotIn("هدف نجات:", joined)

    async def test_guardian_lawyer_mine_outcome_only(self):
        """Guardian/lawyer/mine lines never come from durable history."""
        game = await self._fork_night()
        # Durable leftovers from "Night 1" actions:
        game.nmnd_night2_armor_uid = CIT1_UID   # armor granted night 1
        game.nmnd_night2_armor_day = 1
        game.nmnd_night2_lawyer_immune_uid = CIT1_UID
        game.nmnd_night2_lawyer_immune_day = 1
        game.nmnd_night2_active_mine_uid = CIT1_UID
        game.nmnd_night2_active_mine_night = 1
        game.nmnd_night2_shot_result = {}
        joined, _lines = self._extra_lines()
        # Empty current-night outcomes → "ثبت نشد" for all three.
        self.assertIn(f"{GUARD_MARK}: ثبت نشد.", joined)
        self.assertIn(f"{LAWYER_MARK}: ثبت نشد.", joined)
        self.assertIn(f"{MINE_PLACED_MARK}: ثبت نشد.", joined)
        self.assertNotIn("زره اعمال شد", joined)
        self.assertNotIn("مصونیت اعمال شد", joined)
        self.assertNotIn("مین روی", joined)

    async def test_pseudo_elim_record_window_is_night_correct(self):
        """Unlogged-window elimination reports stay night-correct."""
        game = await self._fork_night()
        self._set_night1_shot_history(game)
        # Night-2 NATO state resolved-and-committed, log not yet written.
        await night2_mod_entry(game, self.bot, self.manager)
        game.nmnd_night2_resolved = True
        game.nmnd_night2_resolved_night = 2
        game.nmnd_night2_outcome = {
            "nato": {
                "activated": True,
                "guessed_role": "DOCTOR",
                "target_uid": DOC_UID,
                "success": True,
                "eliminated": True,
                "consumed": True,
            },
            "shot": {"skipped": True, "reason": "nato_mode"},
        }
        recs = _nam10_unlogged_night_resolved_records(game, self.manager)
        self.assertEqual(len(recs), 1)
        html = recs[0].get("night_report_html") or ""
        self.assertIn(NATO_MARK, html)
        self.assertNotIn(MINE_NEUTRAL_MARK, html)
        self.assertNotIn(f"{NIGHT_SHOT_MARK}: ", html)
        self.assertIn("پایان شب دوم", html)
        self.assertNotIn("پایان شب سوم", html)
        # Idempotent: a second read yields the same record content.
        recs2 = _nam10_unlogged_night_resolved_records(game, self.manager)
        self.assertEqual(recs2, recs)

    async def test_real_record_composition_not_gated_regressed(self):
        """Round-trip: real night records keep per-night truth."""
        game = await self._fork_night()
        self._set_night1_shot_history(game)
        joined1, _ = self._extra_lines()
        self.assertIn(f"{NIGHT_SHOT_MARK}: ", joined1)
        self.assertIn(MINE_NEUTRAL_MARK, joined1)
        await night2_mod_entry(game, self.bot, self.manager)
        joined2, _ = self._extra_lines()
        self.assertIn(MISSING_MARK, joined2)
        # Exactly one shot line, and it is the "missing" variant — no
        # named target from Night 1 and no mine-neutralization line.
        self.assertEqual(joined2.count(NIGHT_SHOT_MARK), 1)
        self.assertNotIn(MINE_NEUTRAL_MARK, joined2)

    async def test_full_night_report_keeps_legacy_sections_intact(self):
        """Non-night2 scenario composition untouched (roster presence)."""
        game = self._fork_room()
        game.nmnd_night2_mode = False
        game.nmnd_night2_shot_result = None
        from bot.nam10.nmnd_narrator import _compose_full_night_report

        html = _compose_full_night_report(
            game,
            self.manager,
            self._night1_roster_snapshot(game),
        )
        self.assertIn("گزارش کامل شب گذشته", html)
        self.assertNotIn(NATO_MARK, html)


def night2_mod_entry(game, bot, manager):
    """Advance the harness room to the next night's entry dispatch."""
    from bot.nam10.night2 import nam10_night2_entry_dispatch

    game.nmnd_narrator_night_count = int(game.nmnd_narrator_night_count or 1) + 1
    game.nmnd_narrator_host_day = game.nmnd_narrator_night_count
    return nam10_night2_entry_dispatch(bot, game, manager)


if __name__ == "__main__":
    unittest.main()
