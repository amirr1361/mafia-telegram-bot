#!/usr/bin/env python3
"""Namayande family — Room 32 fixes regression tests.

Covers (all Namayande counts where the mechanics exist):
- NATO handoff: shooter panel deletion, transferred readiness, the
  recipient staying NOT ready until both stages complete, no premature
  night completion / disciplinary panel, shooter buttons dead after the
  handoff, snapshot-restore safety.
- Mine sacrifice vs temporary-Sniper ordering: the deferred Sniper
  elimination, Hacker eligibility in the sacrifice roster, one-vs-two
  exit outcomes, cause attribution, protection cases.
- Guide-identity disclosure delayed until all mandatory Mafia main
  actions settle.
- Soldier/Sniper panels: two buttons per row.
- Public congratulation for a valid Sniper mafia elimination.
"""

import os
import sys
import unittest
from datetime import datetime, timezone  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_expansion as _exp  # noqa: E402
import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_expansion import (  # noqa: E402
    AGT_UID,
    CIT2_UID,
    SOL_UID,
)
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

STALE = "این مرحله دیگر فعال نیست"
NOTICE_MARK = "🧭 شناسایی راهنما"
CONGRAT_MARK = (
    "🎯 آفرین به شهر! اسنایپر امشب با شلیکی دقیق، "
    "یکی از اعضای مافیا را از بازی خارج کرد."
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


class _BznPressMixin:
    """Bazpors-narrator callback press (helper nap confirmations)."""

    async def _press_bzn(self, actor_uid, act, as_uid=None, tid=0):
        from aiogram.enums import ChatType
        from aiogram.types import (
            CallbackQuery,
            Chat,
            Message,
            Update,
            User,
        )

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


async def _settle_all_but_shooter(test) -> None:
    """Complete every non-shooter night obligation in a 12-room.

    Mirrors ``_walk12`` for everything except the Boss: the Soldier's
    lifetime allowance is consumed, the Guide's extra investigation is
    done, and all waiting panels are acknowledged. Afterwards the
    shooter (Boss) is the only remaining obligation holder.
    """
    g = test.game
    await test._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
    await test._press(DOC_UID, "docok", DOC_UID)
    await test._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
    await test._press(SHIAD_UID, "hacn", SHIAD_UID)
    await test._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
    await test._press(SHIAD_UID, "hacok", SHIAD_UID)
    await test._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
    await test._press(GUIDE_UID, "gdsok", GUIDE_UID)
    await test._press(GUARD_UID, "gdnp", GUARD_UID, tid=BOSS_UID)
    await test._press(GUARD_UID, "gdnok", GUARD_UID)
    await test._press(MINE_UID, "minp", MINE_UID, tid=0)
    await test._press(MINE_UID, "minok", MINE_UID)
    await test._press(LAW_UID, "lawp", LAW_UID, tid=0)
    await test._press(LAW_UID, "lawok", LAW_UID)
    g.nmnd_night2_soldier_used = True
    await test._press(SOL_UID, "waitok", SOL_UID)
    await test._press(NATO_UID, "waitok", NATO_UID)
    await test._press(CIT1_UID, "waitok", CIT1_UID)
    await test._press(OBS_UID, "waitok", SYN_UID)
    await test._press(AGT_UID, "waitok", AGT_UID)
    # The granted extra panel materializes only after the recipient's
    # own main action (waiting ack) settles — like _walk12's tail.
    await test._press(CIT1_UID, "exin", CIT1_UID, tid=DOC_UID)
    await test._press(CIT1_UID, "exok", CIT1_UID)


async def _ack_mine_waiters(test):
    """Waiting acknowledgements for the mine-casualty stage.

    Every living player except the chooser (Boss) must acknowledge —
    including the chosen casualty (Room 73 flow); synthetic seats ack
    via the Observer.
    """
    for uid in (
        NATO_UID,
        AGT_UID,
        SHIAD_UID,
        LAW_UID,
        GUIDE_UID,
        GUARD_UID,
        DOC_UID,
        MINE_UID,
        CIT1_UID,
    ):
        await test._press(uid, "mwok", uid)
    await test._press(OBS_UID, "mwok", SYN_UID)


class Room32NatoHandoffTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """NATO handoff ownership + readiness (12-room, Room 32)."""

    async def test_handoff_transfers_readiness_and_deletes_panel(self):
        from bot.nam10.night2 import (
            BOSS_PHASE_NATO_ROLE,
            PENDING_COLLECTING,
            night2_required_keys,
        )
        from bot.observer_delivery import mirror_ui_claim_key

        self._fork12()
        await self._enter_night()
        await _settle_all_but_shooter(self)
        g = self.game
        self.assertEqual(night2_required_keys(g), ["MAFIA_BOSS"])
        boss_key = mirror_ui_claim_key(g.room_code, "n2boss", BOSS_UID)
        self.assertIn(boss_key, g.mirror_prompt_messages)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(g.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)
        # The shooter's interactive panel is deleted by the handoff.
        self.assertNotIn(boss_key, g.mirror_prompt_messages)
        # The handoff transferred the pending obligation: only the NATO
        # recipient owes readiness now, and the night cannot resolve.
        self.assertEqual(night2_required_keys(g), ["NATO_AGENT"])
        self.assertEqual(g.nmnd_night2_phase, PENDING_COLLECTING)
        self.assertFalse(g.nmnd_night2_outcome_committed)
        # The agent's two-stage panel is live (stage 1).
        self.assertIn("🎭 ناتو", "\n".join(self.bot.texts_to(AGT_UID)))

    async def test_agent_stage1_active_not_stale(self):
        from bot.nam10.night2 import BOSS_PHASE_NATO_ROLE

        self._fork12()
        await self._enter_night()
        await _settle_all_but_shooter(self)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        # The stage-1 pick was accepted (no stale alert anywhere) and
        # the phase is still the agent's NATO stage.
        self.assertFalse(
            any(STALE in (a or "") for a in self.bot.acks()),
            self.bot.acks(),
        )
        self.assertEqual(self.game.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)

    async def test_both_stages_complete_and_night_finishes_after(self):
        from bot.nam10.night2 import BOSS_PHASE_DONE, night2_required_keys
        from bot.models import Role

        self._fork12()
        await self._enter_night()
        await _settle_all_but_shooter(self)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        await self._press(AGT_UID, "nrok", AGT_UID)
        self.assertEqual(
            self.game.nmnd_night2_nato_role, Role.INTERROGATOR.value
        )
        await self._press(AGT_UID, "npl", AGT_UID, tid=GUIDE_UID)
        await self._press(AGT_UID, "npok", AGT_UID)
        g = self.game
        self.assertEqual(g.nmnd_night2_boss_phase, BOSS_PHASE_DONE)
        # The recipient already acknowledged his waiting panel earlier,
        # so with NATO settled every obligation is complete and the
        # collection finishes exactly here (not before).
        self.assertTrue(g.nmnd_night2_outcome_committed)
        outcome = g.nmnd_night2_outcome or {}
        self.assertTrue((outcome.get("nato") or {}).get("activated"))
        self.assertTrue((outcome.get("nato") or {}).get("success"))

    async def test_shooter_buttons_dead_after_handoff(self):
        self._fork12()
        await self._enter_night()
        await _settle_all_but_shooter(self)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.bot.calls.clear()
        # Stale-mode reselection and old shot buttons are rejected.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        self.assertTrue(
            any(STALE in (a or "") for a in self.bot.acks()),
            self.bot.acks(),
        )
        g = self.game
        self.assertIsNone(g.nmnd_night2_shot_target_uid)
        self.assertIsNone(g.nmnd_night2_shot_pending_uid)

    async def test_no_premature_discipline_before_nato_done(self):
        from bot.nam10 import night2_publish as pub

        self._fork12()
        await self._enter_night()
        await _settle_all_but_shooter(self)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        # No publication/discipline flow ran while NATO is pending.
        self.assertFalse(self.game.nmnd_night2_publication_pending)
        self.assertFalse(pub.night2_publication_active(self.game))
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        await self._press(AGT_UID, "nrok", AGT_UID)
        await self._press(AGT_UID, "npl", AGT_UID, tid=GUIDE_UID)
        # Still nothing premature mid-stage.
        self.assertFalse(self.game.nmnd_night2_publication_pending)
        await self._press(AGT_UID, "npok", AGT_UID)
        # With NATO settled (and the earlier waiting ack recorded) the
        # flow may now legitimately start — but only now.
        self.assertTrue(self.game.nmnd_night2_publication_pending)

    async def test_handoff_survives_snapshot_restore(self):
        from bot.game import GameManager
        from bot.game_snapshot import (
            persist_game_snapshot,
            restore_games_into_manager,
        )
        from bot.nam10.night2 import (
            BOSS_PHASE_NATO_ROLE,
            night2_required_keys,
        )

        self._fork12()
        await self._enter_night()
        await _settle_all_but_shooter(self)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        g = self.game
        persist_game_snapshot(g, reason="test_room32")
        code = g.room_code
        self.manager.games.pop(code, None)
        self.manager.host_to_room.pop(g.host_id, None)
        m2 = GameManager()
        restore_games_into_manager(m2)
        back = m2.get_game(code)
        self.assertIsNotNone(back)
        # Handoff state survives the restart: phase, panel deletion and
        # the transferred readiness obligation.
        self.assertEqual(back.nmnd_night2_boss_phase, BOSS_PHASE_NATO_ROLE)
        self.assertEqual(night2_required_keys(back), ["NATO_AGENT"])
        self.assertNotIn(
            "n2boss", " ".join(list(back.mirror_prompt_messages.keys()))
        )


