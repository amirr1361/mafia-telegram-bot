#!/usr/bin/env python3
"""Room 38 (12-player Namayande) regressions — two fixes.

1. Rebel assassination unlock: eliminating the independent NATO
   (ناتو / Role.NATO_AGENT) must unlock the Rebel's once-per-game
   daytime assassination — in 12/13 compositions, via BOTH the day
   elimination pathway and the night elimination applier. Also pins the
   Day-1 gate fix (the v2 mode flag is not set yet during Day 1) and the
   Day-1 defence-outcome activation dispatch.
2. Mafia team introduction: the intro-night roster lists every Mafia
   teammate including the NATO agent, and alive synthetic Mafia seats
   receive their roster via the registered Observer mirror.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/root/mafia-telegram-bot")
os.chdir("/root/mafia-telegram-bot")

import tests.test_namayande10_expansion as _exp  # noqa: E402
import tests.test_namayande10_night_v2 as _v2  # noqa: E402
from tests.test_namayande10_day1_elim_report import (  # noqa: E402
    Nam10Day1ElimReportTest,
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
from tests.test_namayande10_expansion import (  # noqa: E402
    AGT_UID,
    CIT2_UID,
    SOL_UID,
)

from bot.models import Phase, Player  # noqa: E402
from bot.nam10.nmnd_narrator import DAY_DISCUSS, Role  # noqa: E402
from bot.nam10.night2 import (  # noqa: E402
    night2_apply_elimination,
    night2_rebel_assassination_available,
    night2_rebel_assassination_unlocked,
    nam10_night2_entry_dispatch,
)

ROSTER_SENTINEL = "📋 <b>اعضای تیم مافیا:</b>"
NOTICE_SENTINEL = "قابلیت ترور فعال شد"
CIVILIAN_SENTINEL = "چشم‌های خود را ببندید"


def _rec_texts_to(bot, uid: int) -> list[str]:
    """Texts recorded by the Day-1 _RecordingBot for one chat."""
    return [t for chat, t in bot.sends() if chat == uid]


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


class Room38RebelUnlockTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """Durable unlock triggers for the Rebel assassination."""

    def _audit_events(self):
        import json

        path = self.game.audit_log_path
        if not path:
            return []
        out = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    def _unlocked_events(self):
        return [
            e for e in self._audit_events()
            if e.get("event") == "night2.rebel_assassination_unlocked"
        ]

    async def test_nato_agent_night_elim_unlocks_rebel(self):
        self._fork12()
        await self._enter_night()
        self.assertFalse(night2_rebel_assassination_unlocked(self.game))
        night2_apply_elimination(self.game, AGT_UID, "mafia_shot")
        self.assertTrue(night2_rebel_assassination_unlocked(self.game))
        self.assertTrue(night2_rebel_assassination_available(self.game))
        evs = self._unlocked_events()
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].get("trigger_uid"), AGT_UID)

    async def test_nato_agent_day_elim_unlocks_rebel(self):
        """Day-1 pathway: the v2 mode flag is NOT set yet (Room 38)."""
        from bot.nam10.nmnd_narrator import eliminate_player_from_game

        self._fork12()
        self.assertFalse(self.game.nmnd_night2_mode)
        eliminate_player_from_game(
            self.game, self.manager, AGT_UID, elim_source="day_vote"
        )
        self.assertFalse(self.game.players[AGT_UID].is_alive)
        self.assertTrue(night2_rebel_assassination_unlocked(self.game))
        self.assertTrue(night2_rebel_assassination_available(self.game))
        self.assertEqual(self._unlocked_events()[0].get("trigger_uid"), AGT_UID)

    async def test_unlock_fires_once_for_multiple_triggers(self):
        self._fork12()
        await self._enter_night()
        night2_apply_elimination(self.game, BOSS_UID, "mafia_shot")
        night2_apply_elimination(self.game, AGT_UID, "mine_mafia")
        self.assertTrue(night2_rebel_assassination_unlocked(self.game))
        self.assertEqual(len(self._unlocked_events()), 1)

    async def test_dead_rebel_receives_nothing(self):
        self._fork12()
        await self._enter_night()
        # The Rebel dying does NOT unlock (not a trigger role) ...
        night2_apply_elimination(self.game, NATO_UID, "mafia_shot")
        self.assertFalse(night2_rebel_assassination_unlocked(self.game))
        # ... and once unlocked, a dead Rebel is never eligible.
        night2_apply_elimination(self.game, AGT_UID, "mafia_shot")
        self.assertTrue(night2_rebel_assassination_unlocked(self.game))
        self.assertFalse(night2_rebel_assassination_available(self.game))

    async def test_used_assassination_is_not_reactivated(self):
        self._fork12()
        await self._enter_night()
        g = self.game
        g.nmnd_night2_rebel_assassin_used = True
        g.nmnd_night2_rebel_assassin_used_night = 1
        night2_apply_elimination(self.game, AGT_UID, "mafia_shot")
        self.assertTrue(night2_rebel_assassination_unlocked(self.game))
        self.assertFalse(night2_rebel_assassination_available(self.game))
        self.assertTrue(g.nmnd_night2_rebel_assassin_used)
        self.assertEqual(g.nmnd_night2_rebel_assassin_used_night, 1)

    async def test_unlock_survives_snapshot_restore(self):
        from bot.game import GameManager
        from bot.game_snapshot import (
            persist_game_snapshot,
            restore_games_into_manager,
        )

        self._fork12()
        night2_apply_elimination(self.game, AGT_UID, "mafia_shot")
        persist_game_snapshot(self.game, reason="test_room38")
        code = self.game.room_code
        self.manager.games.pop(code, None)
        self.manager.host_to_room.pop(self.game.host_id, None)
        m2 = GameManager()
        restore_games_into_manager(m2)
        back = m2.get_game(code)
        self.assertIsNotNone(back)
        self.assertTrue(night2_rebel_assassination_unlocked(back))
        self.assertTrue(night2_rebel_assassination_available(back))

    async def test_notice_and_next_day_panel_after_agent_elim(self):
        """Night trigger: unlock persists; notice + panel at the day open."""
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        self._fork12()
        await self._enter_night()
        night2_apply_elimination(self.game, AGT_UID, "mafia_shot")
        # Day opening (after the night report / table inquiry).
        self.game.nmnd_narrator_step = DAY_DISCUSS
        await send_nam10_rebel_day_opening(self.bot, self.game)
        g = self.game
        self.assertTrue(g.nmnd_night2_rebel_notice_sent)
        self.assertIn(
            NOTICE_SENTINEL, "\n".join(self.bot.texts_to(NATO_UID))
        )
        self.assertEqual(g.nmnd_night2_rebel_stage, "entry")
        self.assertEqual(g.nmnd_night2_rebel_panel_day, 1)
        self.assertTrue(
            any(
                e.get("event") == "night2.rebel_entry_panel_delivered"
                for e in self._audit_events()
            )
        )

    async def test_cutoff_day_blocks_same_day_panel(self):
        """After the defence-candidates cutoff: notice only, no panel."""
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        self._fork12()
        await self._enter_night()
        night2_apply_elimination(self.game, AGT_UID, "mafia_shot")
        self.game.nmnd_narrator_step = DAY_DISCUSS
        self.game.nmnd_night2_rebel_cutoff_day = 1
        await send_nam10_rebel_day_opening(self.bot, self.game)
        self.assertTrue(self.game.nmnd_night2_rebel_notice_sent)
        self.assertIsNone(self.game.nmnd_night2_rebel_stage)
        # The unused opportunity stays preserved for a later day.
        self.assertTrue(night2_rebel_assassination_available(self.game))


class Room38Day1OutcomeActivationTest(
    Nam10Day1ElimReportTest, metaclass=_SkipAllInherited
):
    """Real Day-1 defence-outcome callback (Room 38's exact pathway)."""

    def _fork_room(self, *, with_observer: bool = True):
        from bot.game_audit_log import init_audit_log

        game = self.manager.create_game(
            host_id=1,
            scenario_name="namayande",
            max_players=12,
            nam10_no_host=True,
        )
        assert game is not None
        seat = 0
        for uid in _exp.REAL_12:
            seat += 1
            err = self.manager.add_player(
                game,
                Player(
                    user_id=uid,
                    full_name=f"بازیکن {seat}",
                    username=None,
                    role=None,
                    is_alive=True,
                    seat=seat,
                ),
            )
            assert err is None, err
        team_map = {
            BOSS_UID: Role.MAFIA_BOSS,
            NATO_UID: Role.NATO,
            SHIAD_UID: Role.SHIAD,
            AGT_UID: Role.NATO_AGENT,
            SOL_UID: Role.SOLDIER,
        }
        for uid, pl in game.players.items():
            pl.role = team_map.get(uid, Role.CITIZEN)
        game.roles_dealt = True
        game.phase = Phase.MANUAL
        game.bot_assistant_user_id = ASSIST_UID
        game.nam10_assistant_narrator_active = True
        game.nam10_intro_night_started = True
        game.nmnd_narrator_host_day = 1
        game.nmnd_narrator_step = DAY_DISCUSS
        if with_observer:
            game.observer_user_id = OBS_UID
            game.observer_prompt_status = "registered"
        init_audit_log(game)
        self.game = game
        return game

    async def _walk_to_stage_a(self):
        await self._funnel()
        await self._press(ASSIST_UID, "d1ri", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=DOC_UID)
        await self._press(ASSIST_UID, "d1rt", ASSIST_UID, tid=SHIAD_UID)
        await self._press(ASSIST_UID, "d1ro", ASSIST_UID)
        await self._press(ASSIST_UID, "d1na", ASSIST_UID)

    async def _walk_to_outcome(self, t1=AGT_UID, t2=GUIDE_UID):
        await self._walk_to_stage_a()
        await self._boss_choose("add", DOC_UID)
        await self._ack_all_waiting()
        await self._press(ASSIST_UID, "d1to", ASSIST_UID)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=t1)
        await self._press(ASSIST_UID, "d1tt", ASSIST_UID, tid=t2)
        await self._press(ASSIST_UID, "d1tok", ASSIST_UID)
        await self._press(ASSIST_UID, "d1rv", ASSIST_UID)

    async def test_defense_outcome_nato_agent_elim_unlocks_rebel(self):
        from bot.nam10.rebel_day import send_nam10_rebel_day_opening

        self._fork_room()
        await self._walk_to_outcome(t1=AGT_UID, t2=DOC_UID)
        await self._press(ASSIST_UID, "d1o1", ASSIST_UID)
        g = self.game
        # The NATO agent was eliminated by the Day-1 defence outcome and
        # the Rebel assassination unlocked (v2 mode still off).
        self.assertFalse(g.players[AGT_UID].is_alive)
        self.assertTrue(night2_rebel_assassination_unlocked(g))
        self.assertTrue(night2_rebel_assassination_available(g))
        # Day-1 surface: window already closed at the outcome stage, so
        # the activation surfaces at the next day opening.
        self.assertFalse(g.nmnd_night2_rebel_notice_sent)
        # Night 1 hands over to v2, then the day-2 opening delivers
        # notice + panel.
        g.nam10_day1_stage = "day1_night_entered"
        self.assertTrue(
            await nam10_night2_entry_dispatch(self.bot, g, self.manager)
        )
        self.assertTrue(g.nmnd_night2_mode)
        g.nmnd_narrator_step = DAY_DISCUSS
        await send_nam10_rebel_day_opening(self.bot, g)
        self.assertTrue(g.nmnd_night2_rebel_notice_sent)
        self.assertIn(
            NOTICE_SENTINEL, "\n".join(_rec_texts_to(self.bot, NATO_UID))
        )
        self.assertEqual(g.nmnd_night2_rebel_stage, "entry")

    async def test_defense_outcome_no_elim_keeps_rebel_locked(self):
        self._fork_room()
        await self._walk_to_outcome(t1=DOC_UID, t2=GUIDE_UID)
        await self._press(ASSIST_UID, "d1o0", ASSIST_UID)
        self.assertFalse(night2_rebel_assassination_unlocked(self.game))


