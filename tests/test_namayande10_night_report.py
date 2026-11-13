"""Namayande-10 Night v2 — complete night report + eliminated-player
frozen report regression (Room 46 production incident).

Room 46 defects reproduced here:
1. The Observer's Night-1 «گزارش کامل شب گذشته» block listed only Mafia
   shot + Hacker; every other role (Doctor save (nullified), Guide pick
   + granted extra investigation with its result, Guardian armor,
   Lawyer immunity, Mine placement/skip, waiting acknowledgements) was
   silently omitted.
2. Seat 7 (eliminated during Night 1) pressed «📋 گزارش بازی» during
   the resolution/publication window and received ONLY the roster: the
   cutoff report is built from audit records, and the `night.resolved`
   audit row is written at the end of the publication flow — so the
   timeline was empty at capture time.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_publish as _pub  # noqa: E402
from tests.test_namayande10_night_publish import (  # noqa: E402
    BOSS_UID,
    CIT1_UID,
    DOC_UID,
    SYN_UID,
    _SkipInheritedTests,
)


class _SkipAllInherited(_SkipInheritedTests):
    """Shadow inherited test methods across the whole MRO."""

    def __new__(mcls, name, bases, ns):
        cls = super().__new__(mcls, name, bases, ns)
        own = set(ns)
        for k in range(len(cls.__mro__)):
            base = cls.__mro__[k]
            if base is cls or base is object:
                continue
            for attr in [
                a
                for a in vars(base)
                if a.startswith("test_") and a not in own
            ]:
                setattr(cls, attr, None)
        return cls


def _block_lines(game):
    """Lines of the «گزارش کامل شب گذشته» block in the internal report."""
    html = game.nmnd_night_report_html or ""
    lines = []
    active = False
    for raw in html.splitlines():
        line = raw.strip()
        if "گزارش کامل شب گذشته" in line:
            active = True
            continue
        if active and line:
            lines.append(line)
    return lines


class Nam10NightReportCompletenessTest(
    _pub.Nam10NightPublishFlowTest, metaclass=_SkipAllInherited
):
    """Observer night report completeness + frozen elim report."""

    async def _run_night(
        self, *, mine_pick, law_pick, do_extra, finish=True
    ):
        self._fork_room()
        await self._enter_night()
        await self._walk_v2(
            boss_tid=2,
            shot_target=SYN_UID,
            doc_pick=SYN_UID,
            guide_target=DOC_UID,
            guard_target=BOSS_UID,
            mine_pick=mine_pick,
            law_pick=law_pick,
            do_extra=do_extra,
            extra_target=BOSS_UID,
        )
        if finish:
            await self._finish_day()
        return self.game

    async def test_full_night_report_lists_every_role(self):
        g = await self._run_night(
            mine_pick=CIT1_UID, law_pick=0, do_extra=True
        )
        lines = _block_lines(g)
        joined = "\n".join(lines)
        self.assertTrue(any("🔴 شات مافیا" in l for l in lines), joined)
        self.assertTrue(
            any("💻 هکر: مبدأ:" in l and "مقصد:" in l for l in lines), joined
        )
        # Doctor save (SYN) was intercepted by the confirmed hacker pair
        # (DOC -> SYN) and must show exactly that.
        self.assertTrue(
            any(
                "💉 پزشک: هدف نجات:" in l and "توسط هکر خنثی شد" in l
                for l in lines
            ),
            joined,
        )
        self.assertTrue(
            any(
                "🧭 راهنما: بازیکن انتخاب‌شده:" in l
                and "استعلام کارآگاهی اعطا شد" in l
                for l in lines
            ),
            joined,
        )
        self.assertTrue(
            any("🔎 استعلام:" in l and "—" in l for l in lines), joined
        )
        self.assertTrue(
            any("🛡️ محافظ:" in l and "زره اعمال شد" in l for l in lines),
            joined,
        )
        self.assertTrue(
            any("⚖️ وکیل: انتخابی نداشت." in l for l in lines), joined
        )
        self.assertTrue(
            any(
                "💣 مین‌گذار: مین روی" in l and "گذاشته شد" in l
                for l in lines
            ),
            joined,
        )
        self.assertNotIn("🌙 تأیید بستن چشم‌ها:", joined)

    async def test_public_broadcast_stays_names_only(self):
        g = await self._run_night(
            mine_pick=CIT1_UID, law_pick=0, do_extra=True
        )
        from bot.nam10.no_host_night_resolve import (
            build_no_host_night_results_broadcast_html,
        )

        public_html = build_no_host_night_results_broadcast_html(
            g, self.manager
        )
        self.assertNotIn("گزارش کامل شب گذشته", public_html)
        for forbidden in (
            "💉 پزشک",
            "🛡️ محافظ",
            "⚖️ وکیل",
            "💣 مین‌گذار",
            "🧭 راهنما",
            "🔎 استعلام اضافی",
            "💻 هکر",
        ):
            self.assertNotIn(forbidden, public_html)
        self.assertIn("نتیجه نهایی شب و روز گذشته", public_html)
        self.assertIn("در شبی که گذشت", public_html)

    async def test_elim_cutoff_report_includes_committed_night(self):
        """Seat-7 window: resolution committed, `night.resolved` audit
        row not yet written — the pseudo record must restore the full
        night timeline in the frozen report, and the frozen report must
        never change afterwards."""
        from bot.nam10.no_host_elim_report import (
            _nam10_unlogged_night_resolved_records,
            capture_nam10_elim_report_cutoff,
            resolve_nam10_elim_report_html,
            _game_created_ts,
        )

        # Stop exactly where Seat 7 was eliminated: resolution committed
        # by the walk, publication (and its `night.resolved` audit row)
        # still pending.
        g = await self._run_night(
            mine_pick=0, law_pick=0, do_extra=True, finish=False
        )
        pseudo = _nam10_unlogged_night_resolved_records(g, self.manager)
        self.assertEqual(
            len(pseudo), 1, "resolved-but-unlogged night must be supplied"
        )
        self.assertIn("🔴 شات مافیا", pseudo[0]["night_report_html"])
        self.assertIn("💻 هکر: مبدأ:", pseudo[0]["night_report_html"])

        # After the full publication flow the audit row exists and the
        # cutoff is built from it; the roster AND the timeline present.
        await self._finish_day()
        entry = capture_nam10_elim_report_cutoff(g, self.manager, SYN_UID)
        self.assertIsNotNone(entry)
        report_html = entry["report_html"]
        self.assertIn("بازیکنان و نقش‌ها", report_html)
        self.assertIn("🔴 شات مافیا", report_html)
        self.assertIn("💻 هکر: مبدأ:", report_html)
        self.assertIn("شب ۱", report_html, report_html)
        self.assertEqual(
            report_html.count("🔴 شات مافیا"), 1, report_html
        )

        # Frozen: later state mutation / reads do not rewrite the report.
        g.nmnd_night2_hacker_uids = []
        entry2 = capture_nam10_elim_report_cutoff(g, self.manager, SYN_UID)
        self.assertEqual(entry2["report_html"], entry["report_html"])
        resolved = resolve_nam10_elim_report_html(
            g, SYN_UID, gts=_game_created_ts(g)
        )
        self.assertEqual(resolved, entry["report_html"])

    async def test_skipped_and_spent_abilities_labelled(self):
        g = await self._run_night(
            mine_pick=0, law_pick=0, do_extra=True
        )
        lines = _block_lines(g)
        joined = "\n".join(lines)
        self.assertTrue(
            any("⚖️ وکیل: انتخابی نداشت." in l for l in lines), joined
        )
        self.assertTrue(
            any("💣 مین‌گذار: انتخابی نداشت." in l for l in lines), joined
        )
        self.assertIn("🔴 شات مافیا", joined)
        self.assertIn("💉 پزشک", joined)
        self.assertIn("🧭 راهنما", joined)
        self.assertIn("🛡️ محافظ", joined)


if __name__ == "__main__":
    unittest.main()