class Room32SniperMineTest(
    _exp.NamExpansionRoomTest, _BznPressMixin, metaclass=_SkipAllInherited
):
    """Mine sacrifice vs temporary-Sniper elimination ordering."""

    async def _walk_sniper_mine(self, *, sniper_target=SHIAD_UID):
        await self._walk12(
            boss_tid=1,
            shot_target=SOL_UID,
            doc_pick=DOC_UID,
            soldier_target=DOC_UID,
            sniper_target=sniper_target,
            mine_pick=SOL_UID,
            law_pick=0,
            do_extra=False,
        )

    async def _finish_casualty(self, *, casualty_uid):
        from bot.nam10 import night2_publish as pub

        await self._press_bzn(ASSIST_UID, "nnap")
        self.assertEqual(
            pub.N2PUB_MINE_NAP_CONFIRM, pub.night2_publication_stage(self.game)
        )
        await self._press_bzn(ASSIST_UID, "nnapok")
        self.assertEqual(
            pub.N2PUB_MINE_CHOOSER, pub.night2_publication_stage(self.game)
        )
        await self._press(BOSS_UID, "mpck", BOSS_UID, tid=casualty_uid)
        await self._press(BOSS_UID, "mpok", BOSS_UID)
        await _ack_mine_waiters(self)

    async def test_sniper_hacker_deferred_roster_keeps_hacker(self):
        from bot.nam10.night2 import GRANT_STATUS_DELIVERED
        from bot.nam10.night2_publish import _mine_mafia_targets

        self._fork12()
        await self._enter_night()
        await self._walk_sniper_mine()
        g = self.game
        outcome = g.nmnd_night2_outcome or {}
        sniper_out = outcome.get("soldier_sniper") or {}
        mine = outcome.get("mine") or {}
        self.assertEqual(
            g.nmnd_night2_soldier_grant_status, GRANT_STATUS_DELIVERED
        )
        self.assertTrue(sniper_out.get("deferred"), sniper_out)
        self.assertIsNone(sniper_out.get("eliminated_uid"))
        self.assertEqual(g.nmnd_night2_sniper_deferred_elim_uid, SHIAD_UID)
        self.assertEqual(sniper_out.get("reason"), "mafia_member_eliminated")
        # The Hacker is still ALIVE and eligible for the sacrifice.
        self.assertTrue(g.players[SHIAD_UID].is_alive)
        self.assertTrue(mine.get("triggered"), outcome.get("mine"))
        self.assertTrue(mine.get("mafia_casualty_deferred"))
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)
        roster = {p.user_id for p in _mine_mafia_targets(g)}
        self.assertEqual(roster, {BOSS_UID, NATO_UID, SHIAD_UID, AGT_UID})
        # Per-night congratulation flag recorded with the valid shot.
        self.assertEqual(
            g.nmnd_night2_sniper_mafia_kill_night,
            g.nmnd_narrator_night_count,
        )

    async def test_case_b_other_sacrifice_two_exits(self):
        from bot.nam10 import night2_publish as pub
        from bot.nam10.night2 import ELIM_CAUSE_MINE_MAFIA, ELIM_CAUSE_SNIPER

        self._fork12()
        await self._enter_night()
        await self._walk_sniper_mine()
        g = self.game
        await self._finish_casualty(casualty_uid=AGT_UID)
        # Two distinct exits: the agent (sacrifice) and the Hacker (sniper).
        self.assertFalse(g.players[AGT_UID].is_alive)
        self.assertFalse(g.players[SHIAD_UID].is_alive)
        agent_recs = [
            r
            for r in g.nmnd_night2_eliminations
            if r.get("uid") == AGT_UID
            and r.get("cause") == ELIM_CAUSE_MINE_MAFIA
        ]
        hacker_recs = [
            r
            for r in g.nmnd_night2_eliminations
            if r.get("uid") == SHIAD_UID
            and r.get("cause") == ELIM_CAUSE_SNIPER
        ]
        self.assertEqual(len(agent_recs), 1)
        self.assertEqual(len(hacker_recs), 1)
        sniper_out = g.nmnd_night2_sniper_result or {}
        self.assertFalse(sniper_out.get("shared_with_mine_casualty"))
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)
        self.assertIsNone(g.nmnd_night2_sniper_deferred_elim_uid)
        self.assertEqual(
            pub.N2PUB_DISCIPLINE, pub.night2_publication_stage(g)
        )

    async def test_case_a_hacker_as_sacrifice_single_exit(self):
        from bot.nam10.night2 import ELIM_CAUSE_MINE_MAFIA, ELIM_CAUSE_SNIPER

        self._fork12()
        await self._enter_night()
        await self._walk_sniper_mine()
        g = self.game
        await self._finish_casualty(casualty_uid=SHIAD_UID)
        # Exactly one exit for the Hacker with both causes recorded.
        self.assertFalse(g.players[SHIAD_UID].is_alive)
        exits = [
            r for r in g.nmnd_night2_eliminations if r.get("uid") == SHIAD_UID
        ]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0].get("cause"), ELIM_CAUSE_MINE_MAFIA)
        self.assertEqual(len(hacker_recs_cause_sniper(g)), 0)
        sniper_out = g.nmnd_night2_sniper_result or {}
        self.assertEqual(sniper_out.get("reason"), "mafia_member_eliminated")
        self.assertTrue(sniper_out.get("shared_with_mine_casualty"))
        self.assertFalse(g.nmnd_night2_mine_casualty_pending)
        self.assertIsNone(g.nmnd_night2_sniper_deferred_elim_uid)

    async def test_sniper_town_target_sniper_dies_immediately(self):
        from bot.nam10.night2 import ELIM_CAUSE_SNIPER

        self._fork12()
        await self._enter_night()
        await self._walk_sniper_mine(sniper_target=CIT1_UID)
        g = self.game
        # Town target: the SNIPER leaves immediately (no roster impact).
        self.assertFalse(g.players[DOC_UID].is_alive)
        recs = [
            r
            for r in g.nmnd_night2_eliminations
            if r.get("uid") == DOC_UID and r.get("cause") == ELIM_CAUSE_SNIPER
        ]
        self.assertEqual(len(recs), 1)
        self.assertTrue(g.players[CIT1_UID].is_alive)
        # The mine casualty requirement (from the shot) still stands.
        self.assertTrue(g.nmnd_night2_mine_casualty_pending)

    async def test_sniper_boss_target_immune_no_kill_flag(self):
        self._fork12()
        await self._enter_night()
        await self._walk_sniper_mine(sniper_target=BOSS_UID)
        g = self.game
        self.assertTrue(g.players[BOSS_UID].is_alive)
        sniper_out = (g.nmnd_night2_outcome or {}).get("soldier_sniper") or {}
        self.assertEqual(sniper_out.get("reason"), "boss_immune")
        self.assertFalse(sniper_out.get("deferred", False))
        self.assertIsNone(g.nmnd_night2_sniper_mafia_kill_night)


