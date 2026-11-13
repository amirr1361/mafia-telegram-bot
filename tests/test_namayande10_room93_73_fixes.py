#!/usr/bin/env python3
"""Patch P — Room 93 + Room 73 regression tests (Task 4).

Room 93 equivalents: daytime Rebel assassination eliminations must appear
in the end-of-game timeline under the ACTUAL day, in the correct order,
with no fabricated night block for a night that never happened.

Room 73 equivalents: a successful NATO elimination of an effectively
mined target must detonate the mine exactly once and force the existing
deferred Mafia-casualty selection flow.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import json  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_night_publish import (  # noqa: E402
    _SkipInheritedTests,
)
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
                a for a in vars(base) if a.startswith("test_") and a not in own
            ]:
                setattr(cls, attr, None)
        return cls


REBEL_TAG = "میز ۲ — یاغی"
TARGET_TAG = "میز ۵ — هدف"
LINE_REBEL = "🎯 صندلی ۲ — یاغی با اجرای ترور از بازی خارج شد."
LINE_TARGET = "🩸 صندلی ۵ — هدف بر اثر ترور از بازی خارج شد."
WINNER_LINE = "🏁 پایان بازی: <b>شهروند</b> برنده شد."


class Room93TimelineFixTest(
    _v2.Nam10NightV2Test, metaclass=_SkipAllInherited
):
    """Timeline attribution of daytime assassinations (Room 93)."""

    # ------------------------------------------------------------ helpers

    def _timeline(self, records, *, scenario: str = "namayande") -> str:
        from bot.main import _build_bazpors_timeline_html

        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for rec in records:
            tmp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp.close()
        snap = {
            "scenario_name": scenario,
            "nmnd_host_mode": "no_host" if scenario == "namayande" else None,
            "rows": [
                {"user_id": -920002, "tag": REBEL_TAG},
                {"user_id": -920005, "tag": TARGET_TAG},
            ],
            "audit_log_path": tmp.name,
        }
        return _build_bazpors_timeline_html(snap)

    def _room93_records(self, *, day_elim: bool = False):
        recs = [
            {
                "ts": "2026-10-26T09:30:00+00:00",
                "event": "night.resolved",
                "bazpors": {
                    "narrator_step": "night_actions",
                    "host_day": 3,
                    "night_count": 3,
                },
                "night_report_html": "pre\n🌙 ═══ گزارش کامل شب گذشته ═══\n"
                "🔴 شات مافیا: صندلی ۳",
            },
            {
                "ts": "2026-10-26T09:44:23+00:00",
                "event": "no_host.day_started_after_night",
                "host_day": 4,
                "night_count": 3,
            },
        ]
        if day_elim:
            recs.append(
                {
                    "ts": "2026-10-26T09:45:07+00:00",
                    "event": "night2.rebel_assassination_day_elim",
                    "rebel_uid": -920002,
                    "target_uid": -920005,
                    "target_eliminated": True,
                    "reason": "eliminated",
                    "host_day": 4,
                    "night": 3,
                }
            )
        recs.extend(
            [
                {
                    "ts": "2026-10-26T09:45:07.893800+00:00",
                    "event": "night2.elimination",
                    "uid": -920002,
                    "cause": "rebel_assassination_self",
                    "night": 3,
                },
                {
                    "ts": "2026-10-26T09:45:07.894044+00:00",
                    "event": "night2.elimination",
                    "uid": -920005,
                    "cause": "rebel_assassination",
                    "night": 3,
                },
                {
                    "ts": "2026-10-26T09:45:07.894178+00:00",
                    "event": "night2.rebel_assassination_effect",
                    "rebel_uid": -920002,
                    "target_uid": -920005,
                    "target_eliminated": True,
                    "reason": "eliminated",
                    "night": 3,
                },
            ]
        )
        if day_elim:
            # Simulate a restart replay: the same records logged twice.
            recs = recs + [
                dict(r, ts=r["ts"] + "x") if r.get("event") == "night2.elimination" else r
                for r in recs[-3:]
            ]
        recs.append(
            {
                "ts": "2026-10-26T09:45:10+00:00",
                "event": "game.ended",
                "winner": "citizen",
                "bazpors": {
                    "narrator_step": "day_discuss",
                    "host_day": 4,
                    "night_count": 3,
                },
            }
        )
        return recs

    # ------------------------------------------------------------ tests

    def test_day4_assassinations_render_no_fabricated_night4(self):
        out = self._timeline(self._room93_records())
        self.assertIn(LINE_REBEL, out)
        self.assertIn(LINE_TARGET, out)
        self.assertIn(WINNER_LINE, out)
        # Correct order: both eliminations before the winner line.
        self.assertLess(out.index(LINE_REBEL), out.index(WINNER_LINE))
        self.assertLess(out.index(LINE_TARGET), out.index(WINNER_LINE))
        # Night 4 never happened: no fabricated block, no "بدون اتفاق".
        self.assertNotIn("🌙 <b>شب ۴</b>", out)
        self.assertNotIn("🌙 <b>شب ۴</b> - بدون اتفاق", out)
        # Night 3 (which did happen) is still rendered.
        self.assertIn("🌙 <b>شب ۳</b>", out)
        self.assertIn("🔴 شات مافیا: صندلی ۳", out)

    def test_day_elim_records_render_once(self):
        out = self._timeline(self._room93_records(day_elim=True))
        self.assertEqual(out.count(LINE_REBEL), 1)
        self.assertEqual(out.count(LINE_TARGET), 1)
        self.assertNotIn("🌙 <b>شب ۴</b>", out)

    def test_duplicate_audit_replay_is_deduped(self):
        recs = self._room93_records()
        # Full restart-style replay of every record.
        out = self._timeline(recs + [dict(r) for r in recs])
        self.assertEqual(out.count(LINE_REBEL), 1)
        self.assertEqual(out.count(LINE_TARGET), 1)

    def test_game_ended_during_night_keeps_night_block(self):
        recs = [
            {
                "ts": "2026-10-26T08:00:00+00:00",
                "event": "night.resolved",
                "bazpors": {
                    "narrator_step": "night_actions",
                    "host_day": 3,
                    "night_count": 3,
                },
                "night_report_html": "pre\n🌙 ═══ گزارش کامل شب گذشته ═══\n"
                "🔴 شات مافیا: صندلی ۳",
            },
            {
                "ts": "2026-10-26T08:05:00+00:00",
                "event": "game.ended",
                "winner": "mafia",
                "bazpors": {
                    "narrator_step": "night_actions",
                    "host_day": 3,
                    "night_count": 3,
                },
            },
        ]
        out = self._timeline(recs)
        # The game ended during Night 3: the night block stays.
        self.assertIn("🌙 <b>شب ۳</b>", out)
        self.assertIn("🔴 شات مافیا: صندلی ۳", out)
        self.assertNotIn("☀️ <b>روز ۴</b>", out)

    def test_other_scenarios_keep_legacy_no_events_night(self):
        recs = [
            {
                "ts": "2026-10-26T08:00:00+00:00",
                "event": "game.ended",
                "winner": "citizen",
                "bazpors": {
                    "narrator_step": "day_discuss",
                    "host_day": 2,
                    "night_count": 1,
                },
            }
        ]
        out = self._timeline(recs, scenario="bazpors")
        # Legacy behaviour untouched for non-Namayande scenarios.
        self.assertIn("🌙 <b>شب ۲</b> - بدون اتفاق", out)

    def test_assassination_audit_carries_host_day(self):
        self._fork_room()
        g = self.game
        g.nmnd_narrator_host_day = 4
        g.nmnd_narrator_night_count = 3
        g.nmnd_night2_rebel_unlocked = True
        from bot.nam10.night2 import night2_rebel_assassination_effect

        res = night2_rebel_assassination_effect(g, CIT1_UID)
        self.assertTrue(res["accepted"], res)
        recs = [
            json.loads(line)
            for line in open(g.audit_log_path, encoding="utf-8")
            if line.strip()
        ]
        evs = [
            r
            for r in recs
            if r.get("event") == "night2.rebel_assassination_day_elim"
        ]
        self.assertEqual(len(evs), 1)
        ev = evs[0]
        self.assertEqual(ev["host_day"], 4)
        self.assertEqual(ev["rebel_uid"], NATO_UID)
        self.assertEqual(ev["target_uid"], CIT1_UID)
        self.assertTrue(ev["target_eliminated"])
        self.assertFalse(g.players[NATO_UID].is_alive)
        self.assertFalse(g.players[CIT1_UID].is_alive)
        # Once-per-game: a replayed commit adds no second record.
        res2 = night2_rebel_assassination_effect(g, CIT1_UID)
        self.assertFalse(res2["accepted"])
        recs2 = [
            json.loads(line)
            for line in open(g.audit_log_path, encoding="utf-8")
            if line.strip()
        ]
        self.assertEqual(
            len(
                [
                    r
                    for r in recs2
                    if r.get("event")
                    == "night2.rebel_assassination_day_elim"
                ]
            ),
            1,
        )


NATO_REPORT_MARK = "🎭 ناتویی مافیا: موفق"
NATO_MINE_MARK = "💣 مین روی هدف ناتو منفجر شد."
MINE_PLACED_MARK = "💣 مین‌گذار: مین روی"


class Room73NatoMineTest(
    _v2.Nam10NightV2ResolveTest, metaclass=_SkipAllInherited
):
    """Successful NATO on an effectively mined target (Room 73)."""

    # ------------------------------------------------------------ helpers

    async def _press_bzn(self, actor_uid, act, as_uid=None, tid=0):
        from aiogram.enums import ChatType
        from aiogram.types import (
            CallbackQuery,
            Chat,
            Message,
            Update,
            User,
        )
        from unittest.mock import MagicMock

        from bot.nam10.nmnd_narrator import BazporsNarrCb

        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        data = BazporsNarrCb(
            code=self.game.room_code, act=act, tid=tid
        ).pack()
        cq = CallbackQuery(
            id=f"cq-b-{len(self.bot.calls)}",
            from_user=actor,
            chat_instance="ci",
            data=data,
            message=Message(
                message_id=888,
                date=datetime.now(timezone.utc),
                chat=Chat(id=actor_uid, type=ChatType.PRIVATE),
                from_user=actor,
            ),
        )
        update = Update(
            update_id=5_000_000 + len(self.bot.calls), callback_query=cq
        )
        await self.dp.feed_update(self.bot, update)

    def _mark(self, chat_id):
        return "\n".join(self.bot.texts_to(chat_id))

    async def _walk_nato_mine(
        self,
        *,
        nato_role_tid: int = 2,
        nato_target: int = GUIDE_UID,
        mine_pick: int = GUIDE_UID,
        doc_pick: int | None = CIT1_UID,
    ):
        await self._walk_v2(
            boss_tid=3,
            nato_role_tid=nato_role_tid,
            nato_target=nato_target,
            doc_pick=doc_pick,
            mine_pick=mine_pick,
            law_pick=0,
            do_extra=False,
        )

    # ------------------------------------------------------------ tests

    async def test_nato_success_on_mined_target_triggers_mine(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_nato_mine()
        outcome = g.nmnd_night2_outcome or {}
        nato = outcome.get("nato") or {}
        mine = outcome.get("mine") or {}
        self.assertTrue(nato.get("activated"))
        self.assertTrue(nato.get("success"))
        self.assertTrue(nato.get("eliminated"))
        self.assertFalse(g.players[GUIDE_UID].is_alive)
        # Mine activated + consumed exactly once.
        self.assertTrue(mine.get("triggered_by_nato"), outcome.get("mine"))
        self.assertTrue(mine.get("triggered"))
        self.assertTrue(mine.get("mafia_casualty_deferred"))
        self.assertIsNone(g.nmnd_night2_active_mine_uid)
        trig = [
            e for e in g.nmnd_night2_mine_events if e.get("triggered")
        ]
        self.assertEqual(len(trig), 1)
        self.assertEqual(trig[0].get("mode"), "nato")
        self.assertEqual(trig[0].get("target_uid"), GUIDE_UID)
        # No shot was fired in this night.
        self.assertFalse(g.nmnd_night2_shot_result)
        # Mandatory Mafia casualty requirement surfaced.
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        from bot.nam10 import night2_publish as pub

        self.assertEqual(
            pub.N2PUB_MINE_NAP_WAIT, pub.night2_publication_stage(g)
        )
        self.assertTrue(
            any("💥 مین فعال شد!" in t for _, t in self.bot.sends())
        )

    async def test_nato_mine_report_lines(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_nato_mine()
        from bot.nam10.night2_publish import night2_night_report_extra_section

        report = night2_night_report_extra_section(g, self.manager)
        self.assertIn(NATO_REPORT_MARK, report)
        self.assertIn("🚪 نتیجه: بازیکن انتخاب‌شده از بازی خارج شد.", report)
        self.assertIn(NATO_MINE_MARK, report)
        self.assertIn(MINE_PLACED_MARK, report)

    async def test_nato_mine_casualty_full_flow(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_nato_mine()
        from bot.nam10 import night2_publish as pub
        from bot.nam10.night2 import ELIM_CAUSE_MINE_MAFIA

        # B1: helper nap confirmation (two explicit steps).
        await self._press_bzn(ASSIST_UID, "nnap")
        self.assertEqual(
            pub.N2PUB_MINE_NAP_CONFIRM, pub.night2_publication_stage(g)
        )
        await self._press_bzn(ASSIST_UID, "nnapok")
        self.assertEqual(
            pub.N2PUB_MINE_CHOOSER, pub.night2_publication_stage(g)
        )
        # Chooser priority: the living Mafia Boss owns the panel.
        self.assertEqual(g.nmnd_night2_mine_chooser_uid, BOSS_UID)
        # Selection + confirmation (choose the Hacker, as in the live room).
        await self._press(BOSS_UID, "mpck", BOSS_UID, tid=SHIAD_UID)
        self.assertEqual(g.nmnd_night2_mine_chooser_pending_uid, SHIAD_UID)
        await self._press(BOSS_UID, "mpok", BOSS_UID)
        self.assertEqual(g.nmnd_night2_mine_casualty_uid, SHIAD_UID)
        # No elimination before every other living player gave OK.
        self.assertTrue(g.players[SHIAD_UID].is_alive)
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        for uid in (MINE_UID, NATO_UID, SHIAD_UID, LAW_UID, GUARD_UID, DOC_UID):
            await self._press(uid, "mwok", uid)
        await self._press(CIT1_UID, "mwok", CIT1_UID)
        await self._press(OBS_UID, "mwok", SYN_UID)
        # Single confirmed elimination; pending fully cleared.
        self.assertFalse(g.players[SHIAD_UID].is_alive)
        recs = [
            r
            for r in g.nmnd_night2_eliminations
            if r.get("uid") == SHIAD_UID
            and r.get("cause") == ELIM_CAUSE_MINE_MAFIA
        ]
        self.assertEqual(len(recs), 1)
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)
        self.assertEqual(
            pub.N2PUB_DISCIPLINE, pub.night2_publication_stage(g)
        )
        outcome_mine = g.nmnd_night2_outcome["mine"]
        self.assertFalse(outcome_mine["mafia_casualty_deferred"])
        self.assertEqual(outcome_mine["mafia_casualty_uid"], SHIAD_UID)
        self.assertTrue(outcome_mine["mafia_casualty_applied"])

    async def test_nato_success_on_unmined_target_no_trigger(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_nato_mine(mine_pick=0)
        outcome = g.nmnd_night2_outcome or {}
        nato = outcome.get("nato") or {}
        mine = outcome.get("mine") or {}
        self.assertTrue(nato.get("success"))
        self.assertTrue(nato.get("eliminated"))
        self.assertFalse(g.players[GUIDE_UID].is_alive)
        self.assertFalse(mine.get("triggered_by_nato", False))
        self.assertFalse(mine.get("triggered", False))
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)

    async def test_nato_fail_on_mined_target_mine_stays(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        # Wrong role guess: the mine is NOT activated by a failed NATO.
        await self._walk_nato_mine(nato_target=CIT1_UID, mine_pick=GUIDE_UID)
        outcome = g.nmnd_night2_outcome or {}
        nato = outcome.get("nato") or {}
        mine = outcome.get("mine") or {}
        self.assertTrue(nato.get("activated"))
        self.assertFalse(nato.get("success"))
        self.assertFalse(nato.get("eliminated"))
        self.assertTrue(g.players[GUIDE_UID].is_alive)
        self.assertTrue(g.players[CIT1_UID].is_alive)
        self.assertFalse(mine.get("triggered_by_nato", False))
        self.assertEqual(g.nmnd_night2_active_mine_uid, GUIDE_UID)
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)

    async def test_mine_on_other_target_not_triggered_by_nato(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        # Mine sits on a different living player; NATO kills the guide.
        await self._walk_nato_mine(mine_pick=CIT1_UID)
        outcome = g.nmnd_night2_outcome or {}
        mine = outcome.get("mine") or {}
        self.assertFalse(mine.get("triggered_by_nato", False))
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)
        self.assertTrue(g.players[CIT1_UID].is_alive)
        # The mine stays active (available to the ordinary shot path).
        self.assertEqual(g.nmnd_night2_active_mine_uid, CIT1_UID)

    async def test_nato_mine_casualty_survives_restart_pending(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_nato_mine()
        # The entire pending requirement lives in durable persisted fields;
        # the active mine is already consumed, so a restart cannot
        # re-arm or re-trigger it.
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        self.assertIsNone(g.nmnd_night2_active_mine_uid)
        from bot.nam10 import night2_publish as pub

        stage_before = pub.night2_publication_stage(g)
        await pub.nam10_night2_publish_tick(self.bot, g, self.manager)
        # Re-ticks are idempotent: same stage, no duplicate broadcast.
        self.assertEqual(stage_before, pub.night2_publication_stage(g))
        trig = [
            e for e in g.nmnd_night2_mine_events if e.get("triggered")
        ]
        self.assertEqual(len(trig), 1)

    async def test_doctor_cancelled_by_nato_keeps_room73_parity(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_nato_mine()
        outcome = g.nmnd_night2_outcome or {}
        doctor = outcome.get("doctor") or {}
        # NATO cancels the Doctor exactly as in the live room.
        self.assertTrue(doctor.get("cancelled"))
        self.assertEqual(doctor.get("cancelled_reason"), "cancelled_by_nato")
