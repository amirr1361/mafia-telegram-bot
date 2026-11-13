"""Namayande-10 — final mine matrix, Guardian exemption, assassination day flow.

Focused regressions for the corrected FINAL rules:
- neutralized shot + active mine: mine neutralized/consumed, the Doctor
  save still resolves survival, no Mafia-casualty selection;
- plain shot + active mine: mine detonates/consumed, the mined target is
  eliminated regardless of a Doctor save, the existing casualty flow runs;
- Guardian acknowledgement-only panel after the Rebel actually used the
  assassination (normal panel otherwise);
- committed assassination bypasses that day's defence workflow and offers
  the assistant one explicit next-night transition.
"""
import unittest

from bot.models import Phase
from bot.nam10.night2 import night2_guardian_exempt_after_assassin
from tests.test_namayande10_night_v2 import (
    ASSIST_UID,
    CIT1_UID,
    DOC_UID,
    GUARD_UID,
    NATO_UID,
    Nam10NightV2ResolveTest,
    Nam10NightV2Test,
    SYN_UID,
)


class Nam10FinalMineMatrixTest(Nam10NightV2ResolveTest):
    async def test_neutralized_mined_shot_with_doctor_save_survives(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,      # Doctor saves the mined target
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["accepted"])
        self.assertFalse(res["eliminated"])
        self.assertTrue(res["protected_by_doctor"])
        self.assertEqual(res["mine_disposition"], "neutralized")
        self.assertTrue(self.game.players[CIT1_UID].is_alive)
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)
        events = self.game.nmnd_night2_mine_events
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["neutralized"])
        self.assertFalse(events[0]["triggered"])

    async def test_neutralized_mined_shot_without_save_dies_no_casualty(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2,
            shot_target=CIT1_UID,
            doc_pick=DOC_UID,       # Doctor elsewhere
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertFalse(res["protected_by_doctor"])
        self.assertEqual(res["mine_disposition"], "neutralized")
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertFalse(self.game.nmnd_night2_mine_casualty_pending)

    async def test_plain_mined_shot_doctor_save_dies_casualty_required(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        res = dict(self.game.nmnd_night2_shot_result)
        self.assertTrue(res["eliminated"])
        self.assertFalse(res["protected_by_doctor"])
        self.assertTrue(res["doctor_save_ineffective"])
        self.assertEqual(res["mine_disposition"], "triggered")
        self.assertFalse(self.game.players[CIT1_UID].is_alive)
        self.assertIsNone(self.game.nmnd_night2_active_mine_uid)
        self.assertTrue(self.game.nmnd_night2_mine_casualty_pending)

    async def test_report_neutralized_shot_lines(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        from bot.nam10.night2_publish import night2_night_report_extra_section

        report = night2_night_report_extra_section(self.game, self.manager)
        self.assertIn("🔴 شات مافیا: با خنثی‌سازی — هدف:", report)
        self.assertIn("💣 مین روی هدف شات خنثی شد.", report)
        self.assertIn(
            "💉 پزشک بازیکن هدف را نجات داد؛ بازیکن از بازی خارج نشد.",
            report,
        )
        self.assertNotIn("مین فعال شد و منفجر شد", report)
        self.assertNotIn("خروجی مافیا", report)

    async def test_report_plain_mined_shot_lines(self):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=CIT1_UID,
            hack_src=DOC_UID,
            hack_dst=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
        )
        from bot.nam10.night2_publish import night2_night_report_extra_section

        report = night2_night_report_extra_section(self.game, self.manager)
        self.assertIn("🔴 شات مافیا: بدون خنثی‌سازی — هدف:", report)
        self.assertIn("💣 مین روی هدف شات منفجر شد.", report)
        self.assertIn(
            "💉 نجات پزشک نتوانست مانع خروج بازیکن بر اثر انفجار مین شود.",
            report,
        )
        self.assertIn("خروجی مافیا هنوز مشخص نشده است", report)


class Nam10GuardianExemptTest(Nam10NightV2Test):
    async def test_exempt_acknowledgement_panel_after_assassin_used(self):
        self._fork_room()
        self.game.nmnd_night2_rebel_assassin_used = True
        await self._enter_night()
        texts = "\n".join(self.bot.texts_to(GUARD_UID))
        self.assertIn("🛡️ محافظ", texts)
        self.assertIn("یاغی از قابلیت ترور خود استفاده کرده", texts)
        self.assertIn("دیگر نیازی به انتخاب بازیکن برای محافظت نیست.", texts)
        self.assertNotIn("انتخاب محافظ", texts)
        # The acknowledgement is the Guardian's night obligation.
        await self._press(GUARD_UID, "waitok", GUARD_UID)
        self.assertIn(
            GUARD_UID,
            (self.game.nmnd_night2_waiting_acked or {}).get("DETECTIVE", []),
        )
        self.assertIn(
            "✅ تأیید شما ثبت شد.", "\n".join(self.bot.texts_to(GUARD_UID))
        )
        # Stale target-selection callbacks are rejected in this state.
        await self._press(GUARD_UID, "gdnp", GUARD_UID, tid=CIT1_UID)
        self.assertIsNone(self.game.nmnd_night2_guardian_uid)

    async def test_rebel_dead_without_assassination_keeps_normal_panel(self):
        self._fork_room()
        self.game.players[NATO_UID].is_alive = False
        await self._enter_night()
        self.assertFalse(night2_guardian_exempt_after_assassin(self.game))
        texts = "\n".join(self.bot.texts_to(GUARD_UID))
        self.assertIn("انتخاب محافظ", texts)
        self.assertNotIn("دیگر نیازی به انتخاب بازیکن", texts)

    async def test_alive_unused_rebel_keeps_normal_panel(self):
        self._fork_room()
        await self._enter_night()
        self.assertFalse(night2_guardian_exempt_after_assassin(self.game))
        self.assertIn(
            "انتخاب محافظ", "\n".join(self.bot.texts_to(GUARD_UID))
        )

    async def test_exempt_ack_satisfies_readiness_without_armor(self):
        self._fork_room()
        self.game.nmnd_night2_rebel_assassin_used = True
        await self._enter_night()
        from bot.nam10.night2 import night2_required_keys

        self.assertIn("DETECTIVE", night2_required_keys(self.game))
        await self._press(GUARD_UID, "waitok", GUARD_UID)
        self.assertNotIn("DETECTIVE", night2_required_keys(self.game))
        self.assertIsNone(self.game.nmnd_night2_guardian_uid)
        self.assertIsNone(self.game.nmnd_night2_armor_uid)


class Nam10AssassinationDayFlowTest(Nam10NightV2Test):
    def _day_state(self):
        self._fork_room()
        g = self.game
        g.nmnd_night2_rebel_assassin_used = True
        g.nam10_day1_defense_active = True
        g.nam10_day1_defense_phase = "pick"
        return g

    async def test_committed_assassination_bypasses_defense_once(self):
        g = self._day_state()
        from bot.nam10.rebel_day import prepare_post_assassination_day

        ok = await prepare_post_assassination_day(
            self.bot,
            g,
            self.manager,
            {"accepted": True, "rebel_uid": NATO_UID, "target_uid": CIT1_UID},
        )
        self.assertTrue(ok)
        self.assertFalse(g.nam10_day1_defense_active)
        self.assertEqual(g.nam10_day1_defense_phase, "bypassed")
        panel = "\n".join(self.bot.texts_to(ASSIST_UID))
        self.assertIn("🌙 پایان روز — آماده‌سازی شب بعد", panel)
        self.assertIn("امروز مرحله دفاعیه برگزار نمی‌شود", panel)
        # Idempotent preparation: a second call sends nothing new.
        n_panels = len(
            [t for t in self.bot.texts_to(ASSIST_UID) if "آماده‌سازی شب بعد" in t]
        )
        self.assertFalse(
            await prepare_post_assassination_day(
                self.bot, g, self.manager, {"accepted": True}
            )
        )
        self.assertEqual(
            len(
                [
                    t
                    for t in self.bot.texts_to(ASSIST_UID)
                    if "آماده‌سازی شب بعد" in t
                ]
            ),
            n_panels,
        )
        nc0 = int(g.nmnd_narrator_night_count or 0)
        await self._press(ASSIST_UID, "rebnext", ASSIST_UID)
        self.assertEqual(int(g.nmnd_narrator_night_count or 0), nc0 + 1)
        # Duplicate press never starts a second night.
        await self._press(ASSIST_UID, "rebnext", ASSIST_UID)
        self.assertEqual(int(g.nmnd_narrator_night_count or 0), nc0 + 1)

    async def test_stale_defense_confirm_rejected_after_bypass(self):
        g = self._day_state()
        from bot.nam10.rebel_day import prepare_post_assassination_day

        await prepare_post_assassination_day(self.bot, g, self.manager, {})
        await self._press(ASSIST_UID, "d1dc", ASSIST_UID)
        self.assertEqual(g.nam10_day1_defense_phase, "bypassed")
        self.assertFalse(g.nam10_day1_defense_active)

    async def test_ended_game_gets_no_panel_and_no_transition(self):
        self._fork_room()
        g = self.game
        g.nmnd_night2_rebel_assassin_used = True
        g.phase = Phase.ENDED
        g.nam10_day1_defense_active = True
        g.nam10_day1_defense_phase = "pick"
        from bot.nam10.rebel_day import prepare_post_assassination_day

        self.assertFalse(
            await prepare_post_assassination_day(
                self.bot, g, self.manager, {"accepted": True}
            )
        )
        self.assertFalse(
            [t for t in self.bot.texts() if "آماده‌سازی شب بعد" in t]
        )
        self.assertEqual(g.nam10_day1_defense_phase, "pick")

def load_tests(loader, tests, pattern):
    """Collect only the tests defined in this module.

    The harness classes are shared TestCase bases carrying their own
    suites; collecting them through these subclasses would re-run every
    inherited harness test.
    """
    suite = unittest.TestSuite()
    for cls in (
        Nam10FinalMineMatrixTest,
        Nam10GuardianExemptTest,
        Nam10AssassinationDayFlowTest,
    ):
        for name in sorted(n for n in cls.__dict__ if n.startswith("test_")):
            suite.addTest(cls(name))
    return suite