def hacker_recs_cause_sniper(g):
    from bot.nam10.night2 import ELIM_CAUSE_SNIPER

    return [
        r
        for r in g.nmnd_night2_eliminations
        if r.get("uid") == SHIAD_UID and r.get("cause") == ELIM_CAUSE_SNIPER
    ]


class Room32GuideNoticeTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """Guide-identity disclosure delayed until Mafia actions settle."""

    async def _guide_picks_town_intercepted(self):
        """Guide picks a town recipient; the Hacker intercepts the grant."""
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=GUIDE_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=CIT1_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=CIT1_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)

    async def _guide_picks_mafia(self):
        """Guide selects a Mafia member (Hacker pair does not intercept)."""
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(GUIDE_UID, "gdsp", GUIDE_UID, tid=SHIAD_UID)
        await self._press(GUIDE_UID, "gdsok", GUIDE_UID)

    async def test_notice_withheld_until_shot_settled(self):
        from bot.nam10.night2 import (
            EXTRA_KIND_MAFIA_ID,
            night2_maybe_grant_guide_extra,
        )

        self._fork12()
        await self._enter_night()
        await self._guide_picks_mafia()
        g = self.game
        self.assertEqual(g.nmnd_night2_extra_kind, EXTRA_KIND_MAFIA_ID)
        # The Mafia shooter has not completed the shot: withheld.
        self.assertNotIn(
            NOTICE_MARK, "\n".join(self.bot.texts_to(SHIAD_UID))
        )
        self.assertFalse(
            g.nmnd_night2_dispositions.get(f"mafia_id_notified:{SHIAD_UID}")
        )
        # The shooter completes the shot -> exactly-once delivery.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        texts = self.bot.texts_to(SHIAD_UID)
        self.assertTrue(any(NOTICE_MARK in t for t in texts), texts)
        self.assertEqual(
            len([t for t in texts if NOTICE_MARK in t]), 1
        )
        self.assertEqual(
            g.nmnd_night2_dispositions.get(f"mafia_id_notified:{SHIAD_UID}"),
            "sent",
        )
        # Replay never duplicates.
        await night2_maybe_grant_guide_extra(self.bot, g)
        texts = self.bot.texts_to(SHIAD_UID)
        self.assertEqual(
            len([t for t in texts if NOTICE_MARK in t]), 1
        )

    async def test_notice_withheld_until_nato_stages_done(self):
        from bot.nam10.night2 import EXTRA_KIND_MAFIA_ID

        self._fork12()
        await self._enter_night()
        await self._guide_picks_mafia()
        g = self.game
        # Boss selects NATO: the pending obligation moves to the agent.
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=3)
        self.assertEqual(g.nmnd_night2_extra_kind, EXTRA_KIND_MAFIA_ID)
        self.assertNotIn(
            NOTICE_MARK, "\n".join(self.bot.texts_to(SHIAD_UID))
        )
        # The agent completes both stages -> notice delivers.
        await self._press(AGT_UID, "nrole", AGT_UID, tid=2)
        await self._press(AGT_UID, "nrok", AGT_UID)
        await self._press(AGT_UID, "npl", AGT_UID, tid=GUIDE_UID)
        await self._press(AGT_UID, "npok", AGT_UID)
        texts = self.bot.texts_to(SHIAD_UID)
        self.assertTrue(any(NOTICE_MARK in t for t in texts), texts)

    async def test_intercepted_grant_never_notifies(self):
        from bot.nam10.night2 import EXTRA_KIND_INTERCEPTED

        self._fork12()
        await self._enter_night()
        await self._guide_picks_town_intercepted()
        g = self.game
        self.assertEqual(g.nmnd_night2_extra_kind, EXTRA_KIND_INTERCEPTED)
        await self._press(BOSS_UID, "bmode", BOSS_UID, tid=1)
        await self._press(BOSS_UID, "sht", BOSS_UID, tid=CIT1_UID)
        await self._press(BOSS_UID, "shtok", BOSS_UID)
        self.assertNotIn(
            NOTICE_MARK, "\n".join(self.bot.texts_to(SHIAD_UID))
        )

    async def test_withholding_adds_no_readiness_key(self):
        """Delayed disclosure must never deadlock the night."""
        from bot.nam10.night2 import night2_required_keys

        self._fork12()
        await self._enter_night()
        await self._guide_picks_mafia()
        keys = night2_required_keys(self.game)
        # The withheld notice adds no extra obligation of its own: the
        # n2extra key stays absent (the MAFIA_ID grant owes nothing).
        self.assertNotIn("n2extra", keys)


