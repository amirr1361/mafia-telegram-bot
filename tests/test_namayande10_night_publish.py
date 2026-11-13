"""Namayande-10 Night v2 publication + mine-casualty flow tests.

Covers the required publication/day-transition behaviors for the
Namayande-10 fork:

- Branch A (no mine): disciplinary ask -> helper answer -> summary
  broadcast (names only) -> table inquiry -> day transition, no early
  day announcements, idempotent.
- Spoiler formatting of the private role message (name + description).
- Branch B (mine triggered): B1 announce + helper nap two-step
  confirmation, B2 chooser priority mafia Boss -> Rebel -> Hacker with
  living-mafia-only targets and single selection + explicit
  confirmation, B3 mandatory OK from every other living player, B4
  rejoin of the discipline/summary/table/day flow.
- Choice gating: unauthorized presses rejected, duplicates rejected,
  reconciliation idempotent, unresolved chooser handled safely.
"""

import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_night_v2 as base
from tests.test_namayande10_night_v2 import (
    ASSIST_UID,
    OBS_UID,
    BOSS_UID,
    NATO_UID,
    SHIAD_UID,
    LAW_UID,
    GUIDE_UID,
    GUARD_UID,
    DOC_UID,
    MINE_UID,
    CIT1_UID,
    SYN_UID,
    STALE_ALERT,
    INVALID_ALERT,
    Nam10NightV2ResolveTest,
)
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    Message,
    Update,
    User,
)

from bot.observer_delivery import PlayerMirrorCb


class _SkipInheritedTests(type):
    """Shadow inherited test methods so only subclass tests run."""

    def __new__(mcls, name, bases, ns):
        own = set(ns)
        for base_cls in bases:
            for attr in [a for a in vars(base_cls) if a.startswith("test_")]:
                if attr not in own:
                    ns[attr] = None
        return super().__new__(mcls, name, bases, ns)


from bot.nam10.nmnd_narrator import BazporsNarrCb
from bot.nam10.nmnd_narrator import Role


