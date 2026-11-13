"""Namayande-10 Room 50 fixes — regression tests.

Covers three production defects:

1. NATO historical-report wording: the 4-line success/failure NATO block is
   rendered first, no ordinary Mafia-shot line is rendered on a NATO night,
   the Doctor NATO-cancellation line names NATO (not the Rebel), and no
   duplicate NATO summary appears.
2. Shooter succession: after the Mafia Boss is eliminated the alive Rebel
   inherits the Mafia team's nighttime shooting duty through the SAME boss
   shooting pipeline (menu without NATO, neutralized-shot ownership
   transfers, waiting-OK can no longer settle the night, Observer mirror
   works for a synthetic Rebel).
3. The one-time Rebel activation notice is lifetime information: it
   survives the night-resolution purge and the per-night mirror reset.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from bot.observer_delivery import PlayerMirrorCb, mirror_ui_claim_key  # noqa: E402
from tests.test_namayande10_night_publish import _SkipInheritedTests  # noqa: E402
from tests.test_namayande10_night_v2 import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    LAW_UID,
    MINE_UID,
    NATO_UID,
    OBS_UID,
    SYN_UID,
)

from bot.nam10.night2 import (  # noqa: E402
    ALERT_STALE,
    PENDING_COLLECTED,
    _acked_uids,
    night2_active_shooter,
    night2_maybe_finish,
    night2_required_keys,
    night2_run_resolution,
    nam10_night2_entry_dispatch,
)

DOCTOR_NATO_LINE = "💉 پزشک: به دلیل اجرای ناتویی، امشب امکان نجات نداشت."
SHOOTER_MENU_MARK = "جانشین رئیس مافیا"


def _cb_tids(bot, mark: str) -> set[int]:
    """Callback tids inside the first mirror panel containing ``mark``."""
    tids: set[int] = set()
    for text, kb in bot.kb_segments():
        if mark in text and kb is not None:
            for row in kb.inline_keyboard:
                for b in row:
                    try:
                        cb = PlayerMirrorCb.unpack(b.callback_data or "")
                    except TypeError:
                        continue
                    if cb is not None:
                        tids.add(cb.tid)
    return tids


class Nam10Room50FixesTest(_v2.Nam10NightV2Test, metaclass=_SkipInheritedTests):
    """Night v2 shooter succession, NATO report wording, notice survival."""

    # ------------------------------------------------------------- helpers

    def _report_game(self, outcome: dict, *, night: int = 2) -> "object":
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_night2_night_count = night
        g.nmnd_narrator_night_count = night
        g.nmnd_night2_outcome = outcome
        g.nmnd_night2_dispositions = {}
        g.nmnd_night2_shot_result = {}
        return g

    def _base_outcome(self) -> dict:
        return {
            "nato": {"activated": False},
            "shot": {"mode": None},
            "doctor": {
                "cancelled": False,
                "cancelled_reason": None,
                "save_target_uid": None,
                "valid_save": False,
                "nullified_by_hacker": False,
                "protects_shot": False,
            },
            "mine": {},
            "guardian": {},
            "lawyer": {},
            "guide": {},
            "hacker": {
                "confirmed": True,
                "source_uid": DOC_UID,
                "destination_uid": CIT1_UID,
            },
            "rebel": {},
        }

    def _report(self, g) -> str:
        from bot.nam10.night2_publish import night2_night_report_extra_section

        return night2_night_report_extra_section(g, self.manager)

    def _kill_boss_and_enter_night2(self):
        """Night 1 entered normally, boss eliminated, night 2 dispatched."""
        g = self._fork_room()
        return g

    async def _dispatch_night2_with_dead_boss(self, g):
        await self._enter_night()
        g.players[BOSS_UID].is_alive = False
        g.nmnd_narrator_night_count = 2
        ok = await nam10_night2_entry_dispatch(self.bot, g, self.manager)
        self.assertTrue(ok)
        return g

    # ------------------------------------------------- NATO report wording

    def test_nato_success_report_wording(self):
        g = self._report_game(
            self._base_outcome()
            | {
                "nato": {
                    "activated": True,
                    "guessed_role": "RUINTAN",
                    "target_uid": MINE_UID,
                    "success": True,
                    "eliminated": True,
                    "consumed": True,
                },
                "shot": {"skipped": True, "reason": "nato_mode"},
                "doctor": {
                    "cancelled": True,
                    "cancelled_reason": "cancelled_by_nato",
                },
                "mine": {
                    "attempt_uid": LAW_UID,
                    "placed": False,
                    "reason": "mine_layer_not_present",
                },
            }
        )
        report = self._report(g)
        lines = [l for l in report.splitlines() if l.strip()]
        self.assertEqual(lines[0], "🎭 ناتویی مافیا: موفق")
        self.assertEqual(lines[1], "🎯 نقش حدس‌زده‌شده: مین‌گذار")
        exp = self.manager.format_player_tag(g.players[MINE_UID])
        self.assertEqual(lines[2], f"👤 بازیکن انتخاب‌شده: {exp}")
        self.assertEqual(lines[3], "🚪 نتیجه: بازیکن انتخاب‌شده از بازی خارج شد.")
        # No ordinary Mafia-shot line on a NATO night, no Rebel attribution.
        self.assertNotIn("🔴 شات مافیا", report)
        self.assertNotIn("حالت یاغی", report)
        self.assertNotIn("لغو توسط یاغی", report)
        self.assertIn(DOCTOR_NATO_LINE, report)
        # Exactly one NATO summary — the old trailing line is gone.
        self.assertEqual(report.count("ناتویی مافیا"), 1)
        self.assertNotIn("ناتویی فعال شد", report)
        # Other role sections stay intact.
        for mark in ("💻 هکر:", "🧭 راهنما:", "🛡️ محافظ:", "⚖️ وکیل:", "💣 مین‌گذار:"):
            self.assertIn(mark, report)

    def test_nato_failure_report_wording(self):
        g = self._report_game(
            self._base_outcome()
            | {
                "nato": {
                    "activated": True,
                    "guessed_role": "SHIAD",
                    "target_uid": CIT1_UID,
                    "success": False,
                    "eliminated": False,
                    "consumed": True,
                },
                "shot": {"skipped": True, "reason": "nato_mode"},
                "doctor": {
                    "cancelled": True,
                    "cancelled_reason": "cancelled_by_nato",
                },
            }
        )
        report = self._report(g)
        lines = [l for l in report.splitlines() if l.strip()]
        self.assertEqual(lines[0], "🎭 ناتویی مافیا: ناموفق")
        self.assertEqual(lines[1], "🎯 نقش حدس‌زده‌شده: هکر")
        self.assertEqual(lines[3], "📋 نتیجه: هیچ بازیکنی بر اثر ناتویی از بازی خارج نشد.")
        self.assertNotIn("🔴 شات مافیا", report)
        self.assertIn(DOCTOR_NATO_LINE, report)

    def test_nato_outcome_is_night_scoped(self):
        """The durable once-per-game flag must not leak into later nights."""
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        g.nmnd_night2_night_count = 2
        g.nmnd_night2_phase = PENDING_COLLECTED
        g.nmnd_night2_resolved = False
        g.nmnd_night2_resolved_night = None
        g.nmnd_night2_outcome_committed = False
        g.nmnd_night2_nato_used = True  # consumed on Night 1
        g.nmnd_night2_nato_used_night = 1
        g.nmnd_night2_nato_role = None
        g.nmnd_night2_nato_target_uid = None
        out = night2_run_resolution(g)
        self.assertFalse(out["nato"]["activated"])
        report = self._report(g)
        self.assertNotIn("ناتویی مافیا", report)
        self.assertNotIn("🎭", report)

    def test_nato_outcome_claims_only_played_night(self):
        """A night that actually played NATO keeps its activation claim."""
        g = self._fork_room()
        g.nmnd_night2_mode = True
        g.nmnd_narrator_night_count = 2
        g.nmnd_night2_night_count = 2
        g.nmnd_night2_phase = PENDING_COLLECTED
        g.nmnd_night2_resolved = False
        g.nmnd_night2_resolved_night = None
        g.nmnd_night2_outcome_committed = False
        g.nmnd_night2_nato_used = True
        g.nmnd_night2_nato_used_night = 2
        g.nmnd_night2_nato_role = "RUINTAN"
        g.nmnd_night2_nato_target_uid = MINE_UID
        out = night2_run_resolution(g)
        self.assertTrue(out["nato"]["activated"])
        self.assertTrue(out["nato"]["success"])
        self.assertTrue(out["nato"]["eliminated"])
        self.assertFalse(g.players[MINE_UID].is_alive)

    def test_normal_shot_report_preserved(self):
        g = self._report_game(
            self._base_outcome()
            | {
                "shot": {"mode": "shot_plain", "resolved": True,
                         "target_uid": CIT1_UID},
                "mine": {"attempt_uid": None, "placed": False,
                         "reason": "no_attempt"},
            },
            night=2,
        )
        g.nmnd_night2_shot_result = {
            "accepted": True,
            "mode": "shot_plain",
            "night": 2,
            "target_uid": CIT1_UID,
            "eliminated": True,
            "mine_disposition": "triggered",
        }
        g.nmnd_night2_mine_casualty_uid = MINE_UID
        report = self._report(g)
        exp = self.manager.format_player_tag(g.players[CIT1_UID])
        self.assertEqual(
            [l for l in report.splitlines() if l.strip()][0],
            f"🔴 شات مافیا: بدون خنثی‌سازی — هدف: {exp}",
        )
        self.assertIn(
            f"💥 مین فعال شد — خروجی مافیا: "
            f"{self.manager.format_player_tag(g.players[MINE_UID])}",
            report,
        )
        self.assertNotIn("ناتویی مافیا", report)
        self.assertNotIn("🎭", report)

    def test_no_shooter_night_reports_unregistered(self):
        g = self._report_game(self._base_outcome())
        self.assertIn("🔴 شات مافیا: ثبت نشد.", self._report(g))

    # ------------------------------------------------ shooter succession

    async def test_rebel_inherits_shooting_after_boss_death(self):
        g = await self._dispatch_night2_with_dead_boss(self._fork_room())
        shooter = night2_active_shooter(g)
        self.assertIsNotNone(shooter)
        self.assertEqual(shooter.user_id, NATO_UID)
        keys = night2_required_keys(g)
        self.assertNotIn("MAFIA_BOSS", keys)
        self.assertIn("NATO", keys)
        # The inherited shooter menu (mirrored to the Observer) offers
        # both shot modes plus NATO while the team allowance is unused.
        self.assertTrue(
            any(SHOOTER_MENU_MARK in t for t in self.bot.texts_to(OBS_UID))
        )
        tids = _cb_tids(self.bot, SHOOTER_MENU_MARK)
        self.assertEqual(tids, {1, 2, 3})

    async def test_rebel_waiting_ok_cannot_settle_night(self):
        g = await self._dispatch_night2_with_dead_boss(self._fork_room())
        await self._press(NATO_UID, "waitok", NATO_UID)
        self.assertNotIn(NATO_UID, _acked_uids(g, "NATO"))
        self.assertIn("NATO", night2_required_keys(g))
        self.assertFalse(night2_maybe_finish(g))
        self.assertIn(ALERT_STALE, self.bot.acks())

    async def test_rebel_completes_inherited_shot_flow(self):
        g = await self._dispatch_night2_with_dead_boss(self._fork_room())
        await self._press(NATO_UID, "bmode", NATO_UID, tid=1)
        self.assertEqual(g.nmnd_night2_boss_mode, "shot_plain")
        self.assertEqual(g.nmnd_night2_boss_phase, "shot_target")
        await self._press(NATO_UID, "sht", NATO_UID, tid=CIT1_UID)
        self.assertEqual(g.nmnd_night2_shot_pending_uid, CIT1_UID)
        await self._press(NATO_UID, "shtok", NATO_UID)
        self.assertEqual(g.nmnd_night2_shot_target_uid, CIT1_UID)
        self.assertEqual(g.nmnd_night2_boss_phase, "done")
        keys = night2_required_keys(g)
        self.assertNotIn("NATO", keys)
        self.assertNotIn("MAFIA_BOSS", keys)

    async def test_synthetic_rebel_shooter_mirrors_to_observer(self):
        g = self._fork_room()
        from bot.models import Role

        g.players[SYN_UID].role = Role.NATO
        g.players[NATO_UID].role = Role.CITIZEN
        g = await self._dispatch_night2_with_dead_boss(g)
        key = mirror_ui_claim_key(g.room_code, "n2boss", SYN_UID)
        entry = g.mirror_prompt_messages.get(key) or {}
        self.assertTrue(entry.get("observer"))
        # The Observer operates the synthetic Rebel's inherited shot menu.
        await self._press(OBS_UID, "bmode", SYN_UID, tid=1)
        self.assertEqual(g.nmnd_night2_boss_mode, "shot_plain")

    async def test_neutralized_shot_stays_consumed_for_rebel(self):
        g = self._fork_room()
        g.nmnd_night2_boss_neutral_shot_used = True
        g.nmnd_night2_boss_neutral_shot_used_night = 1
        g = await self._dispatch_night2_with_dead_boss(g)
        tids = _cb_tids(self.bot, SHOOTER_MENU_MARK)
        self.assertIn(1, tids)
        self.assertNotIn(2, tids)
        await self._press(NATO_UID, "bmode", NATO_UID, tid=2)
        self.assertIn(ALERT_STALE, self.bot.acks())
        self.assertIsNone(g.nmnd_night2_boss_mode)

    async def test_boss_alive_keeps_original_panels(self):
        self._fork_room()
        await self._enter_night()
        g = self.game
        self.assertEqual(night2_active_shooter(g).user_id, BOSS_UID)
        # Boss menu offers NATO while unused.
        boss_menu = _cb_tids(self.bot, "انتخاب قابلیت رئیس مافیا")
        self.assertIn(3, boss_menu)
        # Rebel keeps the waiting-only panel and may ack it.
        self.assertTrue(
            any("انتظار برای پایان شب" in t for t in self.bot.texts_to(NATO_UID))
        )
        from bot.nam10.night2 import _wait_ok_allowed

        self.assertTrue(_wait_ok_allowed(g, "NATO", NATO_UID))
        keys = night2_required_keys(g)
        self.assertIn("MAFIA_BOSS", keys)
        self.assertIn("NATO", keys)

    async def test_shooter_menu_rejects_non_shooter(self):
        g = await self._dispatch_night2_with_dead_boss(self._fork_room())
        # A non-shooter must not drive the shot menu.
        await self._press(CIT1_UID, "bmode", CIT1_UID, tid=1)
        from bot.nam10.night2 import ALERT_FORBIDDEN

        self.assertIn(ALERT_FORBIDDEN, self.bot.acks())
        self.assertIsNone(g.nmnd_night2_boss_mode)
        # And a non-shooter may not pick NATO either.
        await self._press(CIT1_UID, "bmode", CIT1_UID, tid=3)
        self.assertIn(ALERT_FORBIDDEN, self.bot.acks())
        self.assertIsNone(g.nmnd_night2_boss_mode)

    # ------------------------------------------------- notice survives

    async def test_notice_survives_night_purge(self):
        from bot.nam10.nmnd_night_panel_purge import (
            purge_stale_night_and_day_panel_messages,
        )
        from bot.nam10.rebel_day import nam10_rebel_notice_key

        g = self._fork_room()
        nk = nam10_rebel_notice_key(g, NATO_UID)
        pk = mirror_ui_claim_key(g.room_code, "n2doc", DOC_UID)
        g.mirror_prompt_messages[nk] = {
            "player": (NATO_UID, 555),
            "observer": (OBS_UID, 556),
            "text": "notice",
        }
        g.mirror_prompt_messages[pk] = {
            "player": (DOC_UID, 777),
            "observer": (OBS_UID, 778),
            "text": "panel",
        }
        g.mirror_action_claims[nk] = OBS_UID
        g.mirror_action_claims[pk] = DOC_UID
        await purge_stale_night_and_day_panel_messages(self.bot, g)
        dels = set()
        for c in self.bot.calls:
            if getattr(c, "_cls", None) == "delete_message":
                kw = getattr(c, "_rec_kwargs", {}) or {}
                dels.add((kw.get("chat_id"), kw.get("message_id")))
        # Per-night panels are deleted; the lifetime notice is not.
        self.assertIn((DOC_UID, 777), dels)
        self.assertIn((OBS_UID, 778), dels)
        self.assertNotIn((NATO_UID, 555), dels)
        self.assertNotIn((OBS_UID, 556), dels)
        self.assertIn(nk, g.mirror_prompt_messages)
        self.assertNotIn(pk, g.mirror_prompt_messages)
        self.assertIn(nk, g.mirror_action_claims)
        self.assertNotIn(pk, g.mirror_action_claims)

    def test_notice_survives_night_entry_mirror_reset(self):
        from bot.nam10.no_host_mirror_reset import (
            reset_no_host_night_mirror_prompts,
        )
        from bot.nam10.rebel_day import nam10_rebel_notice_key

        g = self._fork_room()
        nk = nam10_rebel_notice_key(g, NATO_UID)
        pk = mirror_ui_claim_key(g.room_code, "n2doc", DOC_UID)
        g.mirror_prompt_messages[nk] = {
            "player": (NATO_UID, 555),
            "observer": (OBS_UID, 556),
            "text": "notice",
        }
        g.mirror_prompt_messages[pk] = {
            "player": (DOC_UID, 777),
            "observer": (OBS_UID, 778),
            "text": "panel",
        }
        g.mirror_action_claims[nk] = OBS_UID
        reset_no_host_night_mirror_prompts(g)
        self.assertIn(nk, g.mirror_prompt_messages)
        self.assertNotIn(pk, g.mirror_prompt_messages)
        self.assertIn(nk, g.mirror_action_claims)


if __name__ == "__main__":
    unittest.main()