class Room38MafiaIntroTest(
    _exp.NamExpansionRoomTest, metaclass=_SkipAllInherited
):
    """Mafia team-introduction roster (NATO included)."""

    async def _deliver(self):
        from bot.nam10.dayflow import (
            deliver_no_host_intro_night_started_messages,
        )

        await deliver_no_host_intro_night_started_messages(
            self.bot, self.game
        )

    async def test_roster_includes_nato_agent_12(self):
        self._fork12()
        await self._deliver()
        text = "\n".join(self.bot.texts_to(AGT_UID))
        self.assertIn(ROSTER_SENTINEL, text)
        self.assertIn("ناتو", text)   # the agent's own line
        self.assertIn("یاغی", text)   # the Rebel teammate line
        # Every other Mafia member sees the same complete roster.
        for uid in (BOSS_UID, NATO_UID, SHIAD_UID):
            t = "\n".join(self.bot.texts_to(uid))
            self.assertIn(ROSTER_SENTINEL, t)
            self.assertIn("ناتو", t)

    async def test_roster_includes_nato_agent_13(self):
        self._fork12(players_13=True)
        await self._deliver()
        text = "\n".join(self.bot.texts_to(AGT_UID))
        self.assertIn(ROSTER_SENTINEL, text)
        self.assertIn("ناتو", text)
        self.assertIn("یاغی", text)

    async def test_citizens_receive_no_roster(self):
        self._fork12()
        await self._deliver()
        t = "\n".join(self.bot.texts_to(CIT1_UID))
        self.assertIn(CIVILIAN_SENTINEL, t)
        self.assertNotIn(ROSTER_SENTINEL, t)

    async def test_observer_gets_no_roster_when_all_mafia_real(self):
        self._fork12()
        await self._deliver()
        t = "\n".join(self.bot.texts_to(OBS_UID))
        self.assertIn(CIVILIAN_SENTINEL, t)
        self.assertNotIn(ROSTER_SENTINEL, t)

    async def test_synthetic_agent_roster_mirrored_to_observer(self):
        from bot.models import Role

        self._fork12()
        # Room 48 shape: the synthetic seat holds the NATO agent role.
        self.game.players[SYN_UID].role = Role.NATO_AGENT
        self.game.players[AGT_UID].role = Role.CITIZEN
        await self._deliver()
        obs = "\n".join(self.bot.texts_to(OBS_UID))
        self.assertIn(ROSTER_SENTINEL, obs)
        self.assertIn("ناتو", obs)
        self.assertIn(SYN_UID, self.game.nmnd_intro_night_delivered_uids)
        # Idempotent: a second delivery does not duplicate the mirror.
        n_before = obs.count(ROSTER_SENTINEL)
        await self._deliver()
        self.assertEqual(
            "\n".join(self.bot.texts_to(OBS_UID)).count(ROSTER_SENTINEL),
            n_before,
        )

    async def test_failed_mirror_send_not_marked_delivered(self):
        from unittest.mock import AsyncMock, patch

        self._fork12()
        self.game.players[SYN_UID].role = Role.NATO_AGENT
        self.game.players[AGT_UID].role = Role.CITIZEN
        with patch(
            "bot.nam10.dayflow.safe_send_message",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await self._deliver()
        self.assertNotIn(
            SYN_UID, self.game.nmnd_intro_night_delivered_uids
        )


if __name__ == "__main__":
    unittest.main()