class Room32PanelUiTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """Soldier/Sniper pick panels: two player buttons per row."""

    def _panel_rows(self, uid, body_mark):
        for text, kb in self.bot.kb_texts_to(uid):
            if body_mark in (text or "") and kb is not None:
                return kb.inline_keyboard
        return None

    async def test_soldier_panel_two_per_row(self):
        from bot.nam10.night2 import SOLDIER_PANEL_BODY

        self._fork12()
        await self._enter_night()
        rows = self._panel_rows(SOL_UID, SOLDIER_PANEL_BODY)
        self.assertIsNotNone(rows)
        # 11 alive targets -> 5 full pairs + one single-button tail,
        # then the confirm row.
        self.assertEqual([len(r) for r in rows], [2, 2, 2, 2, 2, 1, 1])

    async def test_sniper_panel_two_per_row(self):
        from bot.nam10.night2 import SNIPER_PANEL_BODY

        self._fork12()
        await self._enter_night()
        await self._press(DOC_UID, "docp", DOC_UID, tid=CIT1_UID)
        await self._press(DOC_UID, "docok", DOC_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=DOC_UID)
        await self._press(SHIAD_UID, "hacn", SHIAD_UID)
        await self._press(SHIAD_UID, "hacp", SHIAD_UID, tid=SYN_UID)
        await self._press(SHIAD_UID, "hacok", SHIAD_UID)
        await self._press(SOL_UID, "sldp", SOL_UID, tid=DOC_UID)
        await self._press(SOL_UID, "sldok", SOL_UID)
        rows = self._panel_rows(DOC_UID, SNIPER_PANEL_BODY)
        self.assertIsNotNone(rows)
        # 11 targets -> 5 pairs + 1 tail + confirm row; the voluntary
        # skip/no-shot row is removed by the mandatory-shot rule.
        self.assertEqual([len(r) for r in rows], [2, 2, 2, 2, 2, 1, 1])
        self.assertFalse(
            any(
                b.text and "انتخابی ندارم" in b.text
                for row in rows
                for b in row
            )
        )

    async def test_panel_buttons_keep_order_and_callbacks(self):
        from bot.nam10.night2 import SOLDIER_PANEL_BODY
        from bot.observer_delivery import PlayerMirrorCb

        self._fork12()
        await self._enter_night()
        rows = self._panel_rows(SOL_UID, SOLDIER_PANEL_BODY)
        self.assertIsNotNone(rows)
        flat = [b for row in rows for b in row]
        # First two buttons preserve the seat order of the target pool
        # and the original per-button callback payloads.
        first = PlayerMirrorCb.unpack(flat[0].callback_data)
        second = PlayerMirrorCb.unpack(flat[1].callback_data)
        self.assertEqual(first.as_uid, SOL_UID)
        self.assertEqual(second.as_uid, SOL_UID)
        self.assertNotEqual(first.tid, second.tid)
        self.assertEqual(first.act, second.act)