class Nam10NightPublishFlowTest(
    Nam10NightV2ResolveTest, metaclass=_SkipInheritedTests
):
    """Publication/day-flow tests (Branch A + Branch B)."""

    # -- Helper-button press (BazporsNarrCb) ------------------------------

    async def _press_bzn(self, actor_uid, act, as_uid=None, tid=0):
        actor = User(id=actor_uid, is_bot=False, first_name=f"U{actor_uid}")
        data = BazporsNarrCb(
            code=self.game.room_code,
            act=act,
            tid=tid,
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

    async def _finish_day(self):
        """Helper: after discipline ask was delivered, answer No and
        decline the table inquiry, then assert the day started."""
        g = self.game
        before_texts = len(self.bot.calls)
        await self._press_bzn(ASSIST_UID, "disc_no")
        await self._press_bzn(ASSIST_UID, "disc_no_ok")
        # Summary broadcast reaches players
        self.assertTrue(
            any(
                "نتیجه نهایی شب و روز گذشته" in (t or "")
                for _, t in self.bot.sends()
            )
        )
        self.assertIn("در این شب اخراج انضباطی نداریم.", "\n".join(t for _, t in self.bot.sends()))
        # Table inquiry ask reaches the helper
        helper_texts = self._mark(ASSIST_UID)
        self.assertIn("استعلام وضعیت میز", helper_texts)
        await self._press_bzn(ASSIST_UID, "tinq_no")
        await self._press_bzn(ASSIST_UID, "tinq_ok")
        # A declined table inquiry routes through the established automatic
        # ownership-handoff offer before the day starts.
        await self._press_bzn(ASSIST_UID, "handoff_skip")
        day_sends = [
            t
            for cid, t in self.bot.sends()[before_texts:]
            if t and "☀️" in t
        ]
        # The day-started broadcast must exist (at least one ☀️ message).
        self.assertTrue(
            any("☀️" in (t or "") for _, t in self.bot.sends())
        )
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

        self.assertEqual(g.nmnd_narrator_step, DAY_DISCUSS)
        self.assertEqual(g.nmnd_narrator_host_day, 2)

    # ------------------------------------------------------------------
    # Spoiler formatting
    # ------------------------------------------------------------------

    async def test_pub_01_role_message_spoilers(self):
        from bot.main import (
            PRIVATE_ROLE_SPOILER_MIN_CHARS,
            build_private_role_message_html,
        )

        self._fork_room()
        from bot.nam10.role_labels import nam10_role_label_fa

        doc_label = nam10_role_label_fa(Role.DOCTOR)
        out = build_private_role_message_html(self.game, Role.DOCTOR)
        # both the role name and the description are inside spoilers
        self.assertEqual(out.count("<tg-spoiler>"), 2)
        # Name and description dividers; nothing outside spoilers leaks.
        self.assertIn("<tg-spoiler>", out)
        # minimum padding keeps the spoiler bar width unguessable
        self.assertIn(
            " " * (PRIVATE_ROLE_SPOILER_MIN_CHARS - len(doc_label)), out
        )
        # nothing outside each spoiler exposes the role name/description
        stripped = re.sub(
            r"<tg-spoiler>.*?</tg-spoiler>", "", out, flags=re.S
        )
        label_word = doc_label.split()[0] if doc_label.split() else doc_label
        if label_word:
            self.assertNotIn(label_word, stripped)

    # ------------------------------------------------------------------
    # Branch A: no mine — full night -> day flow
    # ------------------------------------------------------------------

    async def test_pub_02_branch_a_full_day_flow(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        # Plain Museo shot at the synthetic seat; no mine placed; Doctor
        # protects CIT1 so the shot victim is the only death.
        await self._walk_v2(
            boss_tid=1,
            shot_target=SYN_UID,
            doc_pick=CIT1_UID,
            mine_pick=0,
            law_pick=0,
            do_extra=False,
        )
        from bot.nam10 import night2_publish as pub
        from bot.nam10.night2 import PENDING_RESOLVED

        self.assertEqual(g.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(g.nmnd_night2_publication_pending)
        self.assertTrue(pub.night2_publication_active(g))
        self.assertEqual(pub.N2PUB_DISCIPLINE, pub.night2_publication_stage(g))
        # The helper received the established disciplinary ask panel.
        self.assertIn(
            "اخراج انضباطی", "\n".join(t for _, t in self.bot.sends())
        )
        # No public broadcasts leaked before the helper completed the flow.
        for uid in (BOSS_UID, NATO_UID, CIT1_UID):
            self.assertNotIn(
                "نتیجه نهایی شب و روز گذشته", self._mark(uid)
            )
        self.assertNotIn(
            "💥 مین فعال شد", "\n".join(t for _, t in self.bot.sends())
        )
        await self._finish_day()
        # Day started exactly once; re-tick must not replay anything.
        counts = len([
            t for _, t in self.bot.sends() if t and "☀️" in t
        ])
        await pub.nam10_night2_publish_tick(self.bot, g, self.manager)
        counts_after = len([
            t for _, t in self.bot.sends() if t and "☀️" in t
        ])
        self.assertEqual(counts, counts_after)

    async def test_pub_03_branch_a_summary_privacy(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=SYN_UID,
            doc_pick=CIT1_UID,
            mine_pick=0,
            law_pick=0,
            do_extra=False,
        )
        await self._press_bzn(ASSIST_UID, "disc_no")
        await self._press_bzn(ASSIST_UID, "disc_no_ok")
        # Collect the player-facing summary text (broadcasts to alive
        # players 901..909 and SYN is dead, so check the living town seat).
        player_summaries = [
            t
            for uid, t in self.bot.sends()
            if uid in (BOSS_UID, NATO_UID, SHIAD_UID)
            and t and "نتیجه نهایی شب و روز گذشته" in t
        ]
        self.assertTrue(player_summaries)
        summary = player_summaries[-1]
        self.assertIn("در شبی که گذشت، با ", summary)
        # The DAY part legitimately has its own farewell line; only the
        # night farewell must list the real night death.
        self.assertNotIn(
            "در شبی که گذشت با کسی خداحافظی نکردیم.", summary
        )
        from bot.nam10.role_labels import (
            nam10_role_label_fa,
        )

        for role in (
            Role.MAFIA_BOSS,
            Role.NATO,
            Role.SHIAD,
            Role.DOCTOR,
            Role.HUNTER,
            Role.INTERROGATOR,
            Role.DETECTIVE,
            Role.RUINTAN,
            Role.CITIZEN,
        ):
            self.assertNotIn(
                nam10_role_label_fa(role),
                summary,
                msg=f"role leaked: {nam10_role_label_fa(role)}",
            )

    async def test_pub_04_branch_a_discipline_kick_names_only(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        await self._walk_v2(
            boss_tid=1,
            shot_target=SYN_UID,
            doc_pick=CIT1_UID,
            mine_pick=0,
            law_pick=0,
            do_extra=False,
        )
        await self._press_bzn(ASSIST_UID, "disc_yes")
        await self._press_bzn(ASSIST_UID, "disc_pick", tid=CIT1_UID)
        await self._press_bzn(ASSIST_UID, "disc_ok")
        self.assertFalse(g.players[CIT1_UID].is_alive)
        self.assertEqual(g.nmnd_night_discipline_kick_uid, CIT1_UID)
        player_summaries = [
            t
            for uid, t in self.bot.sends()
            if uid in (BOSS_UID, NATO_UID) and t
            and "نتیجه نهایی شب و روز گذشته" in t
        ]
        self.assertTrue(player_summaries)
        summary = player_summaries[-1]
        # Names only for the disciplinary kick, never the role.
        from bot.nam10.role_labels import nam10_role_label_fa

        self.assertIn("اخراج انضباطی: <b>", summary)
        self.assertNotIn(
            f"— {nam10_role_label_fa(Role.CITIZEN)}", summary
        )

    # ------------------------------------------------------------------
    # Branch B: mine activation full flow
    # ------------------------------------------------------------------

    async def test_pub_05_mine_branch_full_flow(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        from bot.nam10 import night2_publish as pub
        from bot.nam10.night2 import (
            ELIM_CAUSE_MINE_MAFIA,
            PENDING_RESOLVED,
        )

        # Mine placed on CIT1; Boss plain-shots CIT1 -> mine triggers.
        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
            do_extra=False,
        )
        self.assertEqual(g.nmnd_night2_phase, PENDING_RESOLVED)
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        # B1: broadcast + helper nap request; exactly once.
        broadcast_texts = [
            t
            for uid, t in self.bot.sends()
            if uid in (BOSS_UID, NATO_UID) and t and "💥 مین فعال شد!" in t
        ]
        self.assertEqual(len(broadcast_texts), 2)
        self.assertEqual(
            pub.N2PUB_MINE_NAP_WAIT, pub.night2_publication_stage(g)
        )
        helper_nap = "\n".join(self.bot.texts_to(ASSIST_UID))
        self.assertIn("💥 مین فعال شده است!", helper_nap)
        await pub.nam10_night2_publish_tick(self.bot, g, self.manager)
        broadcast_texts = [
            t
            for uid, t in self.bot.sends()
            if uid in (BOSS_UID, NATO_UID) and t and "💥 مین فعال شد!" in t
        ]
        self.assertEqual(
            len(broadcast_texts), 2, "mine announce replayed on re-tick"
        )
        # B1 helper press -> second explicit confirmation step.
        await self._press_bzn(ASSIST_UID, "nnap")
        self.assertEqual(
            pub.N2PUB_MINE_NAP_CONFIRM, pub.night2_publication_stage(g)
        )
        self.assertTrue(
            any(
                "آیا خواب نیمروزی کامل شده است؟" in t
                for _, t in self.bot.sends()
            )
        )
        # Stale first step presses are rejected.
        await self._press_bzn(ASSIST_UID, "nnap")
        self.assertTrue(
            any(STALE_ALERT in (a or "") for a in self.bot.acks())
        )
        # Second step explicit confirmation.
        await self._press_bzn(ASSIST_UID, "nnapok")
        self.assertEqual(
            pub.N2PUB_MINE_CHOOSER, pub.night2_publication_stage(g)
        )
        self.assertTrue(
            any(
                "گوشی‌های خود را تحویل دهند" in t for _, t in self.bot.sends()
            )
        )
        # B2: chooser panel lists ONLY living mafia team members.
        targets = set()
        pending_choices = []
        for b in self._button_objects("انتخاب خروجی تیم مافیا"):
            if not (b.callback_data or "").startswith("pmr:"):
                continue
            cb = PlayerMirrorCb.unpack(b.callback_data)
            if cb is not None and cb.act == "mpck":
                targets.add(cb.tid)
                pending_choices.append(cb)
        self.assertEqual(
            targets, {BOSS_UID, NATO_UID, SHIAD_UID},
            "Chooser panel must list exactly the living mafia members",
        )
        self.assertNotIn("⏳ تیم مافیا", self._mark(BOSS_UID))
        self.assertIn("⏳ تیم مافیا", self._mark(NATO_UID))
        # Gating: the chooser cannot ack the waiting panel.
        await self._press(BOSS_UID, "mwok", BOSS_UID)
        self.assertTrue(
            any(
                "پنل انتخاب خروجی" in (a or "") for a in self.bot.acks()
            )
        )
        self.assertEqual(g.nmnd_night2_mine_wait_acked, [])
        # Gating: another mafia member cannot operate the chooser panel.
        before = len(g.nmnd_night2_mine_wait_acked)
        await self._press(SHIAD_UID, "mpck", BOSS_UID, tid=NATO_UID)
        self.assertTrue(
            any(
                "این پنل برای شما نیست" in (a or "") for a in self.bot.acks()
            )
        )
        self.assertIsNone(g.nmnd_night2_mine_chooser_pending_uid)
        # Confirmation without a selection is rejected.
        await self._press(BOSS_UID, "mpok", BOSS_UID)
        self.assertTrue(
            any(
                "ابتدا یک بازیکن" in (a or "") for a in self.bot.acks()
            )
        )
        # Single selection + explicit confirmation (choose SHIAD).
        await self._press(BOSS_UID, "mpck", BOSS_UID, tid=SHIAD_UID)
        self.assertEqual(g.nmnd_night2_mine_chooser_pending_uid, SHIAD_UID)
        await self._press(BOSS_UID, "mpok", BOSS_UID)
        self.assertEqual(g.nmnd_night2_mine_casualty_uid, SHIAD_UID)
        # No elimination before every other living player gave OK.
        self.assertTrue(g.players[SHIAD_UID].is_alive)
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        self.assertEqual(
            pub.N2PUB_MINE_CHOOSER, pub.night2_publication_stage(g)
        )
        # Waiting acknowledgements — everyone else alive (Observer acks the
        # synthetic seat); duplicate acks are rejected. CIT1 is the shot
        # victim and therefore not part of the acknowledgement group.
        await self._press(MINE_UID, "mwok", MINE_UID)
        self.assertTrue(g.nmnd_night2_mine_wait_acked == [MINE_UID])
        await self._press(MINE_UID, "mwok", MINE_UID)
        self.assertTrue(
            any("قبلاً ثبت شده است" in (a or "") for a in self.bot.acks())
        )
        self.assertEqual(len(g.nmnd_night2_mine_wait_acked), 1)
        for uid in (
            NATO_UID,
            SHIAD_UID,
            LAW_UID,
            GUIDE_UID,
            GUARD_UID,
            DOC_UID,
        ):
            await self._press(uid, "mwok", uid)
        await self._press(OBS_UID, "mwok", SYN_UID)
        # Final acknowledgement triggers the single elimination attempt.
        self.assertFalse(g.players[SHIAD_UID].is_alive)
        recs = [
            r for r in g.nmnd_night2_eliminations
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
        # B4: the helper now receives the disciplinary ask panel.
        self.assertIn(
            "اخراج انضباطی", "\n".join(self.bot.texts_to(ASSIST_UID))
        )
        await self._finish_day()
        # Summary shows both night deaths by name only.
        player_summaries = [
            t
            for uid, t in self.bot.sends()
            if uid in (BOSS_UID, LAW_UID) and t
            and "نتیجه نهایی شب و روز گذشته" in t
        ]
        self.assertTrue(player_summaries)
        summary = player_summaries[-1]
        from bot.nam10.role_labels import nam10_role_label_fa

        self.assertIn("بازیکن 9", summary)      # CIT1 (shot victim)
        self.assertIn("بازیکن 3", summary)      # SHIAD (mine casualty)
        for role in (
            Role.SHIAD,
            Role.CITIZEN,
            Role.MAFIA_BOSS,
        ):
            self.assertNotIn(nam10_role_label_fa(role), summary)
        self.assertNotIn("💥 مین فعال شد —", summary)

    async def test_pub_06_mine_wait_ok_all_required(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        from bot.nam10 import night2_publish as pub

        await self._walk_v2(
            boss_tid=1,
            shot_target=CIT1_UID,
            doc_pick=SYN_UID,
            mine_pick=CIT1_UID,
            law_pick=0,
            do_extra=False,
        )
        await self._press_bzn(ASSIST_UID, "nnap")
        await self._press_bzn(ASSIST_UID, "nnapok")
        # All acknowledgements first; the chooser confirmation is last.
        for uid in (NATO_UID, SHIAD_UID, LAW_UID, GUIDE_UID):
            await self._press(uid, "mwok", uid)
        # Missing acks keep the casualty pending.
        await self._press(BOSS_UID, "mpck", BOSS_UID, tid=NATO_UID)
        await self._press(BOSS_UID, "mpok", BOSS_UID)
        self.assertTrue(g.players[NATO_UID].is_alive)
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        for uid in (GUARD_UID, DOC_UID, MINE_UID):
            await self._press(uid, "mwok", uid)
        await self._press(OBS_UID, "mwok", SYN_UID)
        self.assertFalse(g.players[NATO_UID].is_alive)
        self.assertEqual(
            pub.N2PUB_DISCIPLINE, pub.night2_publication_stage(g)
        )

    # ------------------------------------------------------------------
    # Chooser priority + unresolvable state
    # ------------------------------------------------------------------

    async def test_pub_07_chooser_priority_chain(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        from bot.nam10 import night2_publish as pub

        self.assertEqual(pub._mine_chooser_uid(g), BOSS_UID)
        g.players[BOSS_UID].is_alive = False
        self.assertEqual(pub._mine_chooser_uid(g), NATO_UID)
        g.players[NATO_UID].is_alive = False
        self.assertEqual(pub._mine_chooser_uid(g), SHIAD_UID)
        g.players[SHIAD_UID].is_alive = False
        self.assertIsNone(pub._mine_chooser_uid(g))

    async def test_pub_08_mine_unresolved_no_chooser(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        from bot.nam10 import night2_publish as pub
        from bot.nam10.night2 import PENDING_RESOLVED

        # No player action: simulate the committed resolution with a
        # pending mine casualty and no eligible decision-maker.
        g.players[BOSS_UID].is_alive = False
        g.players[NATO_UID].is_alive = False
        g.players[SHIAD_UID].is_alive = False
        g.nmnd_night2_phase = PENDING_RESOLVED
        g.nmnd_night2_resolved = True
        g.nmnd_night2_resolved_night = g.nmnd_narrator_night_count
        g.nmnd_night2_publication_pending = True
        g.nmnd_night2_mine_casualty_pending = True
        g.nmnd_night2_outcome = {
            "mine": {"triggered": True, "mafia_casualty_deferred": True}
        }
        awaited = await pub.nam10_night2_publish_tick(self.bot, g, self.manager)
        self.assertTrue(awaited)
        self.assertTrue(pub.night2_publication_active(g))
        await self._press_bzn(ASSIST_UID, "nnap")
        await self._press_bzn(ASSIST_UID, "nnapok")
        # No chooser invented: casualty stays unapplied, flow falls through
        # to the disciplinary ask with a helper report.
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)
        self.assertIsNone(g.nmnd_night2_mine_chooser_uid)
        self.assertTrue(
            g.nmnd_night2_outcome["mine"]["mafia_casualty_unresolved"]
        )
        self.assertEqual(
            pub.N2PUB_DISCIPLINE, pub.night2_publication_stage(g)
        )
        self.assertIn("یافت نشد", "\n".join(self.bot.texts_to(ASSIST_UID)))

    # ------------------------------------------------------------------
    # Ordering invariants
    # ------------------------------------------------------------------

    async def test_pub_09_no_early_day_transition(self):
        self._fork_room()
        g = self.game
        await self._enter_night()
        from bot.nam10 import night2_publish as pub
        from bot.nam10.nmnd_narrator import DAY_DISCUSS

        await self._walk_v2(
            boss_tid=1,
            shot_target=SYN_UID,
            doc_pick=CIT1_UID,
            mine_pick=0,
            law_pick=0,
            do_extra=False,
        )
        # Publication is active but the day machine must not have started.
        self.assertTrue(pub.night2_publication_active(g))
        self.assertNotEqual(g.nmnd_narrator_step, DAY_DISCUSS)
        self.assertEqual(g.nmnd_narrator_night_count, 1)
        from bot.models import Phase

        self.assertEqual(g.phase, Phase.MANUAL)
        self.assertFalse(g.nmnd_night2_mine_announced)
        # No day broadcast, no table inquiry before the helper completed
        # the publication stages.
        self.assertNotIn("☀️", "\n".join(t for _, t in self.bot.sends()))
        self.assertNotIn(
            "استعلام وضعیت میز", "\n".join(t for _, t in self.bot.sends())
        )


if __name__ == "__main__":
    unittest.main()