class Room32CongratulationTest(
    _exp.NamExpansionRoomTest, _BznPressMixin, metaclass=_SkipAllInherited
):
    """Public congratulation for a valid Sniper mafia elimination."""

    async def _summary(self, *, alive_before):
        from bot.nam10.nmnd_narrator import _night_report_outcome_section

        return _night_report_outcome_section(
            self.game, self.manager, alive_before, public=True
        )

    async def test_congratulation_for_sniper_mafia_kill(self):
        self._fork12()
        await self._enter_night()
        alive_before = {uid: p.is_alive for uid, p in self.game.players.items()}
        await Room32SniperMineTest._walk_sniper_mine(self)
        await Room32SniperMineTest._finish_casualty(
            self, casualty_uid=AGT_UID
        )
        lines = await self._summary(alive_before=alive_before)
        # Case B: both exits settled; the summary carries the line once.
        self.assertEqual(len([l for l in lines if CONGRAT_MARK in l]), 1)

    async def test_no_congratulation_without_sniper_kill(self):
        self._fork12()
        await self._enter_night()
        alive_before = {uid: p.is_alive for uid, p in self.game.players.items()}
        # Mine-only mafia consequence (shot on a mined target, no sniper).
        await self._walk12(
            boss_tid=1,
            shot_target=SOL_UID,
            doc_pick=DOC_UID,
            soldier_target=None,
            mine_pick=SOL_UID,
            law_pick=0,
            do_extra=False,
        )
        await Room32SniperMineTest._finish_casualty(
            self, casualty_uid=AGT_UID
        )
        lines = await self._summary(alive_before=alive_before)
        self.assertEqual([l for l in lines if CONGRAT_MARK in l], [])

    async def test_no_congratulation_for_stale_night(self):
        self._fork12()
        g = self.game
        await self._enter_night()
        alive_before = {uid: p.is_alive for uid, p in g.players.items()}
        await Room32SniperMineTest._walk_sniper_mine(self)
        await Room32SniperMineTest._finish_casualty(
            self, casualty_uid=AGT_UID
        )
        # A later summary (next night's report) never re-shows it.
        g.nmnd_narrator_night_count += 1
        lines = await self._summary(alive_before=alive_before)
        self.assertEqual([l for l in lines if CONGRAT_MARK in l], [])


if __name__ == "__main__":
    unittest.main()
